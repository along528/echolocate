"""
Phase 1 — Local CLAP audio embedding, parity-matched to production.

Direct port of `embeddings/generate_clap.py` (audio loading + batched inference), reusing the
pinned model in `src.clap_common`. Produces the same L2-normalized 512-d `v_clap` vectors as
production, but with a selectable device (MPS for throughput; CPU is what production used).

The only behavioral differences from the production script are intentional and inert:
  - device is selectable (production forced CPU);
  - the HF revision is pinned (production floated unpinned — see MODEL_CARD.md).

Usage (library relative_path is rooted at the crate/ tree on the external drive):
    uv run python -m src.embed --device mps "crate/Apple/Artist/Album/Track.mp3" ...
"""

from __future__ import annotations

import argparse

import librosa
import numpy as np

from src.clap_common import DURATION, OFFSET, SAMPLE_RATE, encode_audio, pick_device

# Minimum usable clip length after the offset — matches generate_clap.py (1 second).
MIN_SAMPLES = SAMPLE_RATE
DEFAULT_BATCH_SIZE = 4


def load_audio_for_clap(file_path: str, offset: float = OFFSET) -> np.ndarray | None:
    """
    Load a single 10 s @ 48 kHz mono window — identical to
    embeddings/generate_clap.py:load_audio_for_clap. Returns None if too short after offset.

    `offset` defaults to the production library value (30 s). Note the FMA corpus was embedded
    from the 10-20 s window (offset=10) of its 30 s clips, so callers embedding FMA must pass
    offset=10 to reproduce the stored vectors (see src/parity.py).
    """
    audio, _ = librosa.load(
        file_path,
        sr=SAMPLE_RATE,
        duration=DURATION,
        offset=offset,
    )
    if len(audio) < MIN_SAMPLES:
        return None
    return audio


def embed_files(
    file_paths: list[str],
    device_str: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    offset: float = OFFSET,
) -> dict[str, np.ndarray]:
    """
    Embed audio files -> {path: 512-d L2-normalized vector}. Files too short after the offset
    are skipped (absent from the returned dict), matching production behavior.
    """
    device = pick_device(device_str)
    loaded: list[tuple[str, np.ndarray]] = []
    for p in file_paths:
        try:
            audio = load_audio_for_clap(p, offset=offset)
        except Exception as e:  # noqa: BLE001 — mirror generate_clap.py's per-file skip
            print(f"  skip (load error): {p}: {e}")
            continue
        if audio is None:
            print(f"  skip (too short after {OFFSET}s offset): {p}")
            continue
        loaded.append((p, audio))

    out: dict[str, np.ndarray] = {}
    for i in range(0, len(loaded), batch_size):
        batch = loaded[i : i + batch_size]
        vecs = encode_audio([a for _p, a in batch], device)
        for (p, _a), v in zip(batch, vecs):
            out[p] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Embed audio files with the pinned CLAP model.")
    ap.add_argument("paths", nargs="+", help="Audio file paths")
    ap.add_argument("--device", default=None, help="mps | cpu (default: auto)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--offset", type=float, default=OFFSET, help="window offset s (library=30, FMA=10)")
    args = ap.parse_args()
    vecs = embed_files(args.paths, args.device, args.batch_size, offset=args.offset)
    for p, v in vecs.items():
        print(f"{p}\t||v||={np.linalg.norm(v):.4f}\tdim={v.shape[0]}")


if __name__ == "__main__":
    main()
