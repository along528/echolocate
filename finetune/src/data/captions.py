"""
Phase 2.2 — Deterministic template captions from the cleaned FMA metadata.

Turns each track's structured fields (`fma_meta.parquet`) into 1–5 short natural-language
captions describing how the music *sounds* — genre, descriptive tags, Echonest-derived
adjectives, era, and place. These are the audio-side text targets for contrastive training,
and the seed material the LLM paraphrase pass (`captions_llm.py`) rewrites.

Design choices:
- **No artist / album / track names.** Captions describe sound, not identity; names would let
  the audio encoder memorize a track instead of learning the caption relation.
- **Genre is required.** A track with no genre and no tags produces no caption and is dropped.
- **Seeded per track** (`seed = track_id`), so the full run is byte-for-byte reproducible.
- Echonest words split into adjectives (prepended: "acoustic instrumental folk") and phrases
  (appended: "folk, slow tempo") so captions stay grammatical.

This module is a library (imported by `build_manifest.py`); running it directly prints a
sample for eyeballing.

Usage:
    uv run python -m src.data.captions --sample 20
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_META = FINETUNE_ROOT / "data" / "dataset" / "fma_meta.parquet"

MAX_CAPTIONS = 5
MAX_CAPTION_WORDS = 20  # defensive: no template caption should blow up from a noisy field
# Echonest words that read as adjectives (prepend before the genre) vs. trailing phrases.
ECHO_ADJ = {"high-energy", "mellow", "acoustic", "instrumental", "danceable", "upbeat", "melancholic"}
ECHO_PHRASE = {"live recording", "spoken word", "fast tempo", "slow tempo"}


def _as_list(v: object) -> list:
    """Parquet list columns deserialize to numpy arrays; normalize to a plain python list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return list(v)  # numpy array or tuple


def _primary_genres(row: pd.Series) -> list[str]:
    """Lowercased genre names, leaf preferred over top-level, capped for readable captions."""
    leaf = [g.lower() for g in _as_list(row["genres_leaf"])]
    top = [g.lower() for g in _as_list(row["genres_top"])]
    genres = leaf or top
    return genres[:3]


def caption_candidates(row: pd.Series) -> list[str]:
    """The full deduped pool of template captions for a track (order-stable)."""
    genres = _primary_genres(row)
    tags = [t for t in _as_list(row["tags"]) if len(t) <= 30][:4]
    echo = _as_list(row["echonest_words"])
    adjs = [w for w in echo if w in ECHO_ADJ]
    phrases = [w for w in echo if w in ECHO_PHRASE]
    decade = row["decade"]
    location = row["location"]

    if not genres and not tags:
        return []

    genre = genres[0] if genres else (tags[0] if tags else None)
    two_genres = " and ".join(genres[:2]) if len(genres) >= 2 else genre

    cands: list[str] = []

    def add(s: str | None) -> None:
        if s:
            s = " ".join(s.split()).strip().lower()
            if s and s not in cands:
                cands.append(s)

    if genre:
        add(genre)
        add(two_genres)
        if adjs:
            add(f"{' '.join(adjs[:2])} {genre}")
        if phrases:
            add(f"{genre}, {phrases[0]}")
        if tags:
            add(f"{genre} with {' and '.join(tags[:2])}")
        if adjs and tags:
            add(f"{adjs[0]} {genre} with {tags[0]}")
        if location:
            add(f"{genre} from {location.lower()}")
        if decade:
            add(f"{decade} {two_genres}")
        if adjs and decade:
            add(f"{adjs[0]} {two_genres}, {decade}")
    # Tag-forward variant (works even when genre came from a tag).
    if tags:
        add(f"{', '.join(tags[:2])}" + (f" {genre}" if genre and genre not in tags[:2] else ""))

    return [c for c in cands if c and len(c.split()) <= MAX_CAPTION_WORDS]


def captions_for_track(row: pd.Series, n: int = MAX_CAPTIONS) -> list[str]:
    """Up to `n` captions for a track, sampled deterministically from the candidate pool.

    The genre-only caption is always kept (anchors the pool); the rest are a seeded random
    sample so different tracks surface different template shapes without any global state.
    """
    cands = caption_candidates(row)
    if not cands:
        return []
    if len(cands) <= n:
        return cands
    rng = random.Random(int(row["track_id"]))
    head, tail = cands[0], cands[1:]
    rng.shuffle(tail)
    return [head] + tail[: n - 1]


def main() -> None:
    ap = argparse.ArgumentParser(description="Preview template captions.")
    ap.add_argument("--meta", type=Path, default=DEFAULT_META)
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()

    df = pd.read_parquet(args.meta)
    rng = random.Random(0)
    idx = rng.sample(range(len(df)), min(args.sample, len(df)))
    n_empty = 0
    for i in idx:
        row = df.iloc[i]
        caps = captions_for_track(row)
        if not caps:
            n_empty += 1
        print(f"[{row.echolocate_id}] genres={list(row.genres_leaf)[:3]} tags={list(row.tags)[:4]}")
        for c in caps:
            print(f"    - {c}")
    # Corpus-wide vacuous rate.
    empty_total = sum(1 for _, r in df.iterrows() if not caption_candidates(r))
    print(f"\nsampled empty: {n_empty}/{len(idx)}   corpus vacuous: {empty_total}/{len(df)} "
          f"({empty_total / len(df):.1%})")


if __name__ == "__main__":
    main()
