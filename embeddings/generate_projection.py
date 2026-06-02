"""
Compute 2D "sonar map" coordinates for every track and write them as x,y columns.

Three projection methods are available (``--method``):

  pca        (default)  First 2 principal components of the chosen embedding. Axes
                        are the directions of maximum variance (not interpretable),
                        but capture the dominant structure. Min-max normalized.
                        This is what we ship: PCA on the MERT `v_mid` vector.

  clap-axes             Semantic, interpretable axes. Each axis is a CLAP
                        text-anchored direction (the normalized difference between
                        mean "positive-pole" and "negative-pole" prompt embeddings);
                        each track's v_clap is projected onto the two axes. The axes
                        mean exactly what the frontend labels say
                        (X: acoustic->synthetic, Y: dark->bright), and coordinates
                        are query-stable. Percentile-rank normalized for even spread.
                        Requires --vector clap.

  umap                  UMAP 2D embedding (requires `umap-learn`). Preserves local
                        neighborhoods -> visually tighter clusters, arbitrary axes.
                        Min-max normalized. Slower; good for exploration.

All three write the SAME x,y columns and the same downstream contract, so the
method is a drop-in choice with no frontend/API changes.

Usage:
    python generate_projection.py [--method pca|clap-axes|umap]
                                  [--vector mid|clap] [--normalize rank|minmax]
                                  [--db PATH] [--anchors-out PATH]

    # Shipping config (defaults): PCA on the MERT v_mid vector
    python generate_projection.py

Run against the full DB (../data/cloudcrate.duckdb) BEFORE generate_index_db.py
so the stripped index inherits the x,y columns.
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
DEFAULT_ANCHORS = os.path.join(BASE_DIR, "../data/projection_anchors.json")

CLAP_MODEL_NAME = "laion/clap-htsat-unfused"
TABLES = ["tracks_library", "tracks_fma"]
VECTOR_COLUMN = {"clap": "v_clap", "mid": "v_mid"}

# Text anchors per axis pole (clap-axes only). Multiple prompts per pole are
# averaged for robustness. Edit and re-run to re-aim the axes.
AXES = {
    "x": {  # acoustic/organic (0) -> electronic/synthetic (1)
        "negative": [
            "acoustic music",
            "organic, hand-played instruments",
            "unplugged, natural recording",
        ],
        "positive": [
            "electronic music",
            "synthetic, digital production",
            "synthesizers and drum machines",
        ],
    },
    "y": {  # dark/introspective (0) -> bright/energetic (1)
        "negative": [
            "dark, introspective music",
            "melancholic and somber",
            "slow and brooding",
        ],
        "positive": [
            "bright, energetic music",
            "upbeat and lively",
            "high-energy and cheerful",
        ],
    },
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_vectors(con, vector_col):
    """Return (ids, table_of, matrix) for all tracks with a non-null vector."""
    ids, table_of, vecs = [], [], []
    for table in TABLES:
        ensure_columns(con, table)
        rows = con.execute(f"SELECT id, {vector_col} FROM {table}").fetchall()
        for tid, vec in tqdm(rows, desc=f"Reading {vector_col} from {table}", unit="trk"):
            if vec is None:
                continue
            ids.append(tid)
            table_of.append(table)
            vecs.append(np.asarray(vec, dtype=np.float32))
    if not ids:
        raise SystemExit(f"No tracks with {vector_col} found.")
    return ids, table_of, np.vstack(vecs)


# ---------------------------------------------------------------------------
# Projection methods -> raw (x, y) arrays
# ---------------------------------------------------------------------------
def project_clap_axes(matrix, anchors_out):
    """CLAP text-anchored semantic axes. Returns (x_raw, y_raw)."""
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

    def build_axis(pos, neg):
        axis = encode(pos).mean(axis=0) - encode(neg).mean(axis=0)
        return axis / np.linalg.norm(axis)

    x_axis = build_axis(AXES["x"]["positive"], AXES["x"]["negative"])
    y_axis = build_axis(AXES["y"]["positive"], AXES["y"]["negative"])

    os.makedirs(os.path.dirname(anchors_out), exist_ok=True)
    with open(anchors_out, "w") as f:
        json.dump(
            {"model": CLAP_MODEL_NAME, "axes": AXES,
             "x_axis": x_axis.tolist(), "y_axis": y_axis.tolist()},
            f, indent=2,
        )
    print(f"Saved projection anchors to {anchors_out}")

    return matrix @ x_axis, matrix @ y_axis


def project_pca(matrix):
    """First 2 principal components via the 512x512 covariance eigendecomposition."""
    print("Computing PCA (top 2 components)...")
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    # Covariance is small (D x D); eigh is cheap and stable.
    cov = (centered.T @ centered) / max(1, centered.shape[0] - 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    top2 = eigvecs[:, np.argsort(eigvals)[::-1][:2]]  # (D, 2)
    scores = centered @ top2
    return scores[:, 0], scores[:, 1]


def project_umap(matrix):
    """UMAP 2D embedding. Requires `umap-learn` (pip install umap-learn)."""
    try:
        import umap  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "umap requested but `umap-learn` is not installed. "
            "Run: pip install umap-learn"
        ) from e
    print("Fitting UMAP (this can take a few minutes)...")
    reducer = umap.UMAP(n_components=2, metric="cosine", random_state=42, verbose=True)
    coords = reducer.fit_transform(matrix)
    return coords[:, 0], coords[:, 1]


# ---------------------------------------------------------------------------
# Normalization + write-back
# ---------------------------------------------------------------------------
def percentile_rank(values):
    """Map to [0,1] by rank: uniform spread, robust to outliers."""
    n = len(values)
    if n <= 1:
        return np.full(n, 0.5)
    return np.argsort(np.argsort(values)) / (n - 1)


def minmax(values):
    """Map to [0,1] linearly, preserving relative geometry."""
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi - lo < 1e-12:
        return np.full(len(values), 0.5)
    return (values - lo) / (hi - lo)


def ensure_columns(con, table):
    existing = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
    }
    for col in ("x", "y"):
        if col not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} DOUBLE;")


def write_coords(con, ids, table_of, x_norm, y_norm):
    con.execute("CREATE TEMP TABLE proj_tmp (id VARCHAR, tbl VARCHAR, x DOUBLE, y DOUBLE);")
    rows = list(zip(ids, table_of, x_norm.tolist(), y_norm.tolist()))
    chunk = 5000
    for i in tqdm(range(0, len(rows), chunk), desc="Loading coordinates", unit="chunk"):
        con.executemany("INSERT INTO proj_tmp VALUES (?, ?, ?, ?)", rows[i:i + chunk])
    for table in TABLES:
        con.execute(
            f"UPDATE {table} SET x = p.x, y = p.y FROM proj_tmp p "
            f"WHERE {table}.id = p.id AND p.tbl = ?;",
            [table],
        )
        updated = con.execute(f"SELECT COUNT(*) FROM {table} WHERE x IS NOT NULL").fetchone()[0]
        print(f"  Wrote coordinates for {updated} rows in {table}.")
    con.execute("DROP TABLE proj_tmp;")
    con.execute("CHECKPOINT;")


def generate_projection(db_path, method, vector, normalize, anchors_out):
    if not os.path.exists(db_path):
        raise SystemExit(f"Database not found: {db_path}")

    if method == "clap-axes" and vector != "clap":
        raise SystemExit("clap-axes requires --vector clap (axes live in CLAP space).")

    start = time.time()
    con = duckdb.connect(db_path)
    # The tables carry persistent HNSW indexes; VSS must be loaded before they
    # can be altered/updated.
    con.execute("INSTALL vss; LOAD vss; SET hnsw_enable_experimental_persistence = true;")

    ids, table_of, matrix = load_vectors(con, VECTOR_COLUMN[vector])
    print(f"Loaded {matrix.shape[0]} vectors of dim {matrix.shape[1]}. Method: {method}")

    if method == "clap-axes":
        x_raw, y_raw = project_clap_axes(matrix, anchors_out)
    elif method == "pca":
        x_raw, y_raw = project_pca(matrix)
    elif method == "umap":
        x_raw, y_raw = project_umap(matrix)
    else:
        raise SystemExit(f"Unknown method: {method}")

    norm = percentile_rank if normalize == "rank" else minmax
    write_coords(con, ids, table_of, norm(np.asarray(x_raw)), norm(np.asarray(y_raw)))

    con.close()
    print(f"\nDone in {time.time() - start:.1f}s. Projected {len(ids)} tracks ({method}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute 2D sonar-map coordinates")
    parser.add_argument("--method", choices=["clap-axes", "pca", "umap"], default="pca")
    parser.add_argument("--vector", choices=["clap", "mid"], default="mid",
                        help="Which embedding to project (mid=768 MERT sonic, clap=512 semantic)")
    parser.add_argument("--normalize", choices=["rank", "minmax"], default=None,
                        help="Defaults: rank for clap-axes, minmax for pca/umap")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--anchors-out", default=DEFAULT_ANCHORS)
    args = parser.parse_args()

    normalize = args.normalize or ("rank" if args.method == "clap-axes" else "minmax")
    generate_projection(args.db, args.method, args.vector, normalize, args.anchors_out)
