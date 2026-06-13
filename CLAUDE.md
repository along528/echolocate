# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EchoLocate is a music discovery system that exposes MCP (Model Context Protocol) tools for audio-based vector search. The system uses audio embeddings for "sonic" similarity search and playlist generation.

## Architecture

The project consists of these services:

1. **`mcp/`** - EchoLocate MCP server (Starlette/uvicorn)
   - OAuth2 authentication flow for MCP clients
   - Vector search proxy via `EchoLocate` class (connects to vector service)
   - 6 tools: `echolocate_*` (sample, similar, interpolate, generate_playlist, text_search, semantic_search)
   - Entry point: `mcp/main.py`

2. **`vector/`** - Vector search service (FastAPI) — legacy Python implementation
   - DuckDB with VSS extension for vector similarity search
   - CLAP model for semantic text-to-audio search (lazy-loaded)
   - Interpolation algorithms: greedy walk, SLERP, linear, Bezier curves
   - Mounted GCS bucket for database file in Cloud Run
   - Entry point: `vector/main.py`

3b. **`vector-rs/`** - Vector search service (Rust/Axum) — primary deployment
   - Same DuckDB/VSS stack, rewritten in Rust with Axum
   - **Baked-index architecture**: A stripped index DB (`data/index.duckdb`, ~1.4GB) containing only `v_mid` + `v_clap` + metadata is baked into the Docker image. Cloud Run streams container image blocks on demand, eliminating GCS FUSE cold-start latency.
   - `INDEX_DB_PATH` env var points to the baked index; falls back to `DB_PATH` (GCS mount) when unset
   - No GCS FUSE mount needed — audio streaming uses the GCS client API directly
   - Entry point: `vector-rs/src/main.rs`

4. **`sonar/`** - Sonar-map frontend (React + Vite) — map/list redesign
   - "Sonar map + list" UI: 2D embedding-space scatter (from track `x,y`) with Map⇄List toggle, vibe tagger, trail/playlist builder, now-playing card
   - Talks to the vector service via `VITE_VECTOR_API_URL`; deployed as its own Cloud Run service (`cloud-crate-sonar`) at `sonar.echolocate.app` (domain mapping, like `echoes/`), separate from `frontend/`
   - Map dot positions come from the `/map/backdrop` sample + per-result `x,y`; see `sonar/TODO.md` for deferred items

5. **`embeddings/`** - Audio embedding pipeline (local processing)
   - MERT model (`m-a-p/MERT-v1-95M`) for 768-dim audio embeddings
   - CLAP model for 512-dim text-matchable embeddings
   - Segments audio into intro/mid/outro (5s each)
   - Outputs JSONL which is then loaded into DuckDB

## Common Commands

**Always use the virtual environment for Python commands:**
```bash
source .venv/bin/activate
```

### Deployment
```bash
./deploy.sh                        # Deploy all services to Cloud Run
cd mcp && ./deploy.sh              # Deploy EchoLocate MCP server only
cd vector && ./deploy.sh           # Deploy vector service (Python) only
cd vector-rs && ./deploy.sh        # Deploy vector service (Rust) only — requires data/index.duckdb
cd frontend && ./deploy.sh         # Deploy legacy frontend only
cd sonar && ./deploy.sh            # Deploy sonar frontend (React) only — separate Cloud Run service
```

### Embedding Generation
```bash
cd embeddings
python generate_embeddings.py <directory_or_filelist> [limit]
python generate_clap.py        # Generate CLAP embeddings
python generate_db.py          # Build full DuckDB from JSONL files
python generate_projection.py  # Compute 2D sonar-map x,y columns; run before generate_index_db.py
                               #   --method clap-axes (interpretable) | pca | umap
                               #   --vector clap|mid  --normalize rank|minmax
                               #   sonar ships: --method pca --vector mid (projects the MERT v_mid
                               #   embedding used for interpolation; axes are not interpretable)
python generate_vibes.py       # Classify tracks into CLAP-anchored "vibe" tags -> vibes column;
                               #   run against the full DB before generate_index_db.py
                               #   --top-k N  --min-sim FLOAT
python generate_index_db.py    # Build stripped index DB from full DB (for baked-index deployment)
                               #   inherits the duration / x,y / vibes columns from the full DB
```

### Local Development
```bash
# EchoLocate MCP Server (port 8080)
cd mcp && python main.py

# Vector Service — Rust (port 8080)
cd vector-rs && INDEX_DB_PATH=../data/index.duckdb cargo run

# Vector Service — Python legacy (port 8000)
cd vector && uvicorn main:app --reload

# Sonar frontend — React + Vite (port 5180)
cd sonar && VITE_VECTOR_API_URL=<vector-url> npm run dev
```

### Verification
```bash
python vector/verify_service.py <VECTOR_URL>
python mcp/verify_auth.py <MCP_URL>
```

## Key Technical Details

### Vector Database Schema
The `tracks` table has columns:
- `id`: MD5 hash of artist|album|title
- `v_intro`, `v_mid`, `v_outro`: FLOAT[768] (MERT embeddings)
- `v_clap`: FLOAT[512] (CLAP embeddings for semantic search)
- `duration`: DOUBLE (track length in seconds; carried through from the embedding pipeline)
- `x`, `y`: DOUBLE (2D sonar-map coordinates from `generate_projection.py`, normalized [0,1]; NULL until that step runs)
- `vibes`: VARCHAR (JSON-array string of CLAP-classified vibe tags from `generate_vibes.py`; NULL until that step runs)
- HNSW indexes on `v_mid` (cosine) and `v_clap` (cosine) per source table

### Map Endpoints (vector-rs)
- `GET /map/backdrop?source=&n=` — random `{id,x,y}` sample for the dimmed sonar-map field
- `GET /map/nearest?x=&y=&source=` — the single globally-nearest track to a clicked
  coordinate (Euclidean distance in the normalized [0,1] projection space); powers the
  sonar frontend's "click empty space to probe the whole corpus" interaction

### Interpolation Methods
- **greedy_walk**: Graph traversal finding neighbors closest to target (default)
- **slerp**: Spherical linear interpolation on hypersphere
- **linear**: Simple vector averaging
- Bezier curves available when `steer_track_id` is provided

### MCP Tool Naming Convention
All tools are namespaced: `echolocate_*`

### Environment Variables
- MCP (EchoLocate): `MCP_AUTH_SECRET`, `MCP_JWT_SECRET`, `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`, `VECTOR_SERVICE_URL`
- Vector (Rust): `DB_PATH`, `INDEX_DB_PATH` (baked index, takes precedence over DB_PATH), `GCP_PROJECT_ID`, `CLAP_ONNX_DIR`, `CORS_ALLOW_ORIGINS`
- Vector (Python): `LIBRARY_VECTOR_URL`, `FMA_VECTOR_URL`, or legacy `VECTOR_SERVICE_URL`
- Secrets can be fetched from Google Secret Manager if `GOOGLE_CLOUD_PROJECT` is set

### Audio File Structure
Expected path format: `crate/<Source>/<Artist>/<Album>/<Title>.ext`
Metadata is parsed from directory structure.
