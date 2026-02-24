# Rewrite Vector Service in Rust

## Context

The vector service (`vector/`) was recently optimized by replacing PyTorch with ONNX for the CLAP text encoder. The remaining cold start bottleneck is Python itself — interpreter startup, uvicorn init, and the overhead of Python's runtime. Rewriting in Rust eliminates all of this while also giving us faster request handling (no GIL, native concurrency).

The service is a good candidate: self-contained, stateless reads only, clear HTTP API boundary, and the MCP servers consume it purely over HTTP — so the port is invisible to upstream clients.

## Architecture

New `vector-rs/` directory alongside existing `vector/`. Parallel deployment as `cloud-crate-vector-rs` on Cloud Run, then swap the MCP `VECTOR_SERVICE_URL` once validated.

### Tech stack
- **HTTP**: axum + tokio
- **DuckDB**: `duckdb` crate (bundled feature, compiles from C source)
- **ONNX**: `ort` crate + `tokenizers` crate (native Rust — same lib Python wraps)
- **GCS streaming**: `google-cloud-storage` crate
- **Gemini**: `reqwest` + `google-cloud-auth` (REST API, no heavy SDK)
- **CORS**: `tower-http`

### Project structure
```
vector-rs/
  Cargo.toml
  src/
    main.rs              # tokio main, AppState, Router
    config.rs            # env var loading
    db.rs                # DuckDB connection factory
    models.rs            # serde request/response structs
    error.rs             # AppError -> HTTP response
    handlers/
      health.rs          # GET /
      tracks.rs          # GET /tracks, /similar, /dissimilar
      search.rs          # GET /search, POST /vector-search
      semantic.rs        # POST /semantic-search
      stream.rs          # GET /stream/{track_id}
      interpolate.rs     # POST /interpolate
      playlist.rs        # POST /interpolate/playlist
    interpolation/
      math.rs            # slerp, de_casteljau_slerp, get_midpoint
      greedy_walk.rs
      recursive.rs
      bezier.rs
    clap_onnx.rs         # ONNX session + tokenizer
    gemini.rs            # Gemini REST client
    gcs.rs               # GCS blob streaming
  Dockerfile             # 3-stage: Python ONNX export -> Rust build -> minimal runtime
  deploy.sh
```

### Shared state (`AppState`)
```rust
#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub db_path: Arc<String>,        // DuckDB connections opened per-request (not pooled)
    pub onnx: Arc<ClapOnnxModel>,    // ort::Session is Send+Sync, no Mutex needed
    pub gemini: Arc<Option<GeminiClient>>,
    pub gcs: Arc<GcsClient>,
}
```

DuckDB connections are opened per-request (matching Python behavior) since `Connection` is not `Send`. Each connection runs `LOAD vss;` (extension pre-installed at build time).

## Key technical decisions

### DuckDB list parameter binding
The greedy walk query uses `UNNEST(?)` with a visited ID set. The duckdb-rs crate doesn't support `Vec<String>` via `ToSql`. **Solution**: match what the Python code already does — fetch top 50 neighborhood candidates, filter visited IDs and artists in Rust. This avoids the UNNEST binding entirely and is functionally identical.

### VSS extension
Pre-install during Docker build (download DuckDB CLI, run `INSTALL vss`, copy extension dir). Runtime only needs `LOAD vss` per connection.

### Vec<f32> binding for cosine similarity
Pass vectors via the `duckdb::types::Value` enum (round-trip: read as Value, re-bind as Value). Spike this early.

### Dockerfile (3-stage)
1. **Python exporter**: same as current — runs `export_clap_text.py` to produce ONNX model
2. **Rust builder**: `rust:1.82-slim-bookworm`, builds release binary with `cargo-chef` for layer caching
3. **Runtime**: `debian:bookworm-slim`, copies ONNX model + Rust binary + libonnxruntime

### Gemini auth
Use `google-cloud-auth` crate for ADC (workload identity on Cloud Run). Call Vertex AI REST endpoint directly with `reqwest`. Graceful fallback if `GCP_PROJECT_ID` not set.

## Implementation phases

### Phase 1: Scaffold + spikes
- Init Cargo project, wire axum + AppState
- Spike DuckDB `FLOAT[768]` parameter binding
- Spike VSS extension load in read-only mode
- Implement `GET /` health check

### Phase 2: Core read endpoints
- `GET /tracks` (list/sample)
- `GET /search` (text ILIKE)
- `GET /tracks/{id}/similar` and `/dissimilar`
- `POST /vector-search`

### Phase 3: ONNX + semantic search
- `ClapOnnxModel` (ort session + tokenizers)
- `GeminiClient` (reqwest + google-cloud-auth)
- `POST /semantic-search`

### Phase 4: Interpolation
- Port math module (slerp, de_casteljau_slerp)
- `POST /interpolate` (simple midpoint)
- `POST /interpolate/playlist` (greedy walk, recursive bisection, bezier)

### Phase 5: GCS streaming + Dockerfile
- `GET /stream/{track_id}`
- 3-stage Dockerfile with cargo-chef
- `deploy.sh` for `cloud-crate-vector-rs`

### Phase 6: Validation + cutover
- Run `verify_service.py` against both services
- Parity test: same inputs -> same outputs (within tolerance for similarity scores)
- Swap `VECTOR_SERVICE_URL` in MCP servers
- Delete Python service after observation period

## Files to create
- `vector-rs/Cargo.toml`
- `vector-rs/src/**` (all modules listed above)
- `vector-rs/Dockerfile`
- `vector-rs/deploy.sh`

## Files to reference (not modify)
- `vector/main.py` — source of truth for all endpoint behavior
- `vector/export_clap_text.py` — reused in Dockerfile Stage 1
- `vector/deploy.sh` — Cloud Run flags to preserve
- `mcp/main.py` — confirms expected JSON response shapes

## Verification
1. Spike DuckDB float array binding locally before full implementation
2. `cargo test` for interpolation math (slerp, depth calc)
3. `docker build` the 3-stage Dockerfile locally
4. Deploy as `cloud-crate-vector-rs`, run `verify_service.py` against it
5. Compare responses from Python and Rust services for same inputs
6. Check Cloud Run cold start time in logs
