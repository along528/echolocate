# vector-rs

Rust rewrite of the Cloud Crate vector search service. Drop-in replacement for `vector/` — same HTTP API, same DuckDB database, same ONNX model.

## Why Rust?

The Python vector service spent most of its cold start time on interpreter startup, uvicorn init, and runtime overhead. Rust eliminates all of that while giving us faster request handling (no GIL, native concurrency).

## Architecture

- **HTTP**: axum + tokio
- **DuckDB**: `duckdb` crate (links against pre-built `libduckdb`)
- **ONNX**: `ort` crate + `tokenizers` crate for CLAP text-to-audio embeddings
- **GCS**: `google-cloud-storage` crate for audio streaming
- **Gemini**: `reqwest` + `google-cloud-auth` for query enhancement via Vertex AI

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/tracks` | List/sample tracks |
| GET | `/tracks/{id}/similar` | Find similar tracks by vector |
| GET | `/tracks/{id}/dissimilar` | Find dissimilar tracks by vector |
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

## Baked-Index Architecture

The full `cloudcrate.duckdb` (~23GB) is too large for fast cold starts on Cloud Run — GCS FUSE random I/O for HNSW index traversal caused ~250s cold starts. The solution: bake a stripped index DB into the Docker image.

**How it works:**
- `embeddings/generate_index_db.py` builds `data/index.duckdb` (~1.4GB) from the full DB, keeping all metadata + `v_mid` + `v_clap` with HNSW indexes, but dropping `v_intro` and `v_outro` (unused by this service).
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
