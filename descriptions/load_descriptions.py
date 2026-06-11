"""
Load description artifacts into the full DuckDB as columns.

Adds (if missing) and populates:
  - tags                  VARCHAR  -- JSON array of strings, from tags.jsonl
  - description           VARCHAR  -- verified Gemini caption, from captions.jsonl
  - description_cc_rank   INTEGER  -- cycle-consistency rank, from caption_eval.jsonl

Captions are gated by cycle consistency: only captions whose source track
ranks <= --max-cc-rank in their own retrieval (see evaluate_captions.py) are
written; failing captions stay in the artifacts for regeneration. If no eval
file exists, captions load ungated (with a warning).

Idempotent — safe to re-run as artifacts improve. Run against the FULL DB
before embeddings/generate_index_db.py so the baked index inherits the
columns.

Usage:
    python load_descriptions.py [--db PATH] [--tags PATH] [--captions PATH]
                                [--eval PATH] [--max-cc-rank N]
                                [--skip-tags] [--skip-captions]
"""

import argparse
import json
import os
import time

from tqdm import tqdm

from corpus import ARTIFACTS_DIR, DEFAULT_DB, TABLES, connect

DEFAULT_TAGS = os.path.join(ARTIFACTS_DIR, "tags.jsonl")
DEFAULT_CAPTIONS = os.path.join(ARTIFACTS_DIR, "captions.jsonl")
DEFAULT_EVAL = os.path.join(ARTIFACTS_DIR, "caption_eval.jsonl")

COLUMNS = {
    "tags": "VARCHAR",
    "description": "VARCHAR",
    "description_cc_rank": "INTEGER",
}


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def ensure_columns(con):
    for table in TABLES:
        existing = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ?",
                [table],
            ).fetchall()
        }
        for col, dtype in COLUMNS.items():
            if col not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype};")
                print(f"  Added {table}.{col} {dtype}")


def update_column(con, rows, columns, label):
    """Bulk update columns by (id, table). rows: (id, table, *values)."""
    if not rows:
        print(f"  No rows to load for {label}.")
        return
    placeholders = ", ".join("?" for _ in range(len(columns) + 2))
    col_defs = ", ".join(["id VARCHAR", "tbl VARCHAR"] +
                         [f"{c} {COLUMNS[c]}" for c in columns])
    con.execute(f"CREATE TEMP TABLE load_tmp ({col_defs});")
    chunk = 5000
    for i in tqdm(range(0, len(rows), chunk), desc=f"  Staging {label}", unit="chunk"):
        con.executemany(
            f"INSERT INTO load_tmp VALUES ({placeholders})", rows[i:i + chunk]
        )
    set_clause = ", ".join(f"{c} = t.{c}" for c in columns)
    for table in TABLES:
        con.execute(
            f"UPDATE {table} SET {set_clause} FROM load_tmp t "
            f"WHERE {table}.id = t.id AND t.tbl = ?;",
            [table],
        )
    con.execute("DROP TABLE load_tmp;")
    for table in TABLES:
        n = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {columns[0]} IS NOT NULL"
        ).fetchone()[0]
        print(f"  {table}: {n} rows have {columns[0]}.")


def main(args):
    start = time.time()
    con = connect(args.db)
    ensure_columns(con)

    if not args.skip_tags:
        print("\nLoading tags...")
        tag_rows = [
            (r["id"], r["table"], json.dumps(r["tags"]))
            for r in read_jsonl(args.tags)
            if r.get("tags")
        ]
        update_column(con, tag_rows, ["tags"], "tags")

    if not args.skip_captions:
        print("\nLoading captions...")
        cc_rank = {r["id"]: r["cc_rank"] for r in read_jsonl(args.eval)}
        if not cc_rank:
            print(f"  ⚠️  No eval results at {args.eval} — loading captions UNGATED. "
                  f"Run evaluate_captions.py first to enable quality gating.")
        captions = {r["id"]: r for r in read_jsonl(args.captions) if r.get("caption")}
        caption_rows, gated_out = [], 0
        for tid, rec in captions.items():
            rank = cc_rank.get(tid)
            if rank is not None and rank > args.max_cc_rank:
                gated_out += 1
                continue
            caption_rows.append((tid, rec["table"], rec["caption"], rank))
        if gated_out:
            print(f"  Gated out {gated_out} captions with cc_rank > {args.max_cc_rank}.")
        update_column(con, caption_rows, ["description", "description_cc_rank"],
                      "captions")

    con.execute("CHECKPOINT;")
    con.close()
    print(f"\n✅ Done in {time.time() - start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load tags/captions into DuckDB")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--tags", default=DEFAULT_TAGS)
    parser.add_argument("--captions", default=DEFAULT_CAPTIONS)
    parser.add_argument("--eval", default=DEFAULT_EVAL)
    parser.add_argument("--max-cc-rank", type=int, default=100,
                        help="Only ship captions whose source ranks <= N (default 100)")
    parser.add_argument("--skip-tags", action="store_true")
    parser.add_argument("--skip-captions", action="store_true")
    main(parser.parse_args())
