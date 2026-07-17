"""
Phase 2.4 — Train/val/test splits with leakage guards and eval-holdout exclusion.

Starts from FMA's official `set.split` (carried on each row of `fma_meta.parquet`) and
hardens it for contrastive training:

1. **Album leakage** — an album must never span two splits (its chunks would leak style
   between train and eval). FMA assigns splits per track, so this is verified, not assumed.
2. **Artist leakage** — the same artist appearing in train and test lets the audio encoder
   memorize an artist's sound rather than learn the caption relation. Any artist spanning
   splits is moved wholesale to its majority split (ties -> the stricter split, test > val >
   train), and the fix is re-verified.
3. **Eval holdout** — the 238 tracks judged in the Phase 0 qrels are reassigned to a
   `holdout` split so they never appear as training or validation pairs. They stay available
   for the Phase 4 retrieval eval, which reads qrels directly.

Output: `data/dataset/splits.parquet` (track_id, split) + `splits.meta.json` provenance.

Usage:
    uv run python -m src.data.splits
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_META = FINETUNE_ROOT / "data" / "dataset" / "fma_meta.parquet"
DEFAULT_QRELS = FINETUNE_ROOT / "data" / "qrels" / "qrels_2026-07-14.parquet"
DEFAULT_OUT_DIR = FINETUNE_ROOT / "data" / "dataset"

# Stricter split wins ties when moving an artist, so eval integrity is preserved.
SPLIT_STRICTNESS = {"test": 3, "validation": 2, "training": 1}
HOLDOUT = "holdout"


def _majority_split(splits: list[str]) -> str:
    counts = Counter(splits)
    top = max(counts.values())
    tied = [s for s, c in counts.items() if c == top]
    return max(tied, key=lambda s: SPLIT_STRICTNESS.get(s, 0))


def build_splits(meta_path: Path, qrels_path: Path, out_dir: Path) -> dict:
    df = pd.read_parquet(meta_path, columns=["track_id", "artist_id", "album_id", "split"])

    # FMA assigns splits per track, so an artist or album can straddle two splits, and a
    # compilation can chain an artist to an album to another artist. Repairing artists then
    # albums independently just ping-pongs the leak back. Instead group tracks into connected
    # components of the artist<->album graph (two tracks linked if they share an artist_id OR
    # an album_id) and give each whole component one split — its majority (stricter on ties).
    album_spanning_before = _spanning_groups(df, "album_id")
    artist_spanning_before = _spanning_groups(df, "artist_id")

    comp = _connected_components(df)
    moved_tracks = 0
    moved_components = 0
    for track_idx in comp.values():
        rows = df.loc[track_idx]
        if rows["split"].nunique() <= 1:
            continue
        target = _majority_split(list(rows["split"]))
        moved = int((rows["split"] != target).sum())
        moved_tracks += moved
        moved_components += 1
        df.loc[track_idx, "split"] = target

    if _spanning_groups(df, "artist_id") or _spanning_groups(df, "album_id"):
        raise RuntimeError("leakage remains after component repair")

    # 3. Eval holdout — pull judged tracks out of train/val/test entirely.
    con = duckdb.connect()
    judged = con.execute(
        f"SELECT DISTINCT track_id FROM read_parquet('{qrels_path}') WHERE source = 'fma'"
    ).fetchall()
    con.close()
    judged_ids = {int(r[0].removeprefix("fma_")) for r in judged}
    holdout_mask = df["track_id"].isin(judged_ids)
    n_holdout_in_corpus = int(holdout_mask.sum())
    df.loc[holdout_mask, "split"] = HOLDOUT

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "splits.parquet"
    df[["track_id", "split"]].to_parquet(out_path, index=False)

    split_counts = df["split"].value_counts().to_dict()
    meta = {
        "created": dt.datetime.now().astimezone().isoformat(),
        "meta_path": str(meta_path),
        "qrels_path": str(qrels_path),
        "out": str(out_path),
        "album_leakage_before": len(album_spanning_before),
        "artist_leakage_before": len(artist_spanning_before),
        "components_moved": moved_components,
        "tracks_moved": moved_tracks,
        "leakage_after": 0,
        "judged_tracks_total": len(judged_ids),
        "judged_tracks_in_corpus_holdout": n_holdout_in_corpus,
        "split_counts": {k: int(v) for k, v in split_counts.items()},
    }
    (out_dir / "splits.meta.json").write_text(json.dumps(meta, indent=2))

    print(f"Wrote splits -> {out_path}")
    print(f"  leakage before: {len(artist_spanning_before)} artists, {len(album_spanning_before)} albums span splits")
    print(f"  repaired {moved_components} components ({moved_tracks} tracks moved); leakage after: 0")
    print(f"  eval holdout: {n_holdout_in_corpus}/{len(judged_ids)} judged tracks pulled to '{HOLDOUT}'")
    print(f"  final splits: {meta['split_counts']}")
    return meta


def _spanning_groups(df: pd.DataFrame, key: str) -> list[int]:
    """Group ids (non-null) whose rows fall in more than one split."""
    sub = df[df[key].notna()]
    nsplits = sub.groupby(key)["split"].nunique()
    return [int(k) for k in nsplits[nsplits > 1].index]


def _connected_components(df: pd.DataFrame) -> dict[int, list]:
    """Union-find over tracks: two tracks are linked if they share an artist_id or album_id.
    Returns {component_root -> [df index labels]}. Null ids link nothing."""
    parent: dict[object, object] = {}

    def find(x: object) -> object:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: object, b: object) -> None:
        parent[find(a)] = find(b)

    # Namespace artist/album ids so they can't collide as raw ints.
    for idx, artist_id, album_id in df[["artist_id", "album_id"]].itertuples():
        find(("track", idx))
        if pd.notna(artist_id):
            union(("track", idx), ("artist", int(artist_id)))
        if pd.notna(album_id):
            union(("track", idx), ("album", int(album_id)))

    components: dict[object, list] = {}
    for idx in df.index:
        root = find(("track", idx))
        components.setdefault(root, []).append(idx)
    return components


def main() -> None:
    ap = argparse.ArgumentParser(description="Build leakage-safe splits with eval holdout.")
    ap.add_argument("--meta", type=Path, default=DEFAULT_META)
    ap.add_argument("--qrels", type=Path, default=DEFAULT_QRELS)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()
    build_splits(args.meta, args.qrels, args.out_dir)


if __name__ == "__main__":
    main()
