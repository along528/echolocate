"""
Cycle-consistency evaluation of generated captions (no human labels needed).

A caption is good if it round-trips through CLAP: embed the caption with the
CLAP text encoder, retrieve against every v_clap in the corpus, and record
the rank of the caption's own source track. Captions whose source track ranks
poorly describe something other than what the track sounds like.

Reports recall@{1,5,10,100}, median rank, MRR, and the worst offenders.
Per-track results (cc_rank, cc_sim) go to caption_eval.jsonl and are used by
load_descriptions.py to gate which captions ship.

Usage:
    python evaluate_captions.py [--db PATH] [--captions PATH] [--output PATH]
                                [--report PATH] [--scope corpus|table]
                                [--worst N]
"""

import argparse
import json
import os
import time

import numpy as np

from clap_text import ClapTextEncoder
from corpus import ARTIFACTS_DIR, DEFAULT_DB, connect, load_clap_vectors

DEFAULT_CAPTIONS = os.path.join(ARTIFACTS_DIR, "captions.jsonl")
DEFAULT_OUTPUT = os.path.join(ARTIFACTS_DIR, "caption_eval.jsonl")
DEFAULT_REPORT = os.path.join(ARTIFACTS_DIR, "caption_eval_report.md")

RECALL_KS = [1, 5, 10, 100]


def load_captions(path):
    if not os.path.exists(path):
        raise SystemExit(f"Captions file not found: {path}")
    captions = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("caption"):
                captions[rec["id"]] = rec  # last write wins on duplicates
    if not captions:
        raise SystemExit("No captions found.")
    return captions


def evaluate(db_path, captions_path, output_path, report_path, scope, worst_n):
    start = time.time()
    captions = load_captions(captions_path)
    print(f"Loaded {len(captions)} captions.")

    con = connect(db_path)
    ids, table_of, matrix = load_clap_vectors(con)
    con.close()
    index_of = {tid: i for i, tid in enumerate(ids)}
    table_arr = np.array(table_of)

    evald = [tid for tid in captions if tid in index_of]
    skipped = len(captions) - len(evald)
    if skipped:
        print(f"  Note: {skipped} captioned tracks have no v_clap; skipped.")

    encoder = ClapTextEncoder()
    print(f"Encoding {len(evald)} captions...")
    text_emb = encoder.encode([captions[tid]["caption"] for tid in evald])

    print(f"Ranking against {matrix.shape[0]} tracks (scope: {scope})...")
    results = []
    for row, tid in enumerate(evald):
        src = index_of[tid]
        sims = matrix @ text_emb[row]
        if scope == "table":
            mask = table_arr == table_of[src]
            corpus_n = int(mask.sum())
            rank = int((sims[mask] > sims[src]).sum()) + 1
        else:
            corpus_n = len(sims)
            rank = int((sims > sims[src]).sum()) + 1
        results.append({
            "id": tid,
            "table": table_of[src],
            "cc_rank": rank,
            "cc_sim": round(float(sims[src]), 4),
            "corpus_n": corpus_n,
        })

    ranks = np.array([r["cc_rank"] for r in results])
    corpus_n = int(np.median([r["corpus_n"] for r in results]))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # ---- report ----
    lines = [
        "# Caption cycle-consistency report",
        "",
        f"- Captions evaluated: **{len(results)}** (scope: {scope}, "
        f"corpus ≈ {corpus_n} tracks)",
        f"- Random-caption expectation: median rank ≈ {corpus_n // 2}",
        "",
        "| metric | value |",
        "|---|---|",
    ]
    for k in RECALL_KS:
        lines.append(f"| recall@{k} | {float((ranks <= k).mean()):.3f} |")
    lines.append(f"| median rank | {int(np.median(ranks))} |")
    lines.append(f"| MRR | {float((1.0 / ranks).mean()):.4f} |")
    lines += ["", f"## Worst {worst_n} captions", ""]
    order = np.argsort(-ranks)[:worst_n]
    for i in order:
        r = results[int(i)]
        lines.append(f"- rank **{r['cc_rank']}** — `{r['id']}`: "
                     f"{captions[r['id']]['caption']}")

    report = "\n".join(lines)
    with open(report_path, "w") as f:
        f.write(report + "\n")

    print("\n" + report)
    print(f"\n✅ Done in {time.time() - start:.1f}s")
    print(f"   Per-track results: {output_path}")
    print(f"   Report: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Caption cycle-consistency eval")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--captions", default=DEFAULT_CAPTIONS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--scope", choices=["corpus", "table"], default="corpus",
                        help="Rank against the whole corpus or the track's own table")
    parser.add_argument("--worst", type=int, default=20, dest="worst_n")
    args = parser.parse_args()
    evaluate(args.db, args.captions, args.output, args.report, args.scope,
             args.worst_n)
