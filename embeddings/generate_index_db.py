"""
Build a stripped "search index" DuckDB from the full cloudcrate.duckdb.

The index DB contains all metadata columns plus v_mid and v_clap (with HNSW
indexes), but omits v_intro and v_outro which are unused by the Rust vector
service. This reduces the DB from ~23GB to ~4-5GB, enabling it to be baked
into a Docker image for fast Cloud Run cold starts.

Usage:
    python generate_index_db.py [--source PATH] [--output PATH]
"""

import argparse
import os
import sys
import time

import duckdb


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(BASE_DIR, "../data/cloudcrate.duckdb")
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "../data/index.duckdb")

TABLES = ["tracks_library", "tracks_fma"]

COLUMNS = [
    "id",
    "title",
    "artist",
    "album",
    "relative_path",
    "track_url",
    "album_url",
    "artist_url",
    "v_mid",
    "v_clap",
    # Track length in seconds (surfaced in the list / now-playing UI).
    "duration",
    # 2D sonar-map coordinates (see generate_projection.py). Run that against the
    # full DB before building the index so these columns are populated.
    "x",
    "y",
    # CLAP-classified "vibe" tags as a JSON-array string (see generate_vibes.py).
    # Run that against the full DB before building the index too.
    "vibes",
]


def build_index_db(source_path: str, output_path: str) -> None:
    if not os.path.exists(source_path):
        print(f"Source database not found: {source_path}")
        sys.exit(1)

    if os.path.exists(output_path):
        os.remove(output_path)
        print(f"Removed existing {output_path}")

    start = time.time()
    print(f"Source: {source_path}")
    print(f"Output: {output_path}")

    con = duckdb.connect(output_path)
    con.execute("INSTALL vss; LOAD vss;")
    con.execute("SET hnsw_enable_experimental_persistence = true;")

    # Attach the full DB as read-only
    con.execute(f"ATTACH '{source_path}' AS src (READ_ONLY);")

    col_list = ", ".join(COLUMNS)

    for table in TABLES:
        print(f"\nCopying {table}...")
        # CREATE TABLE AS SELECT copies data and infers schema
        con.execute(
            f"CREATE TABLE {table} AS SELECT {col_list} FROM src.{table};"
        )
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {count} rows copied.")

        # Add primary key (DuckDB supports this after creation)
        con.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (id);")

    con.execute("DETACH src;")

    # Build HNSW indexes
    print("\nBuilding HNSW indexes...")
    for table in TABLES:
        short = table.replace("tracks_", "")
        for col, dim in [("mid", 768), ("clap", 512)]:
            idx_name = f"idx_{short}_{col}"
            print(f"  {idx_name} on {table}.v_{col}...")
            con.execute(
                f"CREATE INDEX {idx_name} ON {table} USING HNSW (v_{col}) "
                f"WITH (metric = 'cosine');"
            )

    # Union view
    print("\nCreating union view 'tracks'...")
    con.execute("""
        CREATE VIEW tracks AS
          SELECT *, 'library' AS source FROM tracks_library
          UNION ALL
          SELECT *, 'fma' AS source FROM tracks_fma;
    """)

    # Text indexes
    print("Creating text indexes...")
    for table in TABLES:
        con.execute(f"CREATE INDEX idx_{table}_title ON {table} (title);")
        con.execute(f"CREATE INDEX idx_{table}_artist ON {table} (artist);")
        con.execute(f"CREATE INDEX idx_{table}_album ON {table} (album);")

    # Persist everything
    print("\nCheckpointing...")
    con.execute("CHECKPOINT;")

    # Summary
    print("\n" + "=" * 50)
    print("Index DB Summary:")
    lib_count = con.execute("SELECT COUNT(*) FROM tracks_library").fetchone()[0]
    fma_count = con.execute("SELECT COUNT(*) FROM tracks_fma").fetchone()[0]
    print(f"  Total tracks: {lib_count + fma_count}")
    print(f"  - library: {lib_count}")
    print(f"  - fma: {fma_count}")

    indexes = con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
    print(f"  Indexes: {[idx[0] for idx in indexes]}")

    con.close()

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    elapsed = time.time() - start
    print(f"\nCreated {output_path} ({size_mb:.0f} MB) in {elapsed:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build stripped index DuckDB")
    parser.add_argument(
        "--source", default=DEFAULT_SOURCE, help="Path to full cloudcrate.duckdb"
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Path for output index.duckdb"
    )
    args = parser.parse_args()
    build_index_db(args.source, args.output)
