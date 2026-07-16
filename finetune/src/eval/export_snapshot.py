"""
Phase 0.1 — Snapshot the production CLAP embeddings to Parquet.

Reads the local full production DuckDB (`data/cloudcrate.duckdb`, the `tracks` view) and
writes a reproducible Parquet snapshot of the metadata + `v_clap` vectors, tagged with
`model_version='clap-base-v1'`. Also audits the zero-vector fallback that
`embeddings/generate_db.py` writes when a track has no CLAP embedding, so we know how much
of each corpus is usable ground truth.

Nothing is written back to the source DB (opened read-only).

Usage:
    uv run python -m src.eval.export_snapshot            # default paths
    uv run python -m src.eval.export_snapshot --db ../data/cloudcrate.duckdb
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb

MODEL_VERSION = "clap-base-v1"
# CLAP vectors are L2-normalized at generation time, so a valid vector has squared norm ~1.0
# and the zero-vector fallback has squared norm 0. Anything below this threshold is "missing".
ZERO_NORM_SQ_THRESHOLD = 1e-6

# Columns carried into the snapshot. `v_mid` is included so the same snapshot can support
# MERT-side sanity checks later without re-reading the 23 GB DB; everything else is metadata.
SNAPSHOT_COLUMNS = [
    "id",
    "source",
    "artist",
    "album",
    "title",
    "relative_path",
    "duration",
    "x",
    "y",
    "v_clap",
]

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = FINETUNE_ROOT.parent / "data" / "cloudcrate.duckdb"
DEFAULT_OUT_DIR = FINETUNE_ROOT / "data" / "snapshot"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_zero_vectors(con: duckdb.DuckDBPyConnection) -> dict:
    """Per-source counts of total / non-zero / zero `v_clap` rows."""
    rows = con.execute(
        f"""
        SELECT
            source,
            COUNT(*) AS total,
            COUNT(*) FILTER (
                WHERE array_inner_product(v_clap, v_clap) < {ZERO_NORM_SQ_THRESHOLD}
            ) AS zero_clap
        FROM tracks
        GROUP BY source
        ORDER BY source
        """
    ).fetchall()
    audit = {}
    for source, total, zero in rows:
        audit[source] = {
            "total": int(total),
            "zero_clap": int(zero),
            "nonzero_clap": int(total - zero),
            "nonzero_coverage": round((total - zero) / total, 4) if total else 0.0,
        }
    return audit


def export_snapshot(db_path: Path, out_dir: Path) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"Production DB not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    parquet_path = out_dir / f"tracks_clap_{date}.parquet"

    con = duckdb.connect(str(db_path), read_only=True)

    audit = audit_zero_vectors(con)

    select_cols = ", ".join(SNAPSHOT_COLUMNS)
    con.execute(
        f"""
        COPY (
            SELECT {select_cols}, '{MODEL_VERSION}' AS model_version
            FROM tracks
        ) TO '{parquet_path}' (FORMAT PARQUET)
        """
    )
    n_rows = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
    ).fetchone()[0]
    con.close()

    meta = {
        "created": dt.datetime.now().astimezone().isoformat(),
        "date": date,
        "model_version": MODEL_VERSION,
        "source_db": str(db_path),
        "parquet": str(parquet_path),
        "parquet_sha256": _sha256(parquet_path),
        "row_count": int(n_rows),
        "columns": SNAPSHOT_COLUMNS + ["model_version"],
        "zero_norm_sq_threshold": ZERO_NORM_SQ_THRESHOLD,
        "zero_vector_audit": audit,
    }
    meta_path = out_dir / f"tracks_clap_{date}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"Wrote snapshot: {parquet_path} ({n_rows:,} rows)")
    print(f"Wrote metadata: {meta_path}")
    print("Zero-vector audit (usable CLAP coverage per source):")
    for source, a in audit.items():
        print(
            f"  {source:8s} total={a['total']:>7,}  "
            f"nonzero={a['nonzero_clap']:>7,}  "
            f"zero={a['zero_clap']:>6,}  "
            f"coverage={a['nonzero_coverage']:.1%}"
        )
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot production CLAP embeddings to Parquet.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to cloudcrate.duckdb")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Snapshot output dir")
    args = ap.parse_args()
    export_snapshot(args.db, args.out_dir)


if __name__ == "__main__":
    main()
