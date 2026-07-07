"""
Build a *small* sample index DuckDB for local / remote development.

`generate_index_db.py` produces the real ~1.4GB baked index from the full
23GB `cloudcrate.duckdb`. Neither of those is available in a dev sandbox (they
are gitignored and huge), so the vector-rs service cannot be run or queried
there. This script produces a tiny, committable stand-in with the *exact* same
schema (`tracks_library` + `tracks_fma` + the `tracks` union view, columns
mirroring generate_index_db.COLUMNS, HNSW indexes when VSS is available) that
the service can build against, run, and answer real queries from — fully
offline, no cloud credentials, no full DB.

Two modes:

  --synthetic (default when no --source)
      Generate N placeholder tracks per table with random unit embeddings and
      plausible metadata. Vectors are meaningless but structurally valid, so
      every endpoint returns real JSON. This is what is committed to
      `vector-rs/testdata/sample_index.duckdb`.

  --source PATH
      Subset a real full DB: copy the first N rows of each table (same column
      set as the baked index). Use this when a maintainer has cloudcrate.duckdb
      locally and wants a realistic sample.

HNSW indexes are built when the DuckDB `vss` extension can be installed;
otherwise the script warns and skips them. Correctness does not depend on the
index — the service's queries `ORDER BY array_cosine_distance(...) LIMIT k`,
which sequentially scans when no index is present (fine at sample size). The
`vss` extension must still be available at *service runtime* regardless (see
vector-rs/scripts/setup-dev.sh); the index is only a query-speed concern.

Usage:
    python generate_sample_index.py [--output PATH] [--synthetic]
                                    [--source FULL_DB] [--n N] [--seed SEED]
"""

import argparse
import hashlib
import os
import sys
import time

import duckdb
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = os.path.join(
    BASE_DIR, "../vector-rs/testdata/sample_index.duckdb"
)

TABLES = ["tracks_library", "tracks_fma"]

# Mirror generate_index_db.COLUMNS (the baked-index schema the service expects).
COLUMNS = [
    "id", "title", "artist", "album", "relative_path",
    "track_url", "album_url", "artist_url",
    "v_mid", "v_clap", "duration", "x", "y",
]

MID_DIM = 768
CLAP_DIM = 512

# Placeholder metadata pools for synthetic mode.
ARTISTS = [
    "Azure Drift", "Neon Vellum", "Coral Static", "Hollow Tide", "Glass Meridian",
    "Umbra Fields", "Paper Satellites", "Slow Ember", "Cobalt Hours", "Violet Rift",
]
ALBUMS = [
    "First Light", "Undertow", "Halcyon", "Machine Pastoral", "Nightglass",
    "Salt & Signal", "Low Orbit", "Analog Bloom",
]
TITLES = [
    "Driftwood", "Copper Wire", "Signal Lost", "Tidepool", "Afterglow",
    "Sonar", "Ghost Notes", "Slow Current", "Blue Hour", "Reverb Garden",
    "Static Bloom", "Deep Field", "Half Light", "Echo Chamber", "Pale Motion",
]


def _rng(seed):
    return np.random.default_rng(seed)


def _unit_rows(n, dim, rng):
    """n random unit vectors of length dim (float32), as python lists."""
    m = rng.standard_normal((n, dim)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    return m


def _pca_xy(mid_matrix):
    """First 2 PCA components of v_mid, minmax-normalized to [0,1].

    Matches the shipping projection (generate_projection.py: --method pca
    --vector mid --normalize minmax) so map endpoints behave realistically.
    """
    centered = mid_matrix - mid_matrix.mean(axis=0, keepdims=True)
    cov = (centered.T @ centered) / max(1, centered.shape[0] - 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    top2 = eigvecs[:, np.argsort(eigvals)[::-1][:2]]
    scores = centered @ top2

    def minmax(v):
        lo, hi = float(v.min()), float(v.max())
        return np.full_like(v, 0.5) if hi - lo < 1e-12 else (v - lo) / (hi - lo)

    return minmax(scores[:, 0]), minmax(scores[:, 1])


def _try_load_vss(con):
    """Load the vss extension; return True on success, False (with warning) else."""
    try:
        con.execute("INSTALL vss; LOAD vss;")
        con.execute("SET hnsw_enable_experimental_persistence = true;")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  vss unavailable ({type(e).__name__}); skipping HNSW indexes.")
        print("     Queries still work via sequential scan at sample size.")
        return False


def _make_synthetic_table(con, table, n, rng, has_vss):
    short = table.replace("tracks_", "")
    mid = _unit_rows(n, MID_DIM, rng)
    clap = _unit_rows(n, CLAP_DIM, rng)
    x_raw, y_raw = _pca_xy(mid)

    con.execute(
        f"CREATE TABLE {table} ("
        "id VARCHAR, title VARCHAR, artist VARCHAR, album VARCHAR, "
        "relative_path VARCHAR, track_url VARCHAR, album_url VARCHAR, "
        "artist_url VARCHAR, "
        f"v_mid FLOAT[{MID_DIM}], v_clap FLOAT[{CLAP_DIM}], "
        "duration DOUBLE, x DOUBLE, y DOUBLE);"
    )

    con.begin()
    for i in range(n):
        artist = ARTISTS[rng.integers(len(ARTISTS))]
        album = ALBUMS[rng.integers(len(ALBUMS))]
        title = f"{TITLES[rng.integers(len(TITLES))]} {i + 1}"
        tid = hashlib.md5(
            f"{artist}|{album}|{title}|{short}".encode()
        ).hexdigest()
        rel = f"{short}/{artist}/{album}/{title}.mp3"
        con.execute(
            f"INSERT INTO {table} VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                tid, title, artist, album, rel,
                f"https://example.test/track/{tid}",
                f"https://example.test/album/{album}",
                f"https://example.test/artist/{artist}",
                mid[i].tolist(), clap[i].tolist(),
                float(round(90 + rng.random() * 210, 1)),
                float(x_raw[i]), float(y_raw[i]),
            ],
        )
    con.commit()
    con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (id);")
    print(f"  {table}: {n} synthetic rows.")


def _copy_from_source(con, source_path, n):
    con.execute(f"ATTACH '{source_path}' AS src (READ_ONLY);")
    col_list = ", ".join(COLUMNS)
    for table in TABLES:
        con.execute(
            f"CREATE TABLE {table} AS "
            f"SELECT {col_list} FROM src.{table} LIMIT {n};"
        )
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (id);")
        print(f"  {table}: {count} rows copied from source.")
    con.execute("DETACH src;")


def _finalize(con, has_vss):
    if has_vss:
        print("Building HNSW indexes...")
        for table in TABLES:
            short = table.replace("tracks_", "")
            for col in ("mid", "clap"):
                con.execute(
                    f"CREATE INDEX idx_{short}_{col} ON {table} "
                    f"USING HNSW (v_{col}) WITH (metric = 'cosine');"
                )

    print("Creating union view 'tracks'...")
    con.execute(
        "CREATE VIEW tracks AS "
        "  SELECT *, 'library' AS source FROM tracks_library "
        "  UNION ALL "
        "  SELECT *, 'fma' AS source FROM tracks_fma;"
    )

    print("Creating text indexes...")
    for table in TABLES:
        for col in ("title", "artist", "album"):
            con.execute(f"CREATE INDEX idx_{table}_{col} ON {table} ({col});")

    con.execute("CHECKPOINT;")


def build_sample(output_path, source_path, n, seed):
    if os.path.exists(output_path):
        os.remove(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    start = time.time()
    con = duckdb.connect(output_path)
    has_vss = _try_load_vss(con)

    if source_path:
        if not os.path.exists(source_path):
            print(f"Source database not found: {source_path}")
            sys.exit(1)
        print(f"Subsetting {n} rows/table from {source_path}...")
        _copy_from_source(con, source_path, n)
    else:
        print(f"Generating {n} synthetic rows/table (seed={seed})...")
        rng = _rng(seed)
        for table in TABLES:
            _make_synthetic_table(con, table, n, rng, has_vss)

    _finalize(con, has_vss)

    total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    con.close()
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(
        f"\nCreated {output_path} ({size_mb:.1f} MB, {total} tracks, "
        f"hnsw={'yes' if has_vss else 'no'}) in {time.time() - start:.1f}s"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build small sample index DB")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--source", default=None,
        help="Full cloudcrate.duckdb to subset (omit for synthetic mode)",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Force synthetic mode even if --source is given",
    )
    parser.add_argument("--n", type=int, default=300, help="Rows per table")
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()

    source = None if args.synthetic else args.source
    build_sample(args.output, source, args.n, args.seed)
