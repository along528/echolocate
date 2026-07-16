# Echolocate: CLAP Fine-Tuning Implementation Plan

**Audience:** Coding agent (Claude Code) working in the Echolocate repository
**Goal:** Fine-tune a CLAP model on the owner's personal music library (free jazz, krautrock, noise, experimental, metal) to improve semantic retrieval quality, measured against the existing eval pipeline (NDCG@10).
**Hardware:** MacBook Pro 16" M5 Pro, 48GB unified memory. All training runs locally via MLX or PyTorch-MPS.
**Existing stack context:** Rust/Axum service on Cloud Run, DuckDB + HNSW index, CLAP/MERT embeddings, Gemini Flash prompt expansion, eval harness with NDCG@10 / re-ranking / MMR diversity.

---

## Ground rules for the agent

1. **Never modify the production embedding pipeline or DuckDB index until Phase 5, and only behind a version flag.** All work happens in a new `finetune/` directory (Python) alongside the Rust service.
2. **Stop and ask for human review at every checkpoint marked ⛔.** Do not proceed past a checkpoint autonomously.
3. **All embeddings are versioned.** Every embedding written anywhere must carry a `model_version` field (e.g., `clap-base-v1`, `clap-nms-lora-v1`). Never overwrite base embeddings.
4. **Reproducibility:** pin all dependencies (uv or pip-tools lockfile), seed all runs, log hyperparameters and git SHA with every training run and eval.
5. **Don't burn disk:** 1TB SSD, audio library is large. Work from the existing audio storage paths; cache mel spectrograms / preprocessed tensors in a size-capped cache dir (`~/.cache/echolocate-ft`, cap 100GB, LRU cleanup script).

---

## Phase 0 — Freeze the baseline

**Objective:** Establish the numbers we're trying to beat, on infrastructure we can rerun identically later.

Tasks:
- Locate the existing eval harness and query set. Document exactly: query set size, relevance judgment source, metrics computed (NDCG@10, plus any re-rank/MMR variants).
- Run the full eval suite against the current production embeddings. Save results as `finetune/results/baseline_<date>.json` with git SHA and index snapshot metadata.
- Snapshot the current DuckDB embedding table (export to Parquet) so the baseline is reproducible even if prod changes.
- Write a one-page `finetune/BASELINE.md` summarizing scores per metric and per query category if categories exist.

**Exit criteria:** Baseline eval runs green twice with identical results (deterministic).
⛔ **Checkpoint: human reviews baseline numbers and confirms the eval set is trusted before any training work.**

---

## Phase 1 — Local CLAP inference (MLX or MPS)

**Objective:** Run the *same* CLAP checkpoint used in production locally, and prove parity.

Tasks:
- Set up `finetune/` Python project (uv, Python 3.12). Dependencies: `torch` (MPS), `laion-clap` or `transformers` CLAP implementation matching the production checkpoint, `librosa`/`torchaudio`, `duckdb`, `numpy`.
- Identify the exact production checkpoint (model name, revision hash, audio preprocessing params: sample rate, mono/stereo handling, chunk length, mel params). Document in `finetune/MODEL_CARD.md`.
- Implement `finetune/src/embed.py`: given an audio file, produce embeddings with identical preprocessing to production.
- **Parity test:** sample 50 tracks that already have production embeddings. Embed locally. Assert cosine similarity ≥ 0.999 per track vs. stored embeddings. If parity fails, debug preprocessing before proceeding — do not continue with mismatched preprocessing.
- Benchmark throughput (tracks/min) on MPS. Decide MLX port only if MPS throughput is insufficient (< ~5x realtime); otherwise MPS is fine and keeps us on the standard PEFT/LoRA ecosystem.

**Exit criteria:** Parity test passes; throughput documented.
⛔ **Checkpoint: human confirms parity results.**

---

## Phase 2 — Dataset construction  ✅ (FMA only)

**Objective:** Build contrastive (audio, text) pairs from the **FMA corpus** with leakage-safe splits.

**Scope decision (2026-07-16):** This fine-tune targets FMA data *only* — no personal library,
Discogs, or Wire vocabulary. The Phase 0 eval set is 100% `source=fma`, so training and
evaluation domains now match. Everything below is FMA-metadata-driven. Implemented in
`src/data/` (see `README.md` Phase 2 for commands); outputs land in `data/dataset/` (gitignored).

Text sources (FMA metadata dump at `/Volumes/Samsung/Projects/echolocate/data/fma/fma_metadata/`):
1. **Template captions** (`captions.py`) — deterministic, seeded per track from `tracks.csv` +
   `genres.csv` + `echonest.csv`: genre names (leaf + top-level via the genre hierarchy), cleaned
   user tags, decade, artist location, and Echonest audio-feature words ("high-energy",
   "acoustic", "instrumental", …). **No artist/album/track names** (captions describe sound, not
   identity). Genre-or-tags required; vacuous tracks (~1.3%) are dropped.
2. **LLM paraphrases** (`captions_llm.py`) — a local Ollama `qwen3:30b-a3b` rewrites the
   structured metadata into 3 evocative sonic descriptions per track. Resumable (append-only
   JSONL cache keyed by track_id), training-split-first, every generation logged. Multi-day for
   the full corpus, so it runs in the background; the manifest folds captions in wherever they
   exist and training can start on templates alone.

Audio processing (`build_manifest.py`):
- Each 30 s FMA clip → three native 10 s CLAP windows at offsets 0/10/20 s (offset recorded;
  the Phase 3 dataloader crops on the fly). Each chunk inherits the track's caption list.
- Hard negatives: `hard_negatives.parquet` maps each leaf genre → its training track_ids, for
  packing within-genre negatives into contrastive batches.

Splits (`splits.py`):
- Start from FMA's official `set.split`. Harden it with a **connected-components leakage check**:
  group tracks by the artist↔album graph (linked if they share an artist_id or album_id) and give
  each whole component one split (majority; stricter split wins ties). This catches compilation
  albums that chain artists across splits — on the full corpus this moved ~8.1k tracks.
- The 238 Phase 0 qrels-judged tracks are reassigned to a `holdout` split and excluded from the
  manifest entirely, so they never train but stay available for the Phase 4 retrieval eval.

Deliverables: `src/data/` builder scripts, `manifest.parquet`, `hard_negatives.parquet`, and
`dataset_stats.md` (pair counts, genre distribution, caption length/source stats, leakage result).

**Result (templates-only):** 103,810 tracks · 311,430 chunks · **1.26M (chunk, caption) pairs**
(far above the ≥5k floor). Leakage check passes (0 after repair); rebuild is byte-identical.

**Exit criteria:** ≥ 5k audio-caption pairs ✅, stats reviewed, leakage check passes ✅.
⛔ **Checkpoint: human spot-checks ~30 random caption/audio pairs** via
`uv run python -m src.data.spot_check --n 30`.

---

## Phase 3 — LoRA contrastive fine-tune

**Objective:** Fine-tune CLAP with LoRA adapters; keep base weights frozen.

Setup:
- PEFT LoRA on the audio encoder's attention layers (and optionally the text encoder — start audio-only, text encoder frozen, since captions are templated).
- Loss: standard CLIP-style symmetric InfoNCE with learnable temperature, initialized from the checkpoint's temperature.
- Batch size: contrastive learning wants large batches. On 48GB unified memory target effective batch ≥ 256 via gradient accumulation (e.g., 64 per step × 4 accumulation). Use the hard-negative map to pack within-genre negatives into batches.
- Hyperparameter starting point: LoRA r=16, alpha=32, lr=1e-4 (adapters only), cosine schedule, 3–5 epochs, early stopping on val retrieval recall@10.
- Log everything to a local tracking file or MLflow-lite (no cloud dependencies). Save adapter checkpoints per epoch.

Runs:
1. Smoke run: 1% of data, 50 steps, confirm loss decreases and checkpoints load.
2. Full run A: audio-encoder LoRA only.
3. Full run B (only if A shows gains): unfreeze text-encoder LoRA too.

Guardrails:
- Monitor for representation collapse: track mean pairwise cosine similarity of val embeddings per epoch; abort if it climbs sharply.
- Thermal/timing note: a full run may take hours; structure as resumable (checkpoint every N steps).

**Exit criteria:** Val recall@10 on held-out pairs beats the frozen base model.
⛔ **Checkpoint: human reviews training curves before Phase 4.**

---

## Phase 4 — Evaluation against the real eval suite

**Objective:** Measure end-to-end retrieval improvement, not just training metrics.

Tasks:
- Re-embed the **entire library** with the fine-tuned model (base + LoRA merged for inference speed). Write to a new versioned table/Parquet: `embeddings_clap_nms_lora_v1`.
- Build a parallel HNSW index over the new embeddings with identical HNSW params to prod (M, ef_construction, ef_search — read them from the Rust config, don't guess).
- Run the Phase 0 eval suite against the new index. Produce a side-by-side report: NDCG@10 overall, per query category, with bootstrap confidence intervals (resample queries, 1000 iterations).
- Qualitative diff: for the 10 queries with the biggest gains and the 10 with the biggest regressions, dump top-10 results before/after into `finetune/results/qualitative_diff.md` for human listening.
- Decision rule: ship-worthy if overall NDCG@10 improves with CI excluding zero AND no query category regresses badly (> 10% relative drop).

⛔ **Checkpoint: human reviews the report and listens to the qualitative diffs. Go/no-go for integration.**

---

## Phase 5 — Integration (only on human go)

**Objective:** Serve the fine-tuned embeddings in Echolocate behind a version switch.

Tasks:
- Add `embedding_model_version` to the Rust service config; index selection keyed on version. Keep base index available for instant rollback.
- Embedding for *new* audio: decide between (a) local batch embedding on the Mac with upload (fits the existing append-only archive pattern), or (b) packaging the merged model for Cloud Run inference. Default to (a) — cheaper, and the library grows slowly.
- Update the eval harness to run against both versions in CI so future changes are always compared.
- Write `finetune/RUNBOOK.md`: how to retrain when the library grows, how to roll back, where checkpoints live.

**Exit criteria:** A/B flag works; rollback tested; runbook reviewed.

---

## Suggested repo layout

```
echolocate/
  finetune/
    pyproject.toml / uv.lock
    MODEL_CARD.md
    BASELINE.md
    RUNBOOK.md
    src/
      embed.py          # local inference, parity-tested
      build_dataset.py  # captions + chunks + splits
      train.py          # LoRA contrastive training
      evaluate.py       # wraps existing eval suite
    data/               # manifests only; audio stays in place
    results/            # baseline_*.json, run logs, reports
    checkpoints/        # LoRA adapters (gitignored)
```

## Open questions — resolved

1. **CLAP checkpoint:** `laion/clap-htsat-unfused` @ `8fa0f1c6…` (see `MODEL_CARD.md`).
2. **Eval ground truth / holdout:** Echoes relevance labels → `qrels_2026-07-14.parquet`; the 238
   judged FMA tracks are held out of training (Phase 2 `holdout` split).
3. **MERT untouched:** yes — CLAP only, one variable at a time.
4. **Local LLM:** Ollama `qwen3:30b-a3b` at `localhost:11434` (`captions_llm.py`).
5. **Training domain:** FMA only (no library/Discogs/Wire), decided 2026-07-16.
6. **Splits:** FMA official `set.split`, hardened with the connected-components leakage repair.
