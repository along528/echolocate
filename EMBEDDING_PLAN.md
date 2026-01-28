# Agent Specification: CloudCrate Music Embedding System

**Objective:** Build a multi-phase pipeline to generate semantic music embeddings using **MERT-v1-95M** and store them in **pgvector** for a music discovery application.

## Phase 1: Local Embedding Prototype (COMPLETED)

*   **Status**: Done. Files moved to `audio_embedding/`.
*   **Audio Loading**: implemented in `audio_embedding/embedding_lib.py` using `librosa`. Resampled to 24kHz.
*   **The "DJ Trinity" Extraction**: implemented. Extracts 5s segments (Intro, Mid, Outro).
*   **Model Inference**: implemented `MusicEncoder` class using `m-a-p/MERT-v1-95M`. Returns 768-dim vectors.
*   **Output**: Verified. Script `audio_embedding/generate_sample.py` successfully produces `embeddings_sample.json`.

## Phase 2: Vector Database (DuckDB) (COMPLETED)

*   **Architecture**: Serverless vector DB using **DuckDB** running on **Cloud Run** with **Google Cloud Storage** volume mounts.
*   **Database File**: `cloudcrate.duckdb` generated locally with `vss` extension (HNSW index).
*   **Service**: `vector_service/` (FastAPI) deployed as `cloudcrate-vector`.
*   **Data Flow**:
    1.  Generate `.duckdb` locally from JSON.
    2.  Upload to GCS bucket `cloud-crate-vector-db`.
    3.  Cloud Run mounts bucket to `/data`.
    4.  Service queries `/data/cloudcrate.duckdb` (Read-Only).

## Phase 3: Scaling & Discovery Logic

### Completed
*   **Audio Sampling**: Created `select_samples.py` to randomly pick tracks.
*   **Embedding Pipeline**: Updated `generate_embeddings.py` to support file lists, progress tracking, and metadata extraction.
*   **Database Schema**: Updated to support:
    *   `v_intro`, `v_mid`, `v_outro` vector columns.
    *   `relative_path` for consistent file referencing.
    *   **Hashed IDs** (`artist|album|title`) for consistency.
*   **Indexing**: Created HNSW index on `v_mid` for primary search.
*   **Discovery Queries**: Implemented in `vector_service`:
    *   **Sonic Interpolation**: `/interpolate` endpoint (midpoint between two tracks).
    *   **Find Similar by ID**: `/tracks/{id}/similar` endpoint.
    *   **List Tracks**: `/tracks` endpoint with paging.
*   **Scaling & Robustness**:
    *   Switched to **JSONL** (`embeddings.jsonl`) for incremental writing.
    *   Added **Resume Capability** to skip already processed files.
    *   Updated `select_samples.py` to default to 10k tracks.

### Pending (To Be Implemented)
*   **Apple Music Integration**: Fetch previews via MusicKit URL (optional).

## Phase 4: MCP Server Integration

*   **Server Exposure:** Wrap the Phase 3 queries into tools within the **CloudCrate MCP server**.
*   **Secure Access:** Ensure the server connects to the database via the existing **OAuth 2.1 / Cloud Run** infrastructure.

---

### Implementation Note for Agent

> **Memory Safety:** Use `torch.no_grad()` and move the model to `cpu` or `mps` (for the 2019 MacBook Pro) to prevent memory leaks during batch processing.
