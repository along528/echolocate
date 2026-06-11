"""
Tier 1: zero-shot reverse-CLAP tagging.

Embeds the vocabulary.json phrases with the CLAP text encoder, scores every
track's existing v_clap against each tag anchor, and assigns top-k tags per
category after per-tag z-score calibration.

Why z-scores: CLAP audio and text embeddings live in different cones of the
joint space (the "modality gap"), so raw cosine values are not comparable
across anchors — some phrases are systematically closer to ALL audio. A tag's
scores are therefore standardized across the corpus, and a tag is assigned
only when a track is unusually close to it relative to everything else.

Usage:
    python generate_tags.py [--db PATH] [--vocabulary PATH] [--output PATH]
                            [--anchors-out PATH] [--stats]

    --stats   Print per-tag coverage and top exemplar tracks without writing
              the output JSONL (for vocabulary iteration).

Output: data/descriptions/tags.jsonl, one line per track:
    {"id", "table", "tags" (flat list), "tags_by_category", "tag_scores"}
"""

import argparse
import json
import os
import time

import numpy as np
from tqdm import tqdm

from clap_text import CLAP_MODEL_NAME, ClapTextEncoder
from corpus import ARTIFACTS_DIR, DEFAULT_DB, connect, load_clap_vectors

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VOCABULARY = os.path.join(BASE_DIR, "vocabulary.json")
DEFAULT_OUTPUT = os.path.join(ARTIFACTS_DIR, "tags.jsonl")
DEFAULT_ANCHORS = os.path.join(ARTIFACTS_DIR, "tag_anchors.json")


def load_vocabulary(path):
    with open(path) as f:
        vocab = json.load(f)
    categories = vocab["categories"]
    # Flatten to parallel lists: tag order defines anchor-matrix row order.
    tag_names, tag_category, prompts_per_tag = [], [], []
    for cat_name, cat in categories.items():
        for tag, prompts in cat["tags"].items():
            tag_names.append(tag)
            tag_category.append(cat_name)
            prompts_per_tag.append(prompts)
    return categories, tag_names, tag_category, prompts_per_tag


def build_anchors(encoder, tag_names, prompts_per_tag, anchors_out):
    """Encode prompts and average per tag -> (T, 512) normalized anchors."""
    flat_prompts = [p for prompts in prompts_per_tag for p in prompts]
    print(f"Encoding {len(flat_prompts)} prompts for {len(tag_names)} tags...")
    flat = encoder.encode(flat_prompts)

    anchors = np.zeros((len(tag_names), flat.shape[1]), dtype=np.float32)
    i = 0
    for t, prompts in enumerate(prompts_per_tag):
        mean = flat[i:i + len(prompts)].mean(axis=0)
        anchors[t] = mean / np.linalg.norm(mean)
        i += len(prompts)

    os.makedirs(os.path.dirname(anchors_out), exist_ok=True)
    with open(anchors_out, "w") as f:
        json.dump(
            {"model": CLAP_MODEL_NAME, "tags": tag_names,
             "anchors": anchors.tolist()},
            f,
        )
    print(f"Saved tag anchors to {anchors_out}")
    return anchors


def assign_tags(z_row, cos_row, categories, tag_names, tag_category):
    """Pick top-k tags per category gated at min_z. Returns (by_category, scores)."""
    by_category, scores = {}, {}
    for cat_name, cat in categories.items():
        idx = [t for t, c in enumerate(tag_category) if c == cat_name]
        idx.sort(key=lambda t: z_row[t], reverse=True)
        chosen = [t for t in idx[: cat["top_k"]] if z_row[t] >= cat["min_z"]]
        if chosen:
            by_category[cat_name] = [tag_names[t] for t in chosen]
            for t in chosen:
                scores[tag_names[t]] = {
                    "z": round(float(z_row[t]), 3),
                    "cos": round(float(cos_row[t]), 4),
                }
    return by_category, scores


def print_stats(z, cos, categories, tag_names, tag_category, ids, con):
    """Per-tag coverage report for vocabulary iteration."""
    n = z.shape[0]
    # Re-run assignment per track to count actual (top-k gated) coverage.
    counts = {tag: 0 for tag in tag_names}
    for i in tqdm(range(n), desc="Computing coverage", unit="trk"):
        by_cat, _ = assign_tags(z[i], cos[i], categories, tag_names, tag_category)
        for tags in by_cat.values():
            for tag in tags:
                counts[tag] += 1

    print(f"\n{'tag':<22} {'category':<16} {'coverage':>9}   top exemplar")
    print("-" * 90)
    for t, tag in enumerate(tag_names):
        best = int(np.argmax(z[:, t]))
        row = con.execute(
            "SELECT title, artist FROM tracks WHERE id = ?", [ids[best]]
        ).fetchone()
        exemplar = f"{row[1]} — {row[0]}" if row else ids[best]
        pct = 100.0 * counts[tag] / n
        flag = "  ⚠" if pct < 0.1 or pct > 60 else ""
        print(f"{tag:<22} {tag_category[t]:<16} {pct:>8.1f}%   {exemplar[:50]}{flag}")
    print("\n⚠ = near-0% or very high coverage; consider rewording those prompts.")


def generate_tags(db_path, vocab_path, output_path, anchors_out, stats_only):
    start = time.time()
    categories, tag_names, tag_category, prompts_per_tag = load_vocabulary(vocab_path)

    con = connect(db_path)
    ids, table_of, matrix = load_clap_vectors(con)
    print(f"Loaded {matrix.shape[0]} v_clap vectors.")

    encoder = ClapTextEncoder()
    anchors = build_anchors(encoder, tag_names, prompts_per_tag, anchors_out)

    print("Scoring corpus against anchors...")
    cos = matrix @ anchors.T  # (N, T)
    # Per-tag z-score across the corpus: the modality-gap calibration.
    mu = cos.mean(axis=0, keepdims=True)
    sigma = cos.std(axis=0, keepdims=True)
    sigma[sigma < 1e-8] = 1e-8
    z = (cos - mu) / sigma

    if stats_only:
        print_stats(z, cos, categories, tag_names, tag_category, ids, con)
        con.close()
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tagged = 0
    with open(output_path, "w") as out_f:
        for i in tqdm(range(len(ids)), desc="Assigning tags", unit="trk"):
            by_category, scores = assign_tags(
                z[i], cos[i], categories, tag_names, tag_category
            )
            flat = [tag for tags in by_category.values() for tag in tags]
            if flat:
                tagged += 1
            out_f.write(json.dumps({
                "id": ids[i],
                "table": table_of[i],
                "tags": flat,
                "tags_by_category": by_category,
                "tag_scores": scores,
            }) + "\n")

    con.close()
    print(f"\n✅ Tagged {tagged}/{len(ids)} tracks in {time.time() - start:.1f}s")
    print(f"   Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zero-shot reverse-CLAP tagging")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--vocabulary", default=DEFAULT_VOCABULARY)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--anchors-out", default=DEFAULT_ANCHORS)
    parser.add_argument("--stats", action="store_true",
                        help="Print per-tag coverage report instead of writing output")
    args = parser.parse_args()
    generate_tags(args.db, args.vocabulary, args.output, args.anchors_out, args.stats)
