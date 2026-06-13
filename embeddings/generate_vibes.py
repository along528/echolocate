"""
Classify every track against a fixed "vibe" vocabulary and write the top tags
as a JSON-array string into the `vibes` column.

Each vibe is text-anchored in CLAP space: its prompt(s) are encoded and averaged
into a unit anchor vector (the same trick `generate_projection.py --method
clap-axes` uses for its axes). Every track's `v_clap` embedding is then scored by
cosine similarity against all anchors, and the top-k vibes (optionally above a
similarity floor) are stored. Because the vocabulary is fixed and query-stable,
the tags are comparable across tracks and cheap to surface in the UI (chips on
list rows / now-playing / the detail card).

The column is written back exactly like `generate_projection.py` writes x,y, so:

    Run against the full DB (../data/cloudcrate.duckdb) BEFORE generate_index_db.py
    so the stripped index inherits the `vibes` column.

Usage:
    python generate_vibes.py [--top-k 3] [--min-sim 0.0]
                             [--db PATH] [--vocab-out PATH]
"""

import argparse
import json
import os
import time

import duckdb
import numpy as np
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "../data/cloudcrate.duckdb")
DEFAULT_VOCAB = os.path.join(BASE_DIR, "../data/vibe_anchors.json")

CLAP_MODEL_NAME = "laion/clap-htsat-unfused"
TABLES = ["tracks_library", "tracks_fma"]

# Fixed vibe vocabulary. Each label maps to one or more text prompts that are
# encoded and averaged into a single anchor. Edit and re-run to re-aim the tags;
# keep labels short — they render as chips in the UI.
VIBE_PROMPTS = {
    "warm": ["warm, cozy music", "rich and warm sounding"],
    "dark": ["dark, brooding music", "ominous and shadowy"],
    "bright": ["bright, sparkling music", "shimmering and luminous"],
    "dreamy": ["dreamy, ethereal music", "hazy and atmospheric"],
    "energetic": ["energetic, high-energy music", "driving and intense"],
    "mellow": ["mellow, laid-back music", "smooth and relaxed"],
    "melancholic": ["melancholic, sad music", "wistful and sorrowful"],
    "uplifting": ["uplifting, joyful music", "happy and feel-good"],
    "aggressive": ["aggressive, heavy music", "harsh and abrasive"],
    "lo-fi": ["lo-fi music", "dusty, tape-saturated, lo-fi production"],
    "acoustic": ["acoustic music", "organic, hand-played instruments"],
    "electronic": ["electronic music", "synthesizers and drum machines"],
    "groovy": ["groovy, funky music", "syncopated and danceable"],
    "cinematic": ["cinematic, epic music", "sweeping and film-score-like"],
    "psychedelic": ["psychedelic music", "trippy, swirling textures"],
    "minimal": ["minimal, sparse music", "stripped-back and spacious"],
    "lush": ["lush, dense music", "thick, layered arrangement"],
    "danceable": ["danceable, club music", "four-on-the-floor dance beat"],
}


def ensure_vibes_column(con, table):
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
    }
    if "vibes" not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN vibes VARCHAR;")


def load_clap_vectors(con):
    """Return (ids, table_of, matrix) for all tracks with a non-null v_clap."""
    ids, table_of, vecs = [], [], []
    for table in TABLES:
        ensure_vibes_column(con, table)
        rows = con.execute(f"SELECT id, v_clap FROM {table}").fetchall()
        for tid, vec in tqdm(rows, desc=f"Reading v_clap from {table}", unit="trk"):
            if vec is None:
                continue
            ids.append(tid)
            table_of.append(table)
            vecs.append(np.asarray(vec, dtype=np.float32))
    if not ids:
        raise SystemExit("No tracks with v_clap found.")
    return ids, table_of, np.vstack(vecs)


def build_anchors(vocab_out):
    """Encode the vibe vocabulary into a (num_vibes, dim) unit-anchor matrix."""
    import torch
    from transformers import AutoProcessor, ClapModel

    device = torch.device("cpu")
    print(f"Loading CLAP model: {CLAP_MODEL_NAME}...")
    model = ClapModel.from_pretrained(CLAP_MODEL_NAME).to(device)
    processor = AutoProcessor.from_pretrained(CLAP_MODEL_NAME)
    model.eval()

    def encode(texts):
        inputs = processor(text=texts, return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            feats = model.get_text_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy()

    labels = list(VIBE_PROMPTS.keys())
    anchors = []
    for label in labels:
        vecs = encode(VIBE_PROMPTS[label])
        anchor = vecs.mean(axis=0)
        anchor = anchor / (np.linalg.norm(anchor) + 1e-12)
        anchors.append(anchor)
    anchors = np.vstack(anchors).astype(np.float32)

    os.makedirs(os.path.dirname(vocab_out), exist_ok=True)
    with open(vocab_out, "w") as f:
        json.dump(
            {"model": CLAP_MODEL_NAME, "prompts": VIBE_PROMPTS,
             "labels": labels, "anchors": anchors.tolist()},
            f, indent=2,
        )
    print(f"Saved vibe anchors to {vocab_out}")
    return labels, anchors


def assign_vibes(matrix, labels, anchors, top_k, min_sim):
    """Return a list of JSON-array strings (one per track) of the top-k vibes."""
    # L2-normalize track vectors so the dot product is cosine similarity.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    sims = unit @ anchors.T  # (num_tracks, num_vibes)

    labels_arr = np.asarray(labels)
    out = []
    for row in tqdm(sims, desc="Assigning vibes", unit="trk"):
        order = np.argsort(row)[::-1][:top_k]
        picked = [labels_arr[i] for i in order if row[i] >= min_sim]
        out.append(json.dumps(list(picked)) if picked else None)
    return out


def write_vibes(con, ids, table_of, vibes):
    con.execute("CREATE TEMP TABLE vibe_tmp (id VARCHAR, tbl VARCHAR, vibes VARCHAR);")
    rows = list(zip(ids, table_of, vibes))
    chunk = 5000
    for i in tqdm(range(0, len(rows), chunk), desc="Loading vibes", unit="chunk"):
        con.executemany("INSERT INTO vibe_tmp VALUES (?, ?, ?)", rows[i:i + chunk])
    for table in TABLES:
        con.execute(
            f"UPDATE {table} SET vibes = v.vibes FROM vibe_tmp v "
            f"WHERE {table}.id = v.id AND v.tbl = ?;",
            [table],
        )
        updated = con.execute(f"SELECT COUNT(*) FROM {table} WHERE vibes IS NOT NULL").fetchone()[0]
        print(f"  Wrote vibes for {updated} rows in {table}.")
    con.execute("DROP TABLE vibe_tmp;")
    con.execute("CHECKPOINT;")


def generate_vibes(db_path, top_k, min_sim, vocab_out):
    if not os.path.exists(db_path):
        raise SystemExit(f"Database not found: {db_path}")

    start = time.time()
    con = duckdb.connect(db_path)
    # The tables carry persistent HNSW indexes; VSS must be loaded before they
    # can be altered/updated.
    con.execute("INSTALL vss; LOAD vss; SET hnsw_enable_experimental_persistence = true;")

    ids, table_of, matrix = load_clap_vectors(con)
    print(f"Loaded {matrix.shape[0]} v_clap vectors of dim {matrix.shape[1]}.")

    labels, anchors = build_anchors(vocab_out)
    print(f"Built {len(labels)} vibe anchors: {labels}")

    vibes = assign_vibes(matrix, labels, anchors, top_k, min_sim)
    tagged = sum(1 for v in vibes if v is not None)
    write_vibes(con, ids, table_of, vibes)

    con.close()
    print(f"\nDone in {time.time() - start:.1f}s. Tagged {tagged}/{len(ids)} tracks "
          f"(top_k={top_k}, min_sim={min_sim}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify tracks into vibe tags")
    parser.add_argument("--top-k", type=int, default=3, help="Max vibes per track")
    parser.add_argument("--min-sim", type=float, default=0.0,
                        help="Minimum cosine similarity to keep a vibe (0 = always keep top-k)")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--vocab-out", default=DEFAULT_VOCAB)
    args = parser.parse_args()

    generate_vibes(args.db, args.top_k, args.min_sim, args.vocab_out)
