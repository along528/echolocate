"""
Phase 0.3/0.4 — Run the baseline retrieval eval against the frozen snapshot + qrels.

For each (query, source) in the qrel set:
  1. Encode the query's *stored enhanced text* (the canonical most-frequent Gemini-expanded
     variant from the labeled search events; raw text fallback when none exists) to a CLAP
     text vector, on deterministic CPU.
  2. Cosine-rank it against all `v_clap` in that source from the Parquet snapshot.
     Stable tie-break: score DESC, then track_id ASC.
  3. Score NDCG@10 / recall@10 / judged@10 coverage against the query's qrels.

Replaying the stored enhanced text reproduces the retrieval path the labels were collected on
(441/442 labeled text searches ran with enhance=on) with no live Gemini call, so the run stays
deterministic — see BASELINE.md "What this eval actually measures". Writes
results/baseline_<date>.json with per-query + aggregate scores plus full provenance
(git SHA, snapshot + qrel hashes, model_version, HF revision).

Usage:
    uv run python -m src.eval.run_baseline
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import numpy as np

from src.clap_common import CHECKPOINT, REVISION, encode_texts, pick_device
from src.eval.score import K, judged_coverage_at_k, ndcg_at_k, recall_at_k

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = FINETUNE_ROOT / "data" / "snapshot"
QRELS_DIR = FINETUNE_ROOT / "data" / "qrels"
RESULTS_DIR = FINETUNE_ROOT / "results"
MODEL_VERSION = "clap-base-v1"


def _latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matches {pattern}")
    return Path(matches[-1])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=FINETUNE_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _load_source_matrix(snapshot: Path, source: str):
    """Return (ids: list[str], mat: float32 [N,512] L2-normalized) for one source."""
    con = duckdb.connect()
    rows = con.execute(
        "SELECT id, v_clap FROM read_parquet(?) WHERE source = ? ORDER BY id",
        [str(snapshot), source],
    ).fetchall()
    con.close()
    ids = [r[0] for r in rows]
    mat = np.asarray([r[1] for r in rows], dtype=np.float32)
    # Snapshot vectors are already unit-norm; renormalize defensively (zero-vectors -> stay 0).
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, mat / norms


def run(snapshot: Path, qrels: Path, queries: Path, out_dir: Path) -> dict:
    con = duckdb.connect()
    qrel_rows = con.execute(
        "SELECT query, source, track_id, gain FROM read_parquet(?)", [str(qrels)]
    ).fetchall()
    query_rows = con.execute(
        "SELECT query, source, eval_text, enhanced, n_judged, n_positive "
        "FROM read_parquet(?) ORDER BY query, source",
        [str(queries)],
    ).fetchall()
    con.close()

    # (query, source) -> {track_id: gain}
    qrel_map: dict[tuple[str, str], dict[str, int]] = {}
    for query, source, tid, gain in qrel_rows:
        qrel_map.setdefault((query, source), {})[tid] = int(gain)

    device = pick_device("cpu")  # deterministic baseline
    sources = sorted({s for _q, s, *_ in query_rows})
    source_cache = {s: _load_source_matrix(snapshot, s) for s in sources}

    # Encode each query's canonical eval_text (the replayed Gemini expansion, deterministic)
    # in one batch, preserving order. This matches the labeled retrieval path (enhance=on).
    ordered = [(q, s, et, bool(enh)) for q, s, et, enh, *_ in query_rows]
    texts = [et for _q, _s, et, _enh in ordered]
    text_vecs = encode_texts(texts, device=device)

    per_query = []
    for (query, source, eval_text, enhanced), qvec in zip(ordered, text_vecs):
        ids, mat = source_cache[source]
        scores = mat @ qvec.astype(np.float32)
        # Stable ranking: score DESC, id ASC. argsort by (-score) then id via lexsort.
        order = np.lexsort((np.asarray(ids), -scores))
        ranked_ids = [ids[i] for i in order[:K]]
        qrel = qrel_map[(query, source)]
        per_query.append(
            {
                "query": query,
                "source": source,
                "eval_text": eval_text,
                "enhanced": enhanced,
                "n_judged": len(qrel),
                "n_positive": sum(1 for g in qrel.values() if g > 0),
                "ndcg@10": round(ndcg_at_k(ranked_ids, qrel), 6),
                "recall@10": round(recall_at_k(ranked_ids, qrel), 6),
                "judged@10": round(judged_coverage_at_k(ranked_ids, qrel), 6),
                "top10": ranked_ids,
            }
        )

    def _mean(key: str) -> float:
        vals = [p[key] for p in per_query]
        return round(sum(vals) / len(vals), 6) if vals else 0.0

    # Aggregate over queries that have at least one positive (NDCG is 0/undefined otherwise).
    scored = [p for p in per_query if p["n_positive"] > 0]

    def _mean_scored(key: str) -> float:
        vals = [p[key] for p in scored]
        return round(sum(vals) / len(vals), 6) if vals else 0.0

    out_dir.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    result = {
        "run": {
            "date": date,
            "model_version": MODEL_VERSION,
            "checkpoint": CHECKPOINT,
            "hf_revision": REVISION,
            "query_text": "replayed_enhanced",  # stored Gemini expansion, deterministic (no live API)
            "device": str(device),
            "k": K,
            "git_sha": _git_sha(),
            "snapshot": str(snapshot),
            "snapshot_sha256": _sha256(snapshot),
            "qrels": str(qrels),
            "qrels_sha256": _sha256(qrels),
        },
        "aggregate": {
            "n_query_source_pairs": len(per_query),
            "n_scored": len(scored),
            "ndcg@10_mean_all": _mean("ndcg@10"),
            "ndcg@10_mean_scored": _mean_scored("ndcg@10"),
            "recall@10_mean_scored": _mean_scored("recall@10"),
            "judged@10_mean": _mean("judged@10"),
        },
        "per_query": sorted(per_query, key=lambda p: (-p["ndcg@10"], p["query"])),
    }
    out_path = out_dir / f"baseline_{date}.json"
    out_path.write_text(json.dumps(result, indent=2))

    agg = result["aggregate"]
    print(f"Baseline written: {out_path}")
    print(f"  scored pairs: {agg['n_scored']}/{agg['n_query_source_pairs']}")
    print(f"  NDCG@10  (scored mean): {agg['ndcg@10_mean_scored']:.4f}")
    print(f"  Recall@10 (scored mean): {agg['recall@10_mean_scored']:.4f}")
    print(f"  judged@10 coverage mean: {agg['judged@10_mean']:.4f}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the baseline CLAP retrieval eval.")
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--qrels", type=Path, default=None)
    ap.add_argument("--queries", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = ap.parse_args()
    snapshot = args.snapshot or _latest(str(SNAPSHOT_DIR / "tracks_clap_*.parquet"))
    qrels = args.qrels or _latest(str(QRELS_DIR / "qrels_*.parquet"))
    queries = args.queries or _latest(str(QRELS_DIR / "queries_*.parquet"))
    run(snapshot, qrels, queries, args.out_dir)


if __name__ == "__main__":
    main()
