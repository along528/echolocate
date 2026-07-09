# vector-rs

Rust rewrite of the Cloud Crate vector search service. Drop-in replacement for `vector/` — same HTTP API, same DuckDB database, same ONNX model.

## Why Rust?

The Python vector service spent most of its cold start time on interpreter startup, uvicorn init, and runtime overhead. Rust eliminates all of that while giving us faster request handling (no GIL, native concurrency).

## Architecture

- **HTTP**: axum + tokio
- **DuckDB**: `duckdb` crate (links against pre-built `libduckdb`)
- **ONNX**: `ort` crate + `tokenizers` crate for [CLAP](https://arxiv.org/abs/2206.04769) text-to-audio embeddings
- **GCS**: `google-cloud-storage` crate for audio streaming
- **Gemini**: `reqwest` + `google-cloud-auth` for query enhancement via Vertex AI

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/tracks` | List/sample tracks |
| GET | `/tracks/{id}/similar` | Find similar tracks by vector |
| GET | `/tracks/{id}/dissimilar` | Find dissimilar tracks by vector |
| GET | `/tracks/{id}/vibes` | Live vibe chips: top-k cosine between the track's `v_clap` and a fixed vocabulary (`vibes.txt`) embedded at startup — no DB column. Params `k` (default 3), `min_score` (default 0.25). Returns `ready:false` while anchors warm up. `POST /tracks/by-ids` accepts `include_vibes:true` for batches. |
| GET | `/search` | Text search (ILIKE) by artist, album, title |
| POST | `/vector-search` | Search by raw 768-dim vector |
| POST | `/semantic-search` | Search by text description (CLAP + optional Gemini enhancement) |
| POST | `/interpolate` | Find tracks between two endpoints (midpoint) |
| POST | `/interpolate/playlist` | Generate a playlist path (greedy walk, recursive bisection, or Bezier) |
| GET | `/stream/{track_id}` | Stream audio from GCS |

## Local Development

### Docker (recommended)

The easiest way to run locally — no need to install `libduckdb` or `libonnxruntime`:

```bash
cd vector-rs && ./run-local.sh
```

This builds the Docker image (with the baked index), mounts your local database directory read-only, and starts the service on port 8000. The baked index inside the image is used by default.

```bash
PORT=9000 ./run-local.sh
```

Defaults: `PORT=8000`. Requires `data/index.duckdb` to exist (see [Baked-Index Architecture](#baked-index-architecture)).

### Native

Requires `libduckdb` v1.2.2 and `libonnxruntime` v1.23.0 on your library path, plus a CLAP ONNX model directory (generate with `python vector/export_clap_text.py`).

```bash
cargo build --release
INDEX_DB_PATH=../data/index.duckdb CLAP_ONNX_DIR=./clap_text_onnx PORT=8000 cargo run
```

### Tests

Unit tests live next to the code (`src/interpolation/math.rs`, `src/vibes.rs`).
Integration tests (`tests/api/`) drive every HTTP endpoint through the real
Axum router (`tower::ServiceExt::oneshot`) against the committed sample index
(`testdata/sample_index.duckdb`) — no ports, no external services. The sample
index has random vectors, so they assert structure and invariants (sort order,
dedup, greedy-walk artist uniqueness), not semantic quality.

```bash
source scripts/dev-env.sh   # needs DUCKDB_LIB_DIR / LD_LIBRARY_PATH to build at all
cargo test
```

Tests that need the real CLAP ONNX model (semantic search, anchor embedding)
skip with a notice when `clap_text_onnx/` or the onnxruntime dylib is absent —
run with `-- --nocapture` to see skips.

## Dev Sandbox (remote / interactive development)

vector-rs is the hardest service to iterate on remotely: it needs a Rust
toolchain plus native `libduckdb`, `libonnxruntime` + the DuckDB `vss`
extension, the CLAP ONNX model, and *data*. The real index is ~1.4GB and the
full DB ~23GB (both gitignored), so a fresh sandbox can't build or query
anything out of the box. The dev-sandbox tooling fixes that with a tiny
**committed sample index** and one **provisioning script**, exposed through
three substrates.

### Sample index

`vector-rs/testdata/sample_index.duckdb` (~5MB, committed) is a 600-track
stand-in with the *exact* baked-index schema (`tracks_library` + `tracks_fma` +
the `tracks` union view, `v_mid`/`v_clap`/`x`/`y`/`duration`). Its vectors are
synthetic (meaningless similarity, but every endpoint returns real JSON), so it
verifies API *shape* and wiring, not real results. Regenerate it — or make a
realistic subset from the full DB — with:

```bash
python embeddings/generate_sample_index.py                 # synthetic (default)
python embeddings/generate_sample_index.py --source ../data/cloudcrate.duckdb --n 500
```

### Provisioning

> For when/by-whom each dev-sandbox script runs (the SessionStart hook,
> `publish-dev-artifacts.sh`, sample regeneration, etc.), see
> [`scripts/README.md`](scripts/README.md).

`vector-rs/scripts/setup-dev.sh` is idempotent and installs everything:
`libduckdb` (required to compile), `onnxruntime` + `vss` + the CLAP model
(required only to *run* — `ort` uses load-dynamic, so `cargo build`/`cargo test`
don't need onnxruntime). Then:

```bash
bash vector-rs/scripts/setup-dev.sh
cd vector-rs && source scripts/dev-env.sh
cargo test                      # interpolation unit tests
cargo run                       # serves the sample index on :8000
curl localhost:8000/ ; curl 'localhost:8000/search?query=blue&source=library'
```

To confirm `vss`/HNSW actually loaded, hit the vector-backed routes too. Their
shapes are easy to guess wrong: `similar` takes the id as a **path param**, and
`semantic-search` / `interpolate` are **POSTs** (fields `track_id_1` /
`track_id_2`, not `id`):

```bash
curl 'localhost:8000/tracks/<id>/similar'
curl -X POST localhost:8000/semantic-search -H 'content-type: application/json' \
  -d '{"query":"dreamy synth","limit":5}'
curl -X POST localhost:8000/interpolate -H 'content-type: application/json' \
  -d '{"track_id_1":"<id>","track_id_2":"<id>","limit":5}'
```

**Stopping the server:** the compiled binary's process name is
`cloud-crate-vector` — **hyphens**, not `cloud_crate_vector`. `pkill`/`pgrep` on
the underscore form matches nothing (and can match your own grep). Use
`pkill -f cloud-crate-vector` or `lsof -ti:8000 | xargs kill`.

**Egress requirements.** The provisioning fetches from these hosts — a remote
sandbox's network policy must allow them (see
[Claude Code on the web docs](https://code.claude.com/docs/en/claude-code-on-the-web)):

| Host | For |
|------|-----|
| `storage.googleapis.com` | libduckdb, onnxruntime, `vss`, and the CLAP model — all public objects, no auth needed — from `gs://cloud-crate-vector-db/dev-artifacts/`, tried first for all four |
| `github.com` + `objects.githubusercontent.com` | fallback when GCS has no mirror: libduckdb, onnxruntime, duckdb CLI, `ant` CLI release assets |
| `extensions.duckdb.org` | fallback for the `vss` extension when GCS has no mirror (also needed at service runtime for `LOAD vss`) |

**Claude Code on the web additionally scopes `github.com` per repo owner, not
just per host.** A session tied to this project can only reach `github.com`
paths under this repo's owner — `github.com/duckdb/duckdb` and
`github.com/microsoft/onnxruntime` 403 there unconditionally, and the
`add_repo` tool can't add a cross-owner repo to widen that (cross-tier adds
are rejected); the same sessions frequently can't reach
`extensions.duckdb.org` either. Allowlisting a host in the environment's
network policy does not fix the GitHub case. So `setup-dev.sh` fetches all
four native deps from a **public, unauthenticated** GCS URL first: no
`gcloud`, no ADC, works even in a sandbox where `gcloud` isn't installed at
all (`publish-dev-artifacts.sh` sets `--predefined-acl=publicRead` on each of
the four dev-artifacts objects). This is safe because all four are unmodified
re-exports/rebuilds of public open-source artifacts, not project data — see
the header comments in `setup-dev.sh` / `publish-dev-artifacts.sh` for the
per-artifact provenance. Nothing else in this bucket is public — it also
serves the private audio corpus vector-rs streams in production. GitHub /
`extensions.duckdb.org` fallback still works fine on substrates without the
cross-owner restriction (a laptop, `Dockerfile.dev`, generic CI).

An actionable one-time checklist for the Claude Code on the web environment lives
in [`.claude/README.md`](../.claude/README.md#one-time-environment-setup-network-policy).

**Publishing the GCS dev artifacts (maintainer, one-time).** So sandboxes get the
CLAP model + `vss` from GCS instead of running the torch export or hitting the
DuckDB extension repo:

```bash
bash vector-rs/scripts/publish-dev-artifacts.sh   # needs storage.objectAdmin on the bucket
```

This uploads to the exact paths `setup-dev.sh` fetches
(`.../dev-artifacts/clap_text_onnx/…`, `.../dev-artifacts/vss.duckdb_extension`).

### Substrate 1 — Claude Code on the web

`.claude/hooks/session-start.sh` (registered in `.claude/settings.json`) runs
`setup-dev.sh` on every web session and persists the build env via
`$CLAUDE_ENV_FILE`, so a session boots ready to build/run/query. It degrades
gracefully: if a required host is blocked it reports which one and lets the
session start anyway.

### Substrate 2 — dev container

`vector-rs/Dockerfile.dev` bakes the whole toolchain + sample index + CLAP model
(source is bind-mounted, not copied). `.devcontainer/devcontainer.json` uses it
for VS Code / Codespaces.

```bash
docker build -f vector-rs/Dockerfile.dev -t vector-rs-dev .
docker run --rm -it -p 8000:8000 -v "$PWD":/workspace vector-rs-dev
```

### Substrate 3 — PR previews

`.github/workflows/vector-rs-ci.yml` gates PRs on `cargo build` + `cargo test`.
`vector-rs-pr-preview.yml` builds an image baking the **sample** index (via the
`INDEX_SRC` build arg + `vector-rs/cloudbuild.yaml`) and deploys a
`--no-traffic --tag pr<N>` revision of `cloud-crate-vector-rs` — a live backend
you can curl — commenting the URL on the PR; `vector-rs-pr-cleanup.yml` tears it
down on close. Auth reuses the existing WIF setup (`.github/setup-wif.sh`); the
`gha-sonar-deployer` SA already has `run.developer` + `cloudbuild` +
`storage.admin`, which cover the vector-rs service too. Confirm before relying on
previews:

```bash
bash vector-rs/scripts/verify-deployer-sa.sh   # read-only IAM check; no changes
```

### Substrate 3.1 — production deploy on main

`.github/workflows/vector-rs-deploy.yml` deploys the production serving revision
(100% traffic) on every merge to main touching `vector-rs/**` — the CI-automated
equivalent of running `vector-rs/deploy.sh` from a laptop (which stays as the
manual fallback). It reuses the same WIF auth and `vector-rs/cloudbuild.yaml` as
the preview, but bakes the **full** production index and applies the production
Cloud Run sizing/env from `deploy.sh` (8Gi / 2 CPU / `--no-cpu-throttling`).

Because the ~1.4GB `data/index.duckdb` is gitignored (not in the repo), it can't
be built from source in CI like sonar. Instead, publish it once — and again
whenever it's regenerated — to a **private** GCS object, which the workflow fetches
and bakes in:

```bash
bash vector-rs/scripts/publish-index.sh   # → gs://cloud-crate-vector-db/vector-rs-index/index.duckdb
```

A cheap `check` job gates the expensive build: it compares this commit's SHA and
the GCS index **generation** against the `GIT_SHA` / `INDEX_VERSION` the serving
revision already carries, and skips the build+deploy when neither changed — so
`workflow_dispatch` reruns (used to pick up an index-only refresh, which no code
push would trigger) are idempotent.

The Managed Agents self-hosted worker and the GKE scale-up are added in later
parts of this series.

## Baked-Index Architecture

The full `cloudcrate.duckdb` (~23GB) is too large for fast cold starts on Cloud Run — GCS FUSE random I/O for HNSW index traversal caused ~250s cold starts. The solution: bake a stripped index DB into the Docker image.

**How it works:**
- `embeddings/generate_index_db.py` builds `data/index.duckdb` (~1.4GB) from the full DB, keeping all metadata + `v_mid` + `v_clap` with [HNSW](https://arxiv.org/abs/1603.09320) indexes, but dropping `v_intro` and `v_outro` (unused by this service).
- The index DB is `COPY`'d into the Docker image as its own layer.
- Cloud Run gen2's container image streaming lazy-loads only the needed blocks from the registry — no FUSE, no full download.
- `INDEX_DB_PATH` env var points to the baked index; falls back to `DB_PATH` when unset (backward compatible).
- No GCS FUSE mount needed — audio streaming uses the GCS client API directly.

**Generating the index DB:**
```bash
cd embeddings && python generate_index_db.py
```

## Docker Build

The Dockerfile is a 3-stage build that must be run from the **repo root** (needs access to `vector/` for the ONNX export and `data/` for the baked index):

```bash
docker build -f vector-rs/Dockerfile -t cloud-crate-vector-rs .
```

**Stages:**
1. **Python exporter** — runs `export_clap_text.py` to produce the ONNX model + tokenizer
2. **Rust builder** — downloads pre-built `libduckdb`, compiles the binary with cargo-chef for layer caching
3. **Runtime** — `debian:bookworm-slim` with the binary, ONNX model, baked index DB, and shared libraries

**Layer caching:** The baked index (~1.4GB) is a separate layer placed before the binary. Code changes only rebuild the binary layer; the index layer is cached unless `data/index.duckdb` changes.

## Deployment

Production deploys run automatically on merge to main via
[`vector-rs-deploy.yml`](#substrate-31--production-deploy-on-main). To deploy by
hand (the manual fallback), from a machine that has the local `data/index.duckdb`:

```bash
cd vector-rs && ./deploy.sh
```

Deploys as `cloud-crate-vector-rs` on Cloud Run with the baked index. No GCS FUSE mount — audio streaming uses the GCS client API directly. Uses `--no-cpu-throttling` for consistent performance.

## Validation

```bash
# Run the verification script against the Rust service
python vector/verify_service.py https://cloud-crate-vector-rs-ie7zxu4hbq-uc.a.run.app

# Compare against the Python service
python vector/verify_service.py https://cloud-crate-vector-ie7zxu4hbq-uc.a.run.app
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INDEX_DB_PATH` | — | Path to baked index DB (takes precedence over `DB_PATH`) |
| `DB_PATH` | `cloudcrate.duckdb` | Path to full DuckDB database (fallback) |
| `PORT` | `8080` | HTTP listen port |
| `GCP_PROJECT_ID` | — | Enables Gemini query enhancement |
| `GCP_LOCATION` | `us-central1` | Vertex AI region |
| `CLAP_ONNX_DIR` | `/app/clap_text_onnx` | Directory containing `clap_text.onnx` and `tokenizer.json` |
| `CORS_ALLOW_ORIGINS` | — | Comma-separated origins (or `*`) |
| `GCS_BUCKET_NAME` | `cloud-crate-vector-db` | GCS bucket for audio streaming |
| `GCS_AUDIO_PREFIX` | `fma/fma_full/fma_full` | Path prefix within the bucket |
| `ORT_DYLIB_PATH` | — | Path to `libonnxruntime.so` (for `load-dynamic` feature) |

## Known Limitations

- DuckDB's Rust crate (v1.4.4) does not support binding list/array values as query parameters. Vectors are inlined as SQL literals instead.
