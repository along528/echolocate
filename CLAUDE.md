# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cloud Crate is a music library management and discovery system that exposes MCP (Model Context Protocol) tools for Apple Music, Discogs, and audio-based vector search. The system uses audio embeddings for "sonic" similarity search and playlist generation.

## Architecture

The project consists of three main services:

1. **`mcp/`** - Remote MCP server (Starlette/uvicorn)
   - OAuth2 authentication flow for MCP clients
   - Apple Music integration via `AppleCrate` class (catalog search, library search, playlist creation)
   - Discogs integration via `RecordCrate` class (search, wantlist management)
   - Vector search proxy via `EchoLocate` class (connects to vector service)
   - Entry point: `mcp/main.py`

2. **`vector/`** - Vector search service (FastAPI)
   - DuckDB with VSS extension for vector similarity search
   - CLAP model for semantic text-to-audio search (lazy-loaded)
   - Interpolation algorithms: greedy walk, SLERP, linear, Bezier curves
   - Mounted GCS bucket for database file in Cloud Run
   - Entry point: `vector/main.py`

3. **`embeddings/`** - Audio embedding pipeline (local processing)
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
./deploy.sh                    # Deploy both services to Cloud Run
cd mcp && ./deploy.sh          # Deploy MCP server only
cd vector && ./deploy.sh       # Deploy vector service only
```

### Embedding Generation
```bash
cd embeddings
python generate_embeddings.py <directory_or_filelist> [limit]
python generate_clap.py        # Generate CLAP embeddings
python generate_db.py          # Build DuckDB from JSONL files
```

### Local Development
```bash
# MCP Server (port 8080)
cd mcp && python main.py

# Vector Service (port 8000)
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
- HNSW index on `v_mid` with cosine metric

### Interpolation Methods
- **greedy_walk**: Graph traversal finding neighbors closest to target (default)
- **slerp**: Spherical linear interpolation on hypersphere
- **linear**: Simple vector averaging
- Bezier curves available when `steer_track_id` is provided

### MCP Tool Naming Convention
All tools are strictly namespaced: `apple_*`, `discogs_*`, `echolocate_*`

### Environment Variables
- MCP: `MCP_AUTH_SECRET`, `MCP_JWT_SECRET`, `MCP_CLIENT_ID`, `MCP_CLIENT_SECRET`
- Apple: `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_MUSIC_USER_TOKEN`
- Discogs: `DISCOGS_TOKEN`
- Vector: `LIBRARY_VECTOR_URL`, `FMA_VECTOR_URL`, or legacy `VECTOR_SERVICE_URL`
- Secrets can be fetched from Google Secret Manager if `GOOGLE_CLOUD_PROJECT` is set

### Audio File Structure
Expected path format: `crate/<Source>/<Artist>/<Album>/<Title>.ext`
Metadata is parsed from directory structure.
