# EchoLocate CLAP fine-tuning

Local (MacBook M-series / MPS) workspace for fine-tuning the production CLAP model on **FMA**
data, to improve semantic retrieval measured against the FMA-only eval set. Nothing here
touches the production embedding pipeline, DuckDB index, or Rust service.

See `CLAP_FINETUNING_PLAN.md` for the full phased plan. Current status: **Phase 0 (baseline)**,
**Phase 1 (inference parity)**, and **Phase 2 (dataset construction)** complete.

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
  data/                 # Phase 2: dataset construction (FMA only)
    fma_meta.py         # tracks.csv + genres.csv + echonest.csv -> cleaned per-track table
    splits.py           # FMA official split + leakage repair + eval holdout
    captions.py         # deterministic template captions (library, imported by build_manifest)
    captions_llm.py     # resumable Ollama paraphrase job (qwen3:30b-a3b)
    build_manifest.py   # -> manifest.parquet (per-chunk pairs) + hard_negatives.parquet
    stats.py            # -> dataset_stats.md
    spot_check.py       # listen to random caption/audio pairs (⛔ exit checkpoint)
data/                   # snapshot, qrels, labels_raw, dataset/ (all gitignored)
results/                # baseline_*.json (gitignored)
checkpoints/            # LoRA adapters, later phases (gitignored)
```

## Phase 2 — build the FMA training dataset

Requires the FMA metadata dump and `fma_large` audio on the mounted drive, and (for LLM
captions) a local Ollama serving `qwen3:30b-a3b`.

```bash
uv run python -m src.data.fma_meta          # -> data/dataset/fma_meta.parquet
uv run python -m src.data.splits            # -> data/dataset/splits.parquet
uv run python -m src.data.build_manifest --templates-only   # manifest from templates alone
# optional: richer captions (resumable, multi-day for the full corpus; runs in background)
uv run python -m src.data.captions_llm --limit 500          # first quality batch
uv run python -m src.data.captions_llm                      # full training split
uv run python -m src.data.build_manifest    # rebuild folding in LLM captions
uv run python -m src.data.stats             # -> dataset_stats.md
uv run python -m src.data.spot_check --n 30 # ⛔ human listen-check before Phase 3
```
