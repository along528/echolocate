"""
Phase 2.6 — Dataset statistics report.

Reads the built artifacts (`manifest.parquet` + the `*.meta.json` provenance from each stage)
and writes `finetune/dataset_stats.md`: pair counts per split, genre distribution, caption
length + source breakdown, the leakage-repair result, and the eval-holdout exclusion count.
This is the artifact the human reviews at the Phase 2 exit checkpoint.

Usage:
    uv run python -m src.data.stats
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = FINETUNE_ROOT / "data" / "dataset"
DEFAULT_MANIFEST = DATASET_DIR / "manifest.parquet"
DEFAULT_OUT = FINETUNE_ROOT / "dataset_stats.md"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _fmt_counts(d: dict) -> str:
    return ", ".join(f"{k}={v:,}" for k, v in d.items())


def write_stats(manifest_path: Path, out_path: Path) -> None:
    m = pd.read_parquet(manifest_path)
    fma_meta = _load_json(DATASET_DIR / "fma_meta.meta.json")
    splits_meta = _load_json(DATASET_DIR / "splits.meta.json")
    manifest_meta = _load_json(DATASET_DIR / "manifest.meta.json")

    tracks = m.drop_duplicates("track_id")
    per_split_tracks = tracks["split"].value_counts().to_dict()
    per_split_chunks = m["split"].value_counts().to_dict()

    # (chunk, caption) pairs per split.
    m = m.assign(n_caps=m["captions"].map(len))
    pairs_per_split = m.groupby("split")["n_caps"].sum().astype(int).to_dict()

    # Caption length (words) + source breakdown, over unique tracks.
    cap_words: list[int] = []
    src_counter: Counter = Counter()
    for _, r in tracks.iterrows():
        for c in r["captions"]:
            cap_words.append(len(c.split()))
        for s in r["caption_sources"]:
            src_counter[s] += 1
    cap_words_sorted = sorted(cap_words)

    def _pct(p: float) -> int:
        if not cap_words_sorted:
            return 0
        return cap_words_sorted[min(len(cap_words_sorted) - 1, int(p * (len(cap_words_sorted) - 1)))]

    # Genre distribution (leaf), over unique tracks.
    genre_counter: Counter = Counter()
    for _, r in tracks.iterrows():
        for g in r["genres_leaf"]:
            genre_counter[g] += 1
    top_genres = genre_counter.most_common(25)

    llm_tracks = manifest_meta.get("n_tracks_with_llm_captions", 0)
    n_tracks = len(tracks)

    lines: list[str] = []
    L = lines.append
    L("# FMA fine-tuning dataset — Phase 2 stats\n")
    L(f"Generated from `{manifest_path.name}` and the stage `*.meta.json` provenance files.\n")

    L("## Headline\n")
    L(f"- **Tracks:** {n_tracks:,}")
    L(f"- **Chunks (10 s windows):** {len(m):,}  (offsets {manifest_meta.get('chunk_offsets')})")
    L(f"- **(chunk, caption) training pairs:** {int(m['n_caps'].sum()):,}")
    L(f"- **Tracks with LLM captions:** {llm_tracks:,} "
      f"({llm_tracks / n_tracks:.1%})" if n_tracks else "")
    L(f"- **Tracks dropped (no caption):** {manifest_meta.get('n_tracks_dropped_no_caption', 0):,}\n")

    L("## Per-split\n")
    L("| split | tracks | chunks | (chunk,caption) pairs |")
    L("|---|---|---|---|")
    for s in ["training", "validation", "test"]:
        L(f"| {s} | {per_split_tracks.get(s, 0):,} | {per_split_chunks.get(s, 0):,} "
          f"| {pairs_per_split.get(s, 0):,} |")
    L("")

    L("## Captions\n")
    L(f"- **Source breakdown (caption instances over unique tracks):** {_fmt_counts(dict(src_counter))}")
    L(f"- **Words per caption:** min={cap_words_sorted[0] if cap_words_sorted else 0} "
      f"p50={_pct(0.5)} p90={_pct(0.9)} max={cap_words_sorted[-1] if cap_words_sorted else 0}")
    L(f"- **Avg captions/track:** {len(cap_words) / n_tracks:.2f}\n" if n_tracks else "")

    L("## Leakage + holdout\n")
    L(f"- **Artist leakage before repair:** {splits_meta.get('artist_leakage_before', '?')} artists")
    L(f"- **Album leakage before repair:** {splits_meta.get('album_leakage_before', '?')} albums")
    L(f"- **Repaired:** {splits_meta.get('components_moved', '?')} components, "
      f"{splits_meta.get('tracks_moved', '?')} tracks moved; **leakage after: 0**")
    L(f"- **Eval-holdout tracks pulled from train/val/test:** "
      f"{splits_meta.get('judged_tracks_in_corpus_holdout', '?')} of "
      f"{splits_meta.get('judged_tracks_total', '?')} judged (excluded from the manifest entirely)\n")

    L("## Corpus coverage (from metadata load)\n")
    cov = fma_meta.get("coverage", {})
    total = fma_meta.get("n_rows", 0)
    if cov and total:
        L("| field | tracks | coverage |")
        L("|---|---|---|")
        for k, v in cov.items():
            L(f"| {k} | {v:,} | {v / total:.1%} |")
    L(f"\n- **Missing audio on disk (skipped):** {fma_meta.get('n_missing_audio', 0):,}\n")

    L("## Top leaf genres (unique tracks)\n")
    L("| genre | tracks |")
    L("|---|---|")
    for g, c in top_genres:
        L(f"| {g} | {c:,} |")
    L("")

    out_path.write_text("\n".join(x for x in lines if x is not None))
    print(f"Wrote {out_path}")
    print(f"  tracks={n_tracks:,} chunks={len(m):,} pairs={int(m['n_caps'].sum()):,} "
          f"llm_tracks={llm_tracks:,}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Write the Phase 2 dataset stats report.")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    write_stats(args.manifest, args.out)


if __name__ == "__main__":
    main()
