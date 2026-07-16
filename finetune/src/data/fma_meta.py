"""
Phase 2.1 — Load and clean FMA metadata into one per-track table.

Joins the FMA metadata dump (`tracks.csv` + `genres.csv` + `echonest.csv`) against the
frozen production snapshot (`data/snapshot/tracks_clap_*.parquet`), keeping only FMA tracks
that (a) prod actually serves with a non-zero `v_clap` and (b) have an audio file on disk.
The result is the structured input for caption templating (`captions.py`) and the LLM
paraphrase job (`captions_llm.py`).

Every field is decoded to human-readable words: `genres_all` ids -> genre names (leaf +
top-level via the `genres.csv` hierarchy), tags cleaned/deduped, dates -> decade, and the
Echonest audio features -> descriptive buckets ("high-energy", "acoustic", ...).

`tracks.csv` and `echonest.csv` carry a multi-row column header (level0 = album/artist/
track/set group, level1 = field). pandas parses that cleanly with `header=[0,1]`; duckdb
does not, which is why pandas is a Phase 2 dependency.

Output: `data/dataset/fma_meta.parquet` (one row per kept track).

Usage:
    uv run python -m src.data.fma_meta
    uv run python -m src.data.fma_meta --limit 2000   # quick smoke subset
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
from pathlib import Path

import duckdb
import pandas as pd

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_META_DIR = Path("/Volumes/Samsung/Projects/echolocate/data/fma/fma_metadata")
DEFAULT_AUDIO_ROOT = Path("/Volumes/Samsung/fma/fma_large")
DEFAULT_SNAPSHOT = FINETUNE_ROOT / "data" / "snapshot" / "tracks_clap_2026-07-14.parquet"
DEFAULT_OUT_DIR = FINETUNE_ROOT / "data" / "dataset"

# Echonest audio features are in [0, 1] (except tempo, in BPM). Each bucket maps a feature
# crossing a threshold to a descriptive word that can seed a caption. Thresholds are
# deliberately conservative so a word only fires when the signal is strong.
ECHONEST_BUCKETS = [
    ("energy", "high", 0.70, "high-energy"),
    ("energy", "low", 0.30, "mellow"),
    ("acousticness", "high", 0.60, "acoustic"),
    ("instrumentalness", "high", 0.60, "instrumental"),
    ("danceability", "high", 0.65, "danceable"),
    ("valence", "high", 0.65, "upbeat"),
    ("valence", "low", 0.25, "melancholic"),
    ("liveness", "high", 0.70, "live recording"),
    ("speechiness", "high", 0.55, "spoken word"),
]


def audio_path(track_id: int, audio_root: Path) -> Path:
    """FMA layout: fma_large/<first 3 digits of 6-digit id>/<6-digit id>.mp3."""
    padded = f"{track_id:06d}"
    return audio_root / padded[:3] / f"{padded}.mp3"


def _parse_id_list(raw: object) -> list[int]:
    """`genres_all` is a stringified python list like '[21, 45]' (may be NaN/'[]')."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    s = str(raw).strip()
    if not s or s == "[]":
        return []
    try:
        val = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return []
    return [int(x) for x in val] if isinstance(val, (list, tuple)) else []


def _parse_tags(raw: object) -> list[str]:
    """Tags are a stringified python list of strings like "['awol', 'nj rap']"."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    s = str(raw).strip()
    if not s or s == "[]":
        return []
    try:
        val = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(val, (list, tuple)):
        return []
    return [str(x).strip() for x in val if str(x).strip()]


def _decade(*date_strs: object) -> str | None:
    """First parseable 4-digit year among the given date strings -> 'YYYYs' decade."""
    for raw in date_strs:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        s = str(raw)
        for i in range(len(s) - 3):
            chunk = s[i : i + 4]
            if chunk.isdigit():
                year = int(chunk)
                if 1900 <= year <= dt.date.today().year:
                    return f"{(year // 10) * 10}s"
    return None


def _clean_location(raw: object) -> str | None:
    """FMA's artist_location is free text — usually 'City, ST' / 'City Country', but sometimes
    a whole venue bio paragraph. Keep the text before the first sentence break and drop
    anything still too long to be a place name."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().strip(",")
    s = s.split(".")[0].strip()  # cut trailing prose ("... slack space is a volunteer...")
    if not s or len(s) > 40:
        return None
    return s


def load_genre_maps(meta_dir: Path) -> tuple[dict[int, str], dict[int, int]]:
    """genre_id -> title, and genre_id -> top_level genre_id, from genres.csv."""
    g = pd.read_csv(meta_dir / "genres.csv")
    id_to_title = dict(zip(g["genre_id"].astype(int), g["title"].astype(str)))
    id_to_top = dict(zip(g["genre_id"].astype(int), g["top_level"].astype(int)))
    return id_to_title, id_to_top


def load_echonest(meta_dir: Path) -> dict[int, list[str]]:
    """track_id -> descriptive words from the Echonest audio features (subset with coverage)."""
    e = pd.read_csv(meta_dir / "echonest.csv", index_col=0, header=[0, 1, 2], low_memory=False)
    feats = e["echonest"]["audio_features"]
    words: dict[int, list[str]] = {}
    for tid, row in feats.iterrows():
        w = _echonest_words_for_row(row)
        if w:
            words[int(tid)] = w
    return words


def _echonest_words_for_row(row: pd.Series) -> list[str]:
    w: list[str] = []
    for feature, side, thresh, label in ECHONEST_BUCKETS:
        if feature not in row or pd.isna(row[feature]):
            continue
        val = float(row[feature])
        hit = val >= thresh if side == "high" else val <= thresh
        if hit:
            w.append(label)
    # Tempo is BPM, not [0,1]; bucket separately if present.
    if "tempo" in row and not pd.isna(row["tempo"]):
        bpm = float(row["tempo"])
        if bpm >= 150:
            w.append("fast tempo")
        elif 0 < bpm <= 80:
            w.append("slow tempo")
    return w


def build_fma_meta(
    meta_dir: Path,
    audio_root: Path,
    snapshot: Path,
    out_dir: Path,
    limit: int | None = None,
) -> dict:
    if not snapshot.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot}")

    # Which FMA tracks does prod actually serve with a usable CLAP vector?
    con = duckdb.connect()
    served = con.execute(
        f"""
        SELECT id FROM read_parquet('{snapshot}')
        WHERE source = 'fma'
          AND list_sum(list_transform(v_clap, x -> x * x)) >= 1e-6
        """
    ).fetchall()
    con.close()
    served_ids = {int(row[0].removeprefix("fma_")) for row in served}
    print(f"snapshot: {len(served_ids):,} FMA tracks with non-zero v_clap")

    print("reading tracks.csv (multi-header)...")
    t = pd.read_csv(meta_dir / "tracks.csv", index_col=0, header=[0, 1], low_memory=False)

    id_to_title, id_to_top = load_genre_maps(meta_dir)
    print(f"genres.csv: {len(id_to_title)} genres")
    echonest_words = load_echonest(meta_dir)
    print(f"echonest.csv: {len(echonest_words):,} tracks with audio features")

    rows: list[dict] = []
    missing_audio = 0
    for track_id, r in t.iterrows():
        tid = int(track_id)
        if tid not in served_ids:
            continue
        path = audio_path(tid, audio_root)
        if not path.exists():
            missing_audio += 1
            continue

        genre_ids = _parse_id_list(r[("track", "genres_all")])
        genres_leaf = sorted({id_to_title[g] for g in genre_ids if g in id_to_title})
        top_ids = {id_to_top[g] for g in genre_ids if g in id_to_top}
        genres_top = sorted({id_to_title[g] for g in top_ids if g in id_to_title})
        genre_top_single = r[("track", "genre_top")]
        if isinstance(genre_top_single, str) and genre_top_single.strip():
            genres_top = sorted(set(genres_top) | {genre_top_single.strip()})

        artist_name = _str_or_none(r[("artist", "name")])
        album_title = _str_or_none(r[("album", "title")])
        track_title = _str_or_none(r[("track", "title")])

        # Merge track/artist/album tags; drop tags that just echo the names or a genre.
        raw_tags = (
            _parse_tags(r[("track", "tags")])
            + _parse_tags(r[("artist", "tags")])
            + _parse_tags(r[("album", "tags")])
        )
        name_blob = " ".join(
            x.lower() for x in (artist_name, album_title, track_title) if x
        )
        genre_blob = " ".join(x.lower() for x in genres_leaf + genres_top)
        tags: list[str] = []
        seen = set()
        for tag in raw_tags:
            tl = tag.lower()
            if tl in seen or tl in name_blob or tl in genre_blob or len(tl) < 2:
                continue
            seen.add(tl)
            tags.append(tl)

        rows.append(
            {
                "track_id": tid,
                "echolocate_id": f"fma_{tid}",
                "audio_path": str(path),
                "split": _str_or_none(r[("set", "split")]) or "training",
                "artist_id": _int_or_none(r[("artist", "id")]),
                "album_id": _int_or_none(r[("album", "id")]),
                "artist_name": artist_name,
                "album_title": album_title,
                "track_title": track_title,
                "genres_leaf": genres_leaf,
                "genres_top": genres_top,
                "tags": tags,
                "decade": _decade(
                    r[("album", "date_released")], r[("track", "date_recorded")]
                ),
                "location": _clean_location(r[("artist", "location")]),
                "language": _str_or_none(r[("track", "language_code")]),
                "echonest_words": echonest_words.get(tid, []),
            }
        )
        if limit and len(rows) >= limit:
            break

    df = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "fma_meta.parquet"
    df.to_parquet(out_path, index=False)

    # Coverage summary.
    def _nonempty(col: str) -> int:
        return int(df[col].map(lambda v: bool(v)).sum())

    meta = {
        "created": dt.datetime.now().astimezone().isoformat(),
        "snapshot": str(snapshot),
        "meta_dir": str(meta_dir),
        "audio_root": str(audio_root),
        "out": str(out_path),
        "n_served_nonzero_clap": len(served_ids),
        "n_rows": len(df),
        "n_missing_audio": missing_audio,
        "coverage": {
            "genres_leaf": _nonempty("genres_leaf"),
            "genres_top": _nonempty("genres_top"),
            "tags": _nonempty("tags"),
            "decade": int(df["decade"].notna().sum()),
            "location": int(df["location"].notna().sum()),
            "language": int(df["language"].notna().sum()),
            "echonest_words": _nonempty("echonest_words"),
        },
        "split_counts": df["split"].value_counts().to_dict(),
    }
    (out_dir / "fma_meta.meta.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"\nWrote {len(df):,} tracks -> {out_path}")
    print(f"  missing audio on disk (skipped): {missing_audio:,}")
    print("  coverage:", json.dumps(meta["coverage"]))
    print("  splits:", meta["split_counts"])
    return meta


def _str_or_none(v: object) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def _int_or_none(v: object) -> int | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the cleaned FMA per-track metadata table.")
    ap.add_argument("--meta-dir", type=Path, default=DEFAULT_META_DIR)
    ap.add_argument("--audio-root", type=Path, default=DEFAULT_AUDIO_ROOT)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--limit", type=int, default=None, help="Cap rows for a quick smoke run.")
    args = ap.parse_args()
    build_fma_meta(args.meta_dir, args.audio_root, args.snapshot, args.out_dir, args.limit)


if __name__ == "__main__":
    main()
