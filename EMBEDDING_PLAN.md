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

*   **Expansion:** Process a larger sample set including your local library and **Apple Music previews** (fetched via MusicKit URL).
*   **Discovery Queries:** Implement SQL functions for:
    *   **Sonic Interpolation:** Find the "midpoint" between two tracks using `(vector_a + vector_b) / 2`.
    *   **Contextual Matching:** Match the `v_outro` of Song A to the `v_intro` of other tracks.
*   **Indexing:** Add an **HNSW index** to the vector columns to ensure high-performance searching.

## Phase 4: MCP Server Integration

*   **Server Exposure:** Wrap the Phase 3 queries into tools within the **CloudCrate MCP server**.
*   **Secure Access:** Ensure the server connects to the database via the existing **OAuth 2.1 / Cloud Run** infrastructure.

---

### Implementation Note for Agent

> **Memory Safety:** Use `torch.no_grad()` and move the model to `cpu` or `mps` (for the 2019 MacBook Pro) to prevent memory leaks during batch processing.
