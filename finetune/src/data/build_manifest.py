"""
Phase 2.5 — Assemble the training manifest and hard-negative map.

Joins the cleaned metadata (`fma_meta.parquet`), repaired splits (`splits.parquet`),
deterministic template captions (`captions.py`), and — where they exist — the LLM paraphrases
(`captions_llm.jsonl`) into the two artifacts Phase 3 trains from:

- **`manifest.parquet`** — one row per (track, 10 s chunk). Each 30 s FMA clip yields three
  native CLAP windows at offsets 0/10/20 s; the offset is recorded so the Phase 3 dataloader
  crops on the fly (matching production's single-window preprocessing per chunk). Every chunk
  carries its track's merged caption list, so a training pair is (chunk audio, sampled caption).
  Eval-holdout tracks are excluded entirely.

- **`hard_negatives.parquet`** — training track_ids grouped by leaf genre, for packing
  within-genre negatives into contrastive batches (distinguishing e.g. free jazz from spiritual
  jazz is where the signal is).

Deterministic: template captions are seeded, LLM captions are read from the frozen cache, and
rows are sorted, so re-running produces byte-identical parquet content.

Usage:
    uv run python -m src.data.build_manifest
    uv run python -m src.data.build_manifest --templates-only   # ignore LLM cache
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from src.data.captions import captions_for_track

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = FINETUNE_ROOT / "data" / "dataset"
DEFAULT_META = DATASET_DIR / "fma_meta.parquet"
DEFAULT_SPLITS = DATASET_DIR / "splits.parquet"
DEFAULT_LLM = DATASET_DIR / "captions_llm.jsonl"

CHUNK_OFFSETS = [0, 10, 20]  # three 10 s CLAP windows per 30 s FMA clip
MAX_CAPTIONS_PER_TRACK = 8
HOLDOUT = "holdout"


def _load_llm_captions(path: Path) -> dict[int, list[str]]:
    """track_id -> LLM captions from the resumable cache (latest record per track wins)."""
    if not path.exists():
        return {}
    by_track: dict[int, list[str]] = {}
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            caps = rec.get("captions") or []
            if caps:
                by_track[int(rec["track_id"])] = caps  # later lines overwrite earlier
    return by_track


def _as_list(v: object) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else list(v)


def _merge_captions(template: list[str], llm: list[str]) -> tuple[list[str], list[str]]:
    """Combine template + LLM captions, deduped, template-first, capped. Returns (captions,
    sources) where sources is a parallel list of 'template'|'llm'."""
    captions: list[str] = []
    sources: list[str] = []
    seen: set[str] = set()
    for cap, src in [(c, "template") for c in template] + [(c, "llm") for c in llm]:
        c = cap.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        captions.append(c)
        sources.append(src)
        if len(captions) >= MAX_CAPTIONS_PER_TRACK:
            break
    return captions, sources


def build_manifest(
    meta_path: Path,
    splits_path: Path,
    llm_path: Path,
    templates_only: bool,
    out_dir: Path,
) -> dict:
    meta = pd.read_parquet(meta_path).drop(columns=["split"], errors="ignore")
    splits = pd.read_parquet(splits_path)
    df = meta.merge(splits, on="track_id", how="left")
    df = df[df["split"] != HOLDOUT].reset_index(drop=True)

    llm_caps = {} if templates_only else _load_llm_captions(llm_path)

    manifest_rows: list[dict] = []
    neg_map: dict[str, list[int]] = {}
    n_no_caption = 0
    n_with_llm = 0

    for _, row in df.iterrows():
        template = captions_for_track(row)
        llm = llm_caps.get(int(row["track_id"]), [])
        captions, sources = _merge_captions(template, llm)
        if not captions:
            n_no_caption += 1
            continue
        if "llm" in sources:
            n_with_llm += 1

        genres_leaf = _as_list(row["genres_leaf"])
        if row["split"] == "training":
            for g in genres_leaf:
                neg_map.setdefault(g, []).append(int(row["track_id"]))

        for offset in CHUNK_OFFSETS:
            manifest_rows.append(
                {
                    "echolocate_id": row["echolocate_id"],
                    "track_id": int(row["track_id"]),
                    "audio_path": row["audio_path"],
                    "split": row["split"],
                    "chunk_offset": offset,
                    "captions": captions,
                    "caption_sources": sources,
                    "genres_leaf": genres_leaf,
                    "genres_top": _as_list(row["genres_top"]),
                }
            )

    manifest = pd.DataFrame(manifest_rows).sort_values(
        ["split", "track_id", "chunk_offset"], kind="stable"
    ).reset_index(drop=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.parquet"
    manifest.to_parquet(manifest_path, index=False)

    neg_rows = [
        {"genre": g, "n_tracks": len(tids), "track_ids": sorted(tids)}
        for g, tids in sorted(neg_map.items())
    ]
    neg_path = out_dir / "hard_negatives.parquet"
    pd.DataFrame(neg_rows).to_parquet(neg_path, index=False)

    n_tracks = manifest["track_id"].nunique()
    pairs = int(manifest["captions"].map(len).sum())  # (chunk, caption) training pairs
    split_tracks = (
        manifest.drop_duplicates("track_id")["split"].value_counts().to_dict()
    )
    meta_out = {
        "created": dt.datetime.now().astimezone().isoformat(),
        "meta_path": str(meta_path),
        "splits_path": str(splits_path),
        "llm_path": None if templates_only else str(llm_path),
        "templates_only": templates_only,
        "manifest_path": str(manifest_path),
        "hard_negatives_path": str(neg_path),
        "n_tracks": int(n_tracks),
        "n_chunks": len(manifest),
        "n_chunk_caption_pairs": pairs,
        "n_tracks_dropped_no_caption": n_no_caption,
        "n_tracks_with_llm_captions": n_with_llm,
        "chunk_offsets": CHUNK_OFFSETS,
        "split_tracks": {k: int(v) for k, v in split_tracks.items()},
        "n_negative_genres": len(neg_rows),
    }
    (out_dir / "manifest.meta.json").write_text(json.dumps(meta_out, indent=2))

    print(f"Wrote manifest -> {manifest_path}")
    print(f"  tracks={n_tracks:,}  chunks={len(manifest):,}  (chunk,caption) pairs={pairs:,}")
    print(f"  dropped (no caption)={n_no_caption:,}  with LLM captions={n_with_llm:,}")
    print(f"  split tracks: {meta_out['split_tracks']}")
    print(f"  hard-negative genres: {len(neg_rows)} -> {neg_path}")
    return meta_out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the training manifest + hard-negative map.")
    ap.add_argument("--meta", type=Path, default=DEFAULT_META)
    ap.add_argument("--splits", type=Path, default=DEFAULT_SPLITS)
    ap.add_argument("--llm", type=Path, default=DEFAULT_LLM)
    ap.add_argument("--templates-only", action="store_true", help="Ignore the LLM caption cache.")
    ap.add_argument("--out-dir", type=Path, default=DATASET_DIR)
    args = ap.parse_args()
    build_manifest(args.meta, args.splits, args.llm, args.templates_only, args.out_dir)


if __name__ == "__main__":
    main()
