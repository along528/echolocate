"""
Shared DuckDB corpus loading for the descriptions pipeline.
"""

import os

import numpy as np
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "../data/cloudcrate.duckdb")
ARTIFACTS_DIR = os.path.join(BASE_DIR, "../data/descriptions")

TABLES = ["tracks_library", "tracks_fma"]


def connect(db_path: str):
    import duckdb

    if not os.path.exists(db_path):
        raise SystemExit(f"Database not found: {db_path}")
    con = duckdb.connect(db_path)
    # The tables carry persistent HNSW indexes; VSS must be loaded before
    # they can be read/altered.
    try:
        con.execute("INSTALL vss; LOAD vss; SET hnsw_enable_experimental_persistence = true;")
    except Exception as e:
        print(f"⚠️  Could not load the VSS extension ({e}); "
              f"reads will fail if the DB carries persistent HNSW indexes.")
    return con


def load_clap_vectors(con, tables=TABLES):
    """Return (ids, table_of, matrix) for all tracks with a real v_clap.

    Tracks without CLAP embeddings are stored as zero vectors by
    generate_db.py; those are skipped here.
    """
    ids, table_of, vecs = [], [], []
    for table in tables:
        rows = con.execute(f"SELECT id, v_clap FROM {table}").fetchall()
        for tid, vec in tqdm(rows, desc=f"Reading v_clap from {table}", unit="trk"):
            if vec is None:
                continue
            arr = np.asarray(vec, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm < 1e-6:
                continue
            ids.append(tid)
            table_of.append(table)
            vecs.append(arr / norm)
    if not ids:
        raise SystemExit("No tracks with non-zero v_clap found.")
    return ids, table_of, np.vstack(vecs)
