# EchoLocate CLAP fine-tuning

Local (MacBook M-series / MPS) workspace for fine-tuning the production CLAP model on the
owner's personal music library. Nothing here touches the production embedding pipeline,
DuckDB index, or Rust service.

See `CLAP_FINETUNING_PLAN.md` for the full phased plan. Current status: **Phase 0 (freeze the
baseline)** and **Phase 1 (local inference parity)**.

## Setup

```bash
cd finetune
uv sync            # provisions Python 3.12 + pinned deps into .venv
```

## Data locations (this machine)

- Full production DB: `../data/cloudcrate.duckdb` (23 GB) — source of truth for served embeddings.
- Library CLAP JSONL: `../data/library/clap_embeddings.jsonl`; FMA: `../data/fma/fma_clap_embeddings.jsonl`.
- Audio (external drive, must be mounted):
  - Personal library: `/Volumes/Samsung/Projects/cloud-crate/crate/` (`relative_path` rooted here).
  - FMA: `/Volumes/Samsung/fma/fma_large/<first-3-of-6padded>/<6padded>.mp3`.
- Relevance labels: `gs://cloud-crate-vector-db/labels/{search_events,label_events}/<date>/`.

## Layout

```
src/
  embed.py              # Phase 1: parity-tested port of embeddings/generate_clap.py
  eval/
    export_snapshot.py  # DuckDB -> Parquet snapshot + zero-vector audit
    build_qrels.py      # GCS labels -> frozen qrels
    score.py            # NDCG@10 + recall@10 + judged@10 coverage
    run_baseline.py     # writes results/baseline_<date>.json
data/                   # snapshot parquet, qrels, labels_raw (gitignored)
results/                # baseline_*.json (gitignored)
checkpoints/            # LoRA adapters, later phases (gitignored)
```
