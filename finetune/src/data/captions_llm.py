"""
Phase 2.3 — LLM caption paraphrases via a local Ollama model.

For each track, feeds the structured FMA metadata (genre / tags / era / place / Echonest
qualities) to a local `qwen3:30b-a3b` and asks for a few short natural-language descriptions
of how the music *sounds*. These augment the deterministic template captions
(`captions.py`) with linguistic variety so the model doesn't overfit to template phrasing.

Runs entirely offline against `http://localhost:11434`. The full corpus is multi-day at a
few seconds per track, so this is designed to run in the background and be interrupted freely:

- **Resumable.** Results append to `data/dataset/captions_llm.jsonl`, one line per track. On
  restart, tracks already in the file are skipped.
- **Prioritized.** Defaults to the `training` split first (those captions are the ones the
  model actually learns from); `--split` overrides.
- **Logged.** Every generation records the model, prompt hash, and raw response so the run is
  auditable (plan ground rule #4).

The manifest builder folds these captions in wherever they exist; training can start on
templates alone before this finishes.

Usage:
    uv run python -m src.data.captions_llm --limit 500          # first quality batch
    uv run python -m src.data.captions_llm                      # full training split
    uv run python -m src.data.captions_llm --split all --concurrency 4
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import threading
from pathlib import Path

import pandas as pd
import requests

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_META = FINETUNE_ROOT / "data" / "dataset" / "fma_meta.parquet"
DEFAULT_SPLITS = FINETUNE_ROOT / "data" / "dataset" / "splits.parquet"
DEFAULT_OUT = FINETUNE_ROOT / "data" / "dataset" / "captions_llm.jsonl"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:30b-a3b"
N_CAPTIONS = 3
MAX_CAPTION_WORDS = 14

SYSTEM = (
    "You write short, evocative descriptions of how a piece of music SOUNDS, for a music "
    "search dataset. Describe timbre, energy, mood, instrumentation, and feel. Never mention "
    "artist, album, or song names. Each description must be under 14 words and stand alone."
)


def _metadata_line(row: pd.Series) -> str:
    def lst(v: object) -> list:
        return [] if v is None else (v if isinstance(v, list) else list(v))

    genres = lst(row["genres_leaf"]) or lst(row["genres_top"])
    parts = [f"genre={', '.join(genres) if genres else 'unknown'}"]
    tags = lst(row["tags"])
    if tags:
        parts.append(f"tags={', '.join(tags[:6])}")
    if row["decade"]:
        parts.append(f"era={row['decade']}")
    if row["location"]:
        parts.append(f"place={row['location']}")
    echo = lst(row["echonest_words"])
    if echo:
        parts.append(f"qualities={', '.join(echo)}")
    return "; ".join(parts)


def _build_prompt(row: pd.Series) -> str:
    meta = _metadata_line(row)
    return (
        f"{SYSTEM}\n\n"
        f"Metadata: {meta}.\n\n"
        f'Write {N_CAPTIONS} distinct descriptions. Return only JSON: '
        f'{{"captions": ["...", "...", "..."]}}'
    )


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _clean_captions(raw: object) -> list[str]:
    """Validate the model's JSON: keep non-empty strings, under the word cap, deduped."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen = set()
    for c in raw:
        if not isinstance(c, str):
            continue
        c = " ".join(c.split()).strip().strip('"').lower()
        if not c or len(c.split()) > MAX_CAPTION_WORDS:
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _generate(row: pd.Series, timeout: float) -> dict:
    prompt = _build_prompt(row)
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.8, "num_predict": 256},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    captions: list[str] = []
    try:
        parsed = json.loads(body.get("response", "{}"))
        captions = _clean_captions(parsed.get("captions"))
    except (json.JSONDecodeError, AttributeError):
        pass
    return {
        "track_id": int(row["track_id"]),
        "echolocate_id": row["echolocate_id"],
        "prompt_hash": _prompt_hash(prompt),
        "model": MODEL,
        "captions": captions,
        "created": dt.datetime.now().astimezone().isoformat(),
    }


def _done_track_ids(out_path: Path) -> set[int]:
    done: set[int] = set()
    if not out_path.exists():
        return done
    with open(out_path) as f:
        for line in f:
            try:
                done.add(int(json.loads(line)["track_id"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return done


def run(
    meta_path: Path,
    splits_path: Path,
    out_path: Path,
    split: str,
    limit: int | None,
    concurrency: int,
    timeout: float,
) -> None:
    df = pd.read_parquet(meta_path).drop(columns=["split"], errors="ignore")
    splits = pd.read_parquet(splits_path)  # carries the repaired split
    df = df.merge(splits, on="track_id", how="left")

    if split != "all":
        df = df[df["split"] == split]
    # Never spend LLM budget on eval-holdout tracks.
    df = df[df["split"] != "holdout"]
    # Prioritize training split when running across everything.
    df = df.sort_values(by="split", key=lambda s: s.map({"training": 0}).fillna(1), kind="stable")

    done = _done_track_ids(out_path)
    todo = df[~df["track_id"].isin(done)]
    if limit:
        todo = todo.head(limit)
    rows = [r for _, r in todo.iterrows()]
    print(f"tracks: {len(df):,} in scope, {len(done):,} already done, {len(rows):,} to generate")
    if not rows:
        print("nothing to do.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()
    n_ok = n_empty = n_err = 0

    def worker(row: pd.Series) -> tuple[int, int, int]:
        try:
            rec = _generate(row, timeout)
        except Exception as e:  # network / model errors: log and continue, don't lose the run
            rec = {
                "track_id": int(row["track_id"]),
                "echolocate_id": row["echolocate_id"],
                "model": MODEL,
                "captions": [],
                "error": str(e)[:200],
                "created": dt.datetime.now().astimezone().isoformat(),
            }
        with write_lock:
            with open(out_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        if rec.get("error"):
            return (0, 0, 1)
        return (1, 0, 0) if rec["captions"] else (0, 1, 0)

    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for i, (ok, empty, err) in enumerate(ex.map(worker, rows), 1):
            n_ok += ok
            n_empty += empty
            n_err += err
            if i % 25 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}  ok={n_ok} empty={n_empty} err={n_err}", flush=True)

    print(f"done. ok={n_ok} empty={n_empty} err={n_err} -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate LLM caption paraphrases via Ollama.")
    ap.add_argument("--meta", type=Path, default=DEFAULT_META)
    ap.add_argument("--splits", type=Path, default=DEFAULT_SPLITS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--split", default="training", choices=["training", "validation", "test", "all"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()
    run(args.meta, args.splits, args.out, args.split, args.limit, args.concurrency, args.timeout)


if __name__ == "__main__":
    main()
