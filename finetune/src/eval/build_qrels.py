"""
Phase 0.2 — Build a frozen qrel set from the Echoes relevance labels.

Reads the locally-cached label objects (synced from
`gs://cloud-crate-vector-db/labels/{search_events,label_events}/`) and produces a reusable,
graded relevance judgment set keyed on **(query text, source)** — relevance is a property of
the query+track, independent of which model/enhance-path originally surfaced the track.

Join: `LabelEvent.search_id -> SearchEvent` recovers the raw `query.text`, the `source`
(`params.source`), and the ranked result list. Only text/semantic queries are kept (that is the
CLAP retrieval path this fine-tune targets).

Signal -> graded gain:
    relevant = 2, borderline = 1, wrong = 0, cleared = (retraction; drops the judgment)

De-duplication: for each (query, source, track_id) keep the label with the latest timestamp.
If that latest label is `cleared`, the pair is treated as unjudged and dropped.

Outputs (under finetune/data/qrels/):
    qrels_<date>.parquet    columns: query, source, track_id, gain
    queries_<date>.parquet  columns: query, source, n_judged, n_positive
    qrels_<date>.meta.json  provenance + distribution stats

Sync the raw objects first (reproducible cache):
    gcloud storage rsync -r gs://cloud-crate-vector-db/labels/search_events  data/labels_raw/search_events
    gcloud storage rsync -r gs://cloud-crate-vector-db/labels/label_events   data/labels_raw/label_events

Usage:
    uv run python -m src.eval.build_qrels
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

SIGNAL_GAIN = {"relevant": 2, "borderline": 1, "wrong": 0}
# "cleared" is intentionally absent: it retracts a judgment rather than assigning a gain.
CLEARED = "cleared"

FINETUNE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = FINETUNE_ROOT / "data" / "labels_raw"
DEFAULT_OUT_DIR = FINETUNE_ROOT / "data" / "qrels"


def _load_json_dir(path: Path) -> list[dict]:
    out = []
    for f in sorted(path.rglob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            print(f"  warning: skipping unparseable {f}")
    return out


def _query_text(search_event: dict) -> str | None:
    q = search_event.get("query")
    if isinstance(q, dict):
        text = q.get("text")
    elif isinstance(q, str):
        text = q
    else:
        text = None
    if text is None:
        return None
    text = text.strip()
    return text or None


def _enhanced_text(search_event: dict) -> str | None:
    q = search_event.get("query")
    if isinstance(q, dict):
        et = q.get("enhanced_text")
        if et and et.strip():
            return et.strip()
    return None


def build_qrels(raw_dir: Path, out_dir: Path) -> dict:
    search_events = _load_json_dir(raw_dir / "search_events")
    label_events = _load_json_dir(raw_dir / "label_events")
    if not search_events:
        raise FileNotFoundError(f"No search_events under {raw_dir} — run the gcloud rsync first.")

    # search_id -> (query_text, source), keeping only text-kind searches.
    # Also tally, per (query, source), the enhanced_text variants actually sent to CLAP —
    # ~all labeled searches ran enhance=on, so the eval must replay that expanded text
    # (deterministically, from this frozen cache) to match the labeled retrieval path.
    search_index: dict[str, tuple[str, str]] = {}
    enhanced_variants: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for se in search_events:
        if se.get("query_kind") != "text":
            continue
        sid = se.get("search_id")
        qtext = _query_text(se)
        if not sid or not qtext:
            continue
        source = (se.get("params") or {}).get("source") or "unknown"
        search_index[sid] = (qtext, source)
        et = _enhanced_text(se)
        if et:
            enhanced_variants[(qtext, source)][et] += 1

    def canonical_eval_text(query: str, source: str) -> tuple[str, bool]:
        """Deterministic query text to encode: most-frequent enhanced variant (lexicographic
        tiebreak), or the raw query if the search was never enhanced. Returns (text, enhanced)."""
        variants = enhanced_variants.get((query, source))
        if not variants:
            return query, False
        best = min(variants.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return best, True

    # (query, source, track_id) -> latest (timestamp, signal)
    latest: dict[tuple[str, str, str], tuple[str, str]] = {}
    n_labels_seen = 0
    n_labels_unmatched = 0
    for le in label_events:
        sid = le.get("search_id")
        track_id = le.get("track_id")
        signal = le.get("signal")
        ts = le.get("timestamp") or ""
        if not sid or not track_id or signal is None:
            continue
        n_labels_seen += 1
        if sid not in search_index:
            n_labels_unmatched += 1
            continue
        qtext, source = search_index[sid]
        key = (qtext, source, track_id)
        prev = latest.get(key)
        if prev is None or ts > prev[0]:  # ISO-8601 timestamps sort lexicographically
            latest[key] = (ts, signal)

    # Materialize graded qrels, dropping retractions.
    qrels: list[tuple[str, str, str, int]] = []
    n_cleared = 0
    for (qtext, source, track_id), (_ts, signal) in latest.items():
        if signal == CLEARED:
            n_cleared += 1
            continue
        gain = SIGNAL_GAIN.get(signal)
        if gain is None:
            continue
        qrels.append((qtext, source, track_id, gain))

    # Per-(query, source) stats.
    per_query: dict[tuple[str, str], dict] = defaultdict(lambda: {"n_judged": 0, "n_positive": 0})
    for qtext, source, _tid, gain in qrels:
        s = per_query[(qtext, source)]
        s["n_judged"] += 1
        if gain > 0:
            s["n_positive"] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    qrels_path = out_dir / f"qrels_{date}.parquet"
    queries_path = out_dir / f"queries_{date}.parquet"

    con = duckdb.connect()
    con.execute("CREATE TABLE qrels(query VARCHAR, source VARCHAR, track_id VARCHAR, gain INTEGER)")
    con.executemany("INSERT INTO qrels VALUES (?,?,?,?)", qrels)
    con.execute(
        f"COPY (SELECT * FROM qrels ORDER BY query, source, gain DESC, track_id) "
        f"TO '{qrels_path}' (FORMAT PARQUET)"
    )
    con.execute(
        "CREATE TABLE queries(query VARCHAR, source VARCHAR, eval_text VARCHAR, "
        "enhanced BOOLEAN, n_judged INTEGER, n_positive INTEGER)"
    )
    n_enhanced = 0
    query_rows = []
    for (q, s), v in per_query.items():
        eval_text, enhanced = canonical_eval_text(q, s)
        n_enhanced += int(enhanced)
        query_rows.append((q, s, eval_text, enhanced, v["n_judged"], v["n_positive"]))
    con.executemany("INSERT INTO queries VALUES (?,?,?,?,?,?)", query_rows)
    con.execute(
        f"COPY (SELECT * FROM queries ORDER BY n_judged DESC, query) "
        f"TO '{queries_path}' (FORMAT PARQUET)"
    )
    con.close()

    # Distribution stats for the write-up.
    gains = [g for *_r, g in qrels]
    judged_counts = sorted(v["n_judged"] for v in per_query.values())
    positive_queries = sum(1 for v in per_query.values() if v["n_positive"] > 0)

    def _pctile(xs: list[int], p: float) -> float:
        if not xs:
            return 0.0
        i = min(len(xs) - 1, int(p * (len(xs) - 1)))
        return xs[i]

    meta = {
        "created": dt.datetime.now().astimezone().isoformat(),
        "date": date,
        "raw_dir": str(raw_dir),
        "search_events_total": len(search_events),
        "search_events_text_kind": len(search_index),
        "label_events_total": len(label_events),
        "label_events_matched": n_labels_seen - n_labels_unmatched,
        "label_events_unmatched": n_labels_unmatched,
        "cleared_retractions": n_cleared,
        "signal_gain_map": SIGNAL_GAIN,
        "qrels_path": str(qrels_path),
        "queries_path": str(queries_path),
        "n_qrels": len(qrels),
        "n_query_source_pairs": len(per_query),
        "n_queries_enhanced_eval_text": n_enhanced,
        "n_queries_with_positive": positive_queries,
        "gain_distribution": {
            "gain_2_relevant": gains.count(2),
            "gain_1_borderline": gains.count(1),
            "gain_0_wrong": gains.count(0),
        },
        "judged_per_query": {
            "min": judged_counts[0] if judged_counts else 0,
            "p50": _pctile(judged_counts, 0.5),
            "p90": _pctile(judged_counts, 0.9),
            "max": judged_counts[-1] if judged_counts else 0,
        },
    }
    (out_dir / f"qrels_{date}.meta.json").write_text(json.dumps(meta, indent=2))

    print(f"Wrote {len(qrels):,} qrels across {len(per_query)} (query, source) pairs")
    print(f"  {qrels_path}")
    print(f"  {queries_path}")
    print(
        f"  gains: relevant={gains.count(2)}  borderline={gains.count(1)}  wrong={gains.count(0)}  "
        f"| cleared(dropped)={n_cleared}  unmatched labels={n_labels_unmatched}"
    )
    print(
        f"  queries with >=1 positive: {positive_queries}/{len(per_query)}  "
        f"| judged/query p50={meta['judged_per_query']['p50']} max={meta['judged_per_query']['max']}"
    )
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Build frozen qrels from cached Echoes labels.")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args()
    build_qrels(args.raw_dir, args.out_dir)


if __name__ == "__main__":
    main()
