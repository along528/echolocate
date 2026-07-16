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

## Phase 2 — Dataset construction

**Objective:** Build contrastive (audio, text) pairs from data the owner already has, with leakage-safe splits.

Text sources, in priority order:
1. **Discogs metadata** (via Record Crate export or Discogs data dump for owned releases): genre, style tags, artist, year, label. Template into natural-language captions ("free jazz with fire-music tenor saxophone, ESP-Disk, 1966").
2. **Wire review language**: the owner maintains a markdown tracking doc of Wire-reviewed albums. Where a library album matches a tracked review, use the descriptive vocabulary (map review adjectives to caption templates — do **not** reproduce review sentences verbatim; generate paraphrased captions, both for copyright hygiene and to avoid overfitting to editorial prose style).
3. **Synthetic captions**: use a local LLM (Ollama/LM Studio, OpenAI-compatible endpoint on localhost) to generate 3–5 caption variants per track from the structured metadata. Log all generations.

Audio processing:
- Chunk tracks into the model's native window (typically 10s for CLAP). Sample N chunks per track (skip first/last 5% to avoid silence/fade). Each chunk inherits the track's captions.
- Hard negatives: within-genre negatives matter most for this library (distinguishing free jazz from spiritual jazz is the whole point). Build a negative-sampling map keyed on Discogs style tags.

Splits:
- **Split by album, never by chunk or track.** Target 80/10/10 train/val/test. Verify no artist appears in both train and test where the library allows (best-effort for prolific artists; document exceptions).
- Ensure the Phase 0 eval query set's judged tracks land in the test split, or exclude them from training entirely.

Deliverables: `finetune/data/` builder scripts, a `dataset_stats.md` (pair counts, genre distribution, caption length stats), and a manifest Parquet.

**Exit criteria:** ≥ 5k audio-caption pairs (more is fine), stats reviewed, leakage check script passes.
⛔ **Checkpoint: human spot-checks ~30 random caption/audio pairs for quality.**

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

## Open questions for the human (answer before Phase 2)

1. Which exact CLAP checkpoint is production using (HF repo + revision)?
2. Where does the eval query set's ground truth come from, and is it safe to hold out those tracks from training?
3. Should MERT embeddings stay untouched for now (recommended: yes — one variable at a time)?
4. Preferred local LLM endpoint for synthetic captions (Ollama model name / port)?
