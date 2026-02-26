# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cloud Crate is a music library management and discovery system that exposes MCP (Model Context Protocol) tools for Apple Music, Discogs, and audio-based vector search. The system uses audio embeddings for "sonic" similarity search and playlist generation.

## Architecture

The project consists of four main services:

1. **`mcp/`** - EchoLocate MCP server (Starlette/uvicorn)
   - OAuth2 authentication flow for MCP clients
   - Vector search proxy via `EchoLocate` class (connects to vector service)
   - 6 tools: `echolocate_*` (sample, similar, interpolate, generate_playlist, text_search, semantic_search)
   - Entry point: `mcp/main.py`

2. **`mcp-discogs/`** - Dedicated Discogs MCP server (Starlette/uvicorn)
   - OAuth2 authentication flow (password-based, same pattern as `mcp/`)
   - Discogs integration via `RecordCrate` class (search, wantlist, collection management)
   - 9 tools: `discogs_*` (search, get_versions, get_release, get_wantlist, add_to_wantlist, get_collection_folders, get_collection, add_to_collection, move_release)
   - Entry point: `mcp-discogs/main.py`

3. **`vector/`** - Vector search service (FastAPI) — legacy Python implementation
   - DuckDB with VSS extension for vector similarity search
   - CLAP model for semantic text-to-audio search (lazy-loaded)
   - Interpolation algorithms: greedy walk, SLERP, linear, Bezier curves
   - Mounted GCS bucket for database file in Cloud Run
   - Entry point: `vector/main.py`

3b. **`vector-rs/`** - Vector search service (Rust/Axum) — primary deployment
   - Same DuckDB/VSS stack, rewritten in Rust with Axum
   - **Baked-index architecture**: A stripped index DB (`data/index.duckdb`, ~1.4GB) containing only `v_mid` + `v_clap` + metadata is baked into the Docker image. Cloud Run streams container image blocks on demand, eliminating GCS FUSE cold-start latency.
   - `INDEX_DB_PATH` env var points to the baked index; falls back to `DB_PATH` (GCS mount) when unset
   - GCS mount retained at `/data/cloudcrate.duckdb` as fallback with full vectors (`v_intro`, `v_outro`)
   - Entry point: `vector-rs/src/main.rs`

4. **`mcp-apple/`** - Dedicated Apple Music MCP server (Starlette/uvicorn)
   - Shared app-level `MCP_CLIENT_ID`/`MCP_CLIENT_SECRET` (all users configure the same values)
   - Self-service registration: users sign in with Apple Music via MusicKit.js during `/authorize`
   - User identity = SHA-256 hash of Apple Music user token, stored in Firestore (`cloud_crate_users/{user_id}`)
   - `contextvars.ContextVar` threads user identity from JWT to tool handlers
   - 4 tools only: `apple_search_catalog`, `apple_search_library`, `apple_create_playlist`, `apple_get_track_context`
   - Owns `apple_crate.py` directly (colocated)
   - Entry point: `mcp-apple/main.py`

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
cd mcp-discogs && ./deploy.sh      # Deploy Discogs MCP server only
cd vector && ./deploy.sh           # Deploy vector service (Python) only
cd vector-rs && ./deploy.sh        # Deploy vector service (Rust) only — requires data/index.duckdb
cd mcp-apple && ./deploy.sh        # Deploy Apple MCP server only
```

### Embedding Generation
```bash
cd embeddings
python generate_embeddings.py <directory_or_filelist> [limit]
python generate_clap.py        # Generate CLAP embeddings
python generate_db.py          # Build full DuckDB from JSONL files
python generate_index_db.py    # Build stripped index DB from full DB (for baked-index deployment)
```

### Local Development
```bash
# EchoLocate MCP Server (port 8080)
cd mcp && python main.py

# Discogs MCP Server (port 8080)
cd mcp-discogs && python main.py

# Apple MCP Server (port 8080)
cd mcp-apple && source .venv/bin/activate && python main.py

# Vector Service — Rust (port 8080)
cd vector-rs && INDEX_DB_PATH=../data/index.duckdb cargo run

# Vector Service — Python legacy (port 8000)
cd vector && uvicorn main:app --reload
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
- HNSW indexes on `v_mid` (cosine) and `v_clap` (cosine) per source table

### Interpolation Methods
- **greedy_walk**: Graph traversal finding neighbors closest to target (default)
- **slerp**: Spherical linear interpolation on hypersphere
- **linear**: Simple vector averaging
- Bezier curves available when `steer_track_id` is provided

### MCP Tool Naming Convention
All tools are strictly namespaced: `apple_*`, `discogs_*`, `echolocate_*`

### Environment Variables
- MCP (EchoLocate): `MCP_AUTH_SECRET`, `MCP_JWT_SECRET`, `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`, `VECTOR_SERVICE_URL`
- Discogs MCP: `MCP_AUTH_SECRET`, `MCP_JWT_SECRET`, `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`, `DISCOGS_TOKEN`
- Apple MCP: `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `MCP_JWT_SECRET`, `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`, `GOOGLE_CLOUD_PROJECT` (for Firestore)
- Vector (Rust): `DB_PATH`, `INDEX_DB_PATH` (baked index, takes precedence over DB_PATH), `GCP_PROJECT_ID`, `CLAP_ONNX_DIR`, `CORS_ALLOW_ORIGINS`
- Vector (Python): `LIBRARY_VECTOR_URL`, `FMA_VECTOR_URL`, or legacy `VECTOR_SERVICE_URL`
- Secrets can be fetched from Google Secret Manager if `GOOGLE_CLOUD_PROJECT` is set

### Audio File Structure
Expected path format: `crate/<Source>/<Artist>/<Album>/<Title>.ext`
Metadata is parsed from directory structure.
