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

This builds the Docker image, mounts your local database read-only, and starts the service on port 8000. Override defaults with environment variables:

```bash
PORT=9000 DB_PATH=/path/to/cloudcrate.duckdb ./run-local.sh
```

Defaults: `PORT=8000`, `DB_PATH=../data/cloudcrate.duckdb` (relative to repo root).

### Native

Requires `libduckdb` v1.2.2 and `libonnxruntime` v1.23.0 on your library path, plus a CLAP ONNX model directory (generate with `python vector/export_clap_text.py`).

```bash
cargo build --release
DB_PATH=./cloudcrate.duckdb CLAP_ONNX_DIR=./clap_text_onnx PORT=8000 cargo run
```

## Docker Build

The Dockerfile is a 3-stage build that must be run from the **repo root** (needs access to `vector/` for the ONNX export):

```bash
docker build -f vector-rs/Dockerfile -t cloud-crate-vector-rs .
```

**Stages:**
1. **Python exporter** — runs `export_clap_text.py` to produce the ONNX model + tokenizer
2. **Rust builder** — downloads pre-built `libduckdb`, compiles the binary with cargo-chef for layer caching
3. **Runtime** — `debian:bookworm-slim` with just the binary, ONNX model, and shared libraries

## Deployment

```bash
cd vector-rs && ./deploy.sh
```

Deploys as `cloud-crate-vector-rs` on Cloud Run alongside the existing Python service. Uses the same GCS-mounted DuckDB database.

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
| `DB_PATH` | `cloudcrate.duckdb` | Path to DuckDB database file |
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
