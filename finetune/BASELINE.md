# CLAP retrieval baseline — Phase 0

Frozen baseline the fine-tuned model must beat. Everything here is deterministic and
reproducible from the local snapshot + frozen label cache (no live services).

- **Date:** 2026-07-14
- **Checkpoint:** `laion/clap-htsat-unfused` @ `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`
- **Model version:** `clap-base-v1`
- **Repo git SHA:** `d2e5eea`
- **Snapshot:** `data/snapshot/tracks_clap_2026-07-14.parquet` (124,803 rows)
- **Qrels:** `data/qrels/qrels_2026-07-14.parquet` (252 judgments, 38 query/source pairs)
- **Determinism:** two runs produced byte-identical `results/baseline_2026-07-14.json`
  (sha256 `57eec5c9…`).

## Headline numbers

Metric aggregates are over queries with ≥1 positive judgment. Because the judged pool is
small, the most trustworthy figure is the well-judged subset (coverage ≈ how much of the
top-10 is actually judged).

| Query subset | n | NDCG@10 | Recall@10 | judged@10 coverage |
|---|---|---|---|---|
| All scored (n_positive > 0) | 34 | **0.439** | 0.510 | 0.38 |
| Well-judged (n_judged ≥ 5)  | 17 | **0.581** | 0.658 | 0.72 |
| Best-judged (n_judged ≥ 10) | 11 | **0.642** | 0.710 | 0.87 |

Reported per metric:
- **NDCG@10** — graded gains (relevant=2, borderline=1, wrong=0), exponential gain `2^g−1`,
  `log2(rank+2)` discount, ideal DCG from the query's judged pool.
- **Recall@10** — positives (gain > 0) retrieved in top-10 ÷ positives known for the query
  (recall *within the seed judgments*, not absolute recall).
- **judged@10 coverage** — fraction of the top-10 that carries any judgment; the trust signal
  for NDCG on that query. Bounded above by `n_judged/10`, so short-judged queries cap low.

## What this eval actually measures — read before trusting it

1. **FMA only, not the personal library.** All 38 judged query/source pairs are `source=fma`.
   The Echoes labelers only ever judged FMA results, so this baseline measures general CLAP
   semantic retrieval on FMA — **not** retrieval over the free-jazz/krautrock/noise library
   the fine-tune targets. A fine-tune that helps the library could still move this number
   (shared audio encoder), but a library-specific eval set does not exist yet and must be
   built (Phase 4 pooling, or fresh labeling) before we can claim library gains.
2. **Enhanced-query retrieval, replayed deterministically.** 441 of 442 labeled text searches
   ran with `enhance=on` (Gemini query expansion). Scoring the raw query instead collapses
   judged@10 coverage to ~0.05 and NDCG to ~0.09 — the labels live on the *expanded* retrieval
   path. So the baseline encodes each query's **stored** `enhanced_text` (the canonical
   most-frequent variant per query), which reproduces the labeled path with **no live Gemini
   call**, keeping the run deterministic. This deviates from the plan's "enhance=off" wording;
   the data forced it. The fine-tuned model will be scored identically, so the comparison is
   fair. 35/38 pairs have an enhanced variant; 3 short raw queries fall back to raw text.
3. **Sparse judgments.** Median judged tracks/query = 4 (p90 = 15, max = 22). Queries with
   1–2 judgments are near-noise (a single positive that ranks 11th scores NDCG 0). Weight the
   n_judged ≥ 10 subset when reading go/no-go signals.
4. **Unjudged = non-relevant.** Standard assumption; its risk is exactly what judged@10
   coverage quantifies. This is a **seed** baseline — Phase 4 should pool the fine-tuned
   model's top-k and top-up label the unjudged results before a final verdict.

## Corpus / embedding coverage (zero-vector audit)

`v_clap` is L2-normalized at generation; the `[0.0]*512` fallback marks tracks that never got
a CLAP embedding. Non-zero coverage:

| source | total | non-zero v_clap | zero | coverage |
|---|---|---|---|---|
| fma | 105,391 | 105,391 | 0 | 100.0% |
| library | 19,412 | 19,306 | 106 | 99.5% |

The library target set is essentially intact (106 unusable tracks out of 19,412).

## Label provenance

- Source: `gs://cloud-crate-vector-db/labels/{search_events,label_events}/` synced to
  `data/labels_raw/` (724 search events, 313 label events).
- 442 search events are text-kind; 298/313 label events joined to a text search (15 unmatched
  — their search event was non-text or absent).
- Gain distribution: relevant=102, borderline=68, wrong=82. Zero `cleared` retractions.
- Dedup: latest label per (query, source, track_id) by timestamp wins; `cleared` drops the pair.

## Per-query results

| query | judged | +pos | NDCG@10 | Recall@10 | judged@10 |
|---|---|---|---|---|---|
| acid house squelchy 303 bassline | 1 | 1 | 1.000 | 1.000 | 0.10 |
| sparse minimal classical with solo violin | 6 | 6 | 1.000 | 1.000 | 0.60 |
| Summertime in the backyard at a bbq | 4 | 3 | 0.952 | 1.000 | 0.40 |
| chiptune arpeggios and 8-bit drums | 10 | 10 | 0.935 | 1.000 | 1.00 |
| melancholic piano with strings | 10 | 7 | 0.933 | 0.857 | 0.90 |
| spacey cosmic synth arpeggios | 10 | 6 | 0.856 | 1.000 | 1.00 |
| meditative singing bowls and drones | 8 | 7 | 0.776 | 1.000 | 0.80 |
| crunchy breakbeats and jungle rollers | 4 | 3 | 0.765 | 0.667 | 0.20 |
| warm jazz saxophone | 10 | 5 | 0.711 | 1.000 | 0.90 |
| bright acoustic fingerpicking | 17 | 16 | 0.697 | 0.375 | 0.60 |
| Summer in the backyard in North Carolina | 3 | 2 | 0.689 | 1.000 | 0.30 |
| Summer in the backyard | 2 | 1 | 0.631 | 1.000 | 0.20 |
| orchestral swells | 1 | 1 | 0.631 | 1.000 | 0.10 |
| funky bass grooves and tight percussion | 22 | 19 | 0.552 | 0.368 | 0.90 |
| shimmering shoegaze wall of sound | 15 | 4 | 0.552 | 0.750 | 0.70 |
| wobbly tape-warped synths and delay | 15 | 15 | 0.513 | 0.600 | 0.90 |
| polyrhythmic afrobeat horns and percussion | 12 | 2 | 0.491 | 1.000 | 1.00 |
| Twangy indie from North Carolina | 20 | 10 | 0.410 | 0.500 | 0.90 |
| chaotic free jazz improvisation | 22 | 14 | 0.407 | 0.357 | 0.80 |
| cinematic tension with low cello | 8 | 5 | 0.403 | 0.800 | 0.70 |
| ethereal vocals | 2 | 2 | 0.387 | 0.500 | 0.10 |
| dreamy lo-fi beats | 7 | 7 | 0.387 | 0.286 | 0.20 |
| thunderous orchestral percussion | 8 | 7 | 0.246 | 0.286 | 0.30 |
| Death metal | 3 | 3 | 0.000 | 0.000 | 0.00 |
| afrobeat horns | 3 | 3 | 0.000 | 0.000 | 0.00 |
| bossa nova | 5 | 2 | 0.000 | 0.000 | 0.00 |
| cosmic synth | 1 | 1 | 0.000 | 0.000 | 0.00 |
| funky bass | 2 | 1 | 0.000 | 0.000 | 0.00 |
| glitchy IDM | 1 | 1 | 0.000 | 0.000 | 0.00 |
| krautrock motorik | 1 | 1 | 0.000 | 0.000 | 0.00 |
| melancholic piano | 1 | 1 | 0.000 | 0.000 | 0.00 |
| shoegaze wall | 1 | 1 | 0.000 | 0.000 | 0.00 |
| smooth jazz | 2 | 2 | 0.000 | 0.000 | 0.00 |
| surf rock reverb | 2 | 1 | 0.000 | 0.000 | 0.00 |

Excluded from scored aggregates (no positive judgments): "Skateboarding in California in the
90s", "Thing", "raw punk", "soulful organ and gospel choir".

The 0.000 rows are mostly 1–2-judgment queries whose lone positive fell outside the top-10;
"Death metal" (3 positives, all missed) is a genuine weak spot — FMA is thin on the genre and
the labeled positives rank low.

## Reproduce

```bash
cd finetune && uv sync
uv run python -m src.eval.export_snapshot        # data/snapshot/*.parquet + zero-vec audit
# sync raw labels (data/ is gitignored, so this local cache must be (re)fetched from GCS):
gcloud storage rsync -r gs://cloud-crate-vector-db/labels/search_events data/labels_raw/search_events
gcloud storage rsync -r gs://cloud-crate-vector-db/labels/label_events  data/labels_raw/label_events
uv run python -m src.eval.build_qrels            # data/qrels/*.parquet
uv run python -m src.eval.run_baseline           # results/baseline_<date>.json
```

## ⛔ Checkpoint — decisions needed before training

1. **Is this FMA-only eval an acceptable proxy** to guard against regressions while we fine-tune
   on the library, given no library eval set exists yet? Or should we build a small library
   query/qrel set first (recommended before claiming library gains)?
2. **Trust the seed labels?** 34 scored queries, median 4 judgments each. Good enough to detect
   a real improvement on the n_judged ≥ 10 subset, but underpowered per-query elsewhere.
3. Confirm the **replayed-enhanced-text** eval design (vs. raw enhance=off) is the right
   yardstick — it matches how the labels were collected and stays deterministic.
