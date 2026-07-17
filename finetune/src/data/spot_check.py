"""
Phase 2 exit checkpoint — listen to random (caption, audio) pairs.

Samples N tracks from the manifest, prints their captions, and plays the clip so a human can
judge whether the captions actually match how the track sounds. This is the ⛔ manual gate
before Phase 3 training.

`afplay` cannot seek, so it plays the full 30 s FMA clip; the chunk offset is printed for
reference (captions describe the whole track, not a single window). Press Enter to advance,
`s`+Enter to skip playback, `q`+Enter to quit.

Usage:
    uv run python -m src.data.spot_check --n 30
    uv run python -m src.data.spot_check --n 30 --split training --seed 1
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pandas as pd

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = FINETUNE_ROOT / "data" / "dataset" / "manifest.parquet"


def spot_check(manifest_path: Path, n: int, split: str, seed: int) -> None:
    m = pd.read_parquet(manifest_path)
    tracks = m.drop_duplicates("track_id")
    if split != "all":
        tracks = tracks[tracks["split"] == split]
    if tracks.empty:
        print(f"no tracks for split={split}")
        return
    sample = tracks.sample(n=min(n, len(tracks)), random_state=seed)

    print(f"Spot-checking {len(sample)} tracks (split={split}, seed={seed}).")
    print("Enter=next, s=skip audio, q=quit.\n")
    for i, (_, r) in enumerate(sample.iterrows(), 1):
        print(f"[{i}/{len(sample)}] {r['echolocate_id']}  split={r['split']}  "
              f"genres={list(r['genres_leaf'])[:3]}")
        for cap, src in zip(r["captions"], r["caption_sources"]):
            print(f"    ({src[0]}) {cap}")
        path = Path(r["audio_path"])
        if not path.exists():
            print(f"    !! audio missing: {path}")
            continue
        cmd = input("    > play? [Enter/s/q] ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            continue
        try:
            subprocess.run(["afplay", str(path)], check=False)
        except KeyboardInterrupt:
            print("    (stopped)")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Listen to random caption/audio pairs.")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--split", default="training",
                    choices=["training", "validation", "test", "all"])
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    spot_check(args.manifest, args.n, args.split, args.seed)


if __name__ == "__main__":
    main()
