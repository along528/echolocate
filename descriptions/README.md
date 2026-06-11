# Descriptions — audio → text pipeline

Generate human-readable descriptions of every track from its audio: the
*reverse* of what EchoLocate does today. The existing CLAP path goes
**text → audio** (embed a query, retrieve nearest tracks); this pipeline goes
**audio → text** (structured vibe tags + a free-text caption per track), using
the embeddings already sitting in the database plus Gemini's native audio
understanding.

The output is two new columns on the `tracks_*` tables:

| Column | Type | Source |
|---|---|---|
| `tags` | `VARCHAR` (JSON array of strings) | Tier 1 — zero-shot reverse CLAP |
| `description` | `VARCHAR` (one-sentence caption) | Tier 2 — Gemini captioning, CLAP-verified |

Both are cheap to serve (plain columns, no model at query time) and unlock:
per-track vibe chips in sonar (the deferred `sonar/TODO.md` item), a
now-playing blurb, descriptions as *searchable text* (improving `text_search`),
and a future `echolocate_describe` MCP tool.

---

## Architecture

```
                         ┌────────────────────────────────────────────┐
                         │           data/cloudcrate.duckdb           │
                         │   v_clap FLOAT[512]  (already computed)    │
                         └───────┬───────────────────────┬────────────┘
                                 │                       │
              Tier 1             │                       │            Tier 2
   ┌─────────────────────────────▼──────┐   ┌────────────▼─────────────────────┐
   │ generate_tags.py                   │   │ generate_captions.py             │
   │  vocabulary.json → CLAP text       │   │  audio snippet → Gemini 2.0      │
   │  anchors; score every v_clap;      │   │  Flash (Vertex AI) → caption +   │
   │  per-tag z-score calibration;      │   │  vibes JSON                      │
   │  top-k per category                │   └────────────┬─────────────────────┘
   └─────────────────┬──────────────────┘                │
                     │                       ┌───────────▼──────────────────────┐
                     │                       │ evaluate_captions.py             │
                     │                       │  caption → CLAP text embedding   │
                     │                       │  → retrieve → rank of source     │
                     │                       │  track (cycle consistency)       │
                     │                       └───────────┬──────────────────────┘
                     │                                   │
        data/descriptions/tags.jsonl     data/descriptions/captions.jsonl
                     │                   data/descriptions/caption_eval.jsonl
                     └───────────────┬───────────────────┘
                                     ▼
                        ┌──────────────────────────┐
                        │ load_descriptions.py     │
                        │  ALTER + UPDATE tags,    │
                        │  description columns     │
                        └────────────┬─────────────┘
                                     ▼
                  embeddings/generate_index_db.py (carries the
                  new columns into the baked index automatically)
```

Generation writes JSONL artifacts; loading into DuckDB is a separate step.
This matches the existing `embeddings/` convention (JSONL → `generate_db.py`)
and means model-heavy steps are resumable and re-runnable without touching
the DB.

---

## Tier 1 — Zero-shot reverse CLAP (`generate_tags.py`)

CLAP is a *joint* audio/text embedding space, so it can run backwards: embed a
curated vocabulary of descriptive phrases with the CLAP **text** encoder and
score every track's existing `v_clap` against them. No audio is reprocessed —
this is pure linear algebra over columns already in the DB.

### The modality gap (why naive cosine fails)

CLAP audio and text embeddings occupy *different cones* of the space — audio
embeddings cluster together, text embeddings cluster elsewhere. Raw cosine
similarity is therefore not comparable **across** anchors: some phrases sit
systematically closer to the entire audio cone and would win on every track.

The fix is per-tag calibration: for each tag, take its raw cosine scores
across the whole corpus and z-score them (`z = (s - μ_tag) / σ_tag`). A tag is
only assigned when a track is unusually close to that tag *relative to how
close all tracks are to it*. Selection is then top-k by z-score within each
category, gated by a per-category `min_z` threshold (both configurable in
`vocabulary.json`).

### Vocabulary (`vocabulary.json`)

Six categories, each with its own `top_k` / `min_z` and 1–3 CLAP prompts per
tag (multiple prompts are averaged, same trick as `generate_projection.py`'s
clap-axes anchors):

| Category | Examples | top_k |
|---|---|---|
| `genre` | rock, jazz, house, ambient, shoegaze… | 2 |
| `mood` | melancholic, euphoric, eerie, nostalgic… | 2 |
| `energy` | slow ballad, driving and fast, danceable… | 1 |
| `instrumentation` | acoustic guitar, synthesizer, horns… | 3 |
| `vocals` | female vocals, rapping, instrumental… | 1 |
| `production` | lo-fi and gritty, reverb-drenched, minimal… | 2 |

The vocabulary is data, not code — edit phrases, re-run, inspect the printed
per-tag coverage stats (fraction of corpus assigned, top exemplar tracks), and
iterate. Tags whose coverage is ~0% or ~100% are mis-anchored and should be
reworded.

### Output

`data/descriptions/tags.jsonl` — one line per track:

```json
{"id": "fma_12345", "table": "tracks_fma",
 "tags": ["house", "hypnotic", "danceable", "drum machine", "synthesizer", "instrumental"],
 "tags_by_category": {"genre": ["house"], "mood": ["hypnotic"], "...": "..."},
 "tag_scores": {"house": {"z": 2.31, "cos": 0.41}, "...": "..."}}
```

Plus `data/descriptions/tag_anchors.json` (the text-anchor embeddings, for
reproducibility — same pattern as `projection_anchors.json`).

---

## Tier 2 — Gemini captioning + CLAP verification

### Generation (`generate_captions.py`)

Sends an audio snippet (default: 30 s from 30 s in, 16 kHz mono WAV — well
under inline-payload limits, ≈960 audio tokens) to **Gemini 2.0 Flash on
Vertex AI** — the same model/endpoint `vector-rs/src/gemini.rs` already uses
for query expansion — and asks for structured JSON:

```json
{"caption": "Hazy mid-tempo dream pop with reverb-washed female vocals,
             chorused guitars and a soft motorik drum groove.",
 "vibes": ["dreamy", "hazy", "reverb-washed"]}
```

Design decisions:

- **Audio only, no metadata.** By default the prompt contains *no* title /
  artist / album, so the caption describes what the clip *sounds like* rather
  than Gemini's textual priors about the artist (`--include-metadata` exists
  for comparison experiments).
- **Caption style matches the CLAP query-expansion style** (one technical
  sentence ≤ 30 words: instrumentation, mood, texture, tempo). This is
  deliberate: captions in that register embed well with CLAP's text encoder,
  which both the verification step and future text→audio search rely on.
- **Resumable**: already-captioned ids are skipped on re-run (JSONL append,
  same convention as `generate_clap.py`).
- Auth via Application Default Credentials; retries with exponential backoff
  on 429/5xx.

Cost: Gemini 2.0 Flash audio input is ~32 tokens/sec, so a 30 s clip plus
prompt is ≈1k input tokens and ~60 output tokens. At current Flash pricing
the full corpus (~10⁵ tracks) is on the order of **$10–20 total** — check
current Vertex pricing before a full run, and do a `--limit 200` pilot first.

### Verification (`evaluate_captions.py`) — cycle consistency

A caption is only good if it *round-trips*: embed the generated caption with
the CLAP text encoder, retrieve against every `v_clap` in the corpus, and
record the **rank of the source track** in its own caption's result list. No
human labels needed.

Reported metrics:

- `recall@1 / @5 / @10 / @100` — fraction of tracks that rank in the top-k
  of their own caption's retrieval
- median rank and mean reciprocal rank (MRR)
- the worst-N offenders, printed with their captions, for manual audit

Per-track results go to `data/descriptions/caption_eval.jsonl`
(`{"id", "cc_rank", "cc_sim"}`) and a summary report to
`data/descriptions/caption_eval_report.md`. The loader uses `cc_rank` to
gate which captions ship (default: `cc_rank ≤ 100`); failures stay in the
artifacts so they can be regenerated (different snippet offset, longer clip)
rather than silently shipped.

Baselines to sanity-check against (the report includes the random-rank
expectation): a random caption would rank the source track at ~N/2 on
average. Tier 1 tags joined into a pseudo-caption can serve as a second
baseline — Gemini captions should beat it.

---

## Runbook

All steps run locally against the **full** DB (like `generate_projection.py`),
before `generate_index_db.py`:

```bash
source .venv/bin/activate
cd descriptions
pip install -r requirements.txt

# Tier 1 — zero-shot tags (CPU, minutes)
python generate_tags.py                      # writes data/descriptions/tags.jsonl
python generate_tags.py --stats              # vocabulary coverage report only

# Tier 2 — pilot, then full run
export GOOGLE_CLOUD_PROJECT=<project-id>
python generate_captions.py --limit 200      # pilot
python evaluate_captions.py                  # cycle-consistency report
#   → iterate on prompt/snippet if recall@10 is poor, then:
python generate_captions.py                  # full corpus (resumable)
python evaluate_captions.py

# Load into the DB, then rebuild the baked index
python load_descriptions.py                  # tags + verified captions → columns
cd ../embeddings
python generate_index_db.py                  # picks up tags/description automatically
cd ../vector-rs && ./deploy.sh
```

`load_descriptions.py` is idempotent (ALTER IF missing + UPDATE by id) and
safe to re-run as artifacts improve.

---

## Integration plan (follow-up PRs)

Deliberately **not** in this PR — the pipeline and its artifacts come first so
quality is validated before anything ships to users.

1. **vector-rs**: add `tags: Option<Vec<String>>` (parsed from the JSON
   column) and `description: Option<String>` to `TrackResponse` /
   `SearchResult` in `src/models.rs`, plumb through the row mappers. The
   columns are optional, so the service keeps working against an old index DB.
2. **sonar**: per-track vibe chips (list rows, tooltip, now-playing) — the
   exact deferred item in `sonar/TODO.md`, now with a backend source; caption
   as a now-playing blurb.
3. **MCP**: new `echolocate_describe` tool returning tags + description for a
   track id; include `description` in existing tool responses so playlist
   results are self-explaining.
4. **Search**: include `description` in `text_search`'s matchable fields.

## Tier 3 roadmap (future)

- **Supervised genre probe**: FMA metadata ships genre labels for every track
  — train a linear/MLP probe from `v_mid` (768-d) or `v_clap` (512-d) to the
  FMA genre taxonomy. Calibrated probabilities instead of zero-shot guesses;
  evaluated against held-out FMA labels; transfers to the personal library.
  The Tier 2 eval harness doubles as its regression suite.
- **Distilled captioner** (ClipCap-style): once 10–20k Gemini captions exist,
  train a small mapping network from the 512-d CLAP embedding to caption text
  so new tracks get described in the embedding pipeline for free, no API call.
- **Vocabulary expansion via captions**: mine frequent n-grams from verified
  captions to grow `vocabulary.json` with phrases that demonstrably live in
  the corpus.
