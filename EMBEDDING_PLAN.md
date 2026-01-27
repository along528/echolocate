# Agent Specification: CloudCrate Music Embedding System

**Objective:** Build a multi-phase pipeline to generate semantic music embeddings using **MERT-v1-95M** and store them in **pgvector** for a music discovery application.

## Phase 1: Local Embedding Prototype

*   **Audio Loading:** Use `librosa` to load local files. Resample all audio to **24,000Hz**.
*   **The "DJ Trinity" Extraction:** For each track, extract exactly **5 seconds** from three specific segments:
    1.  **Intro:** 0s to 5s.
    2.  **Middle:** (Duration/2) to (Duration/2 + 5s).
    3.  **Outro:** (Duration - 5s) to Duration.
*   **Model Inference:** Use `transformers` to load `m-a-p/MERT-v1-95M`. Generate vectors by taking the **mean of the last hidden state** (resulting in a **768-dimension** vector per segment).
*   **Output:** Save results to a local `embeddings_sample.json` for validation.

## Phase 2: pgvector Integration

*   **Database Setup:** Create a PostgreSQL schema with the `vector` extension.
*   **Table Design:** Define a `tracks` table with columns `v_intro`, `v_mid`, and `v_outro`, all type `vector(768)`.
*   **Data Migration:** Write a script using `psycopg2` or `SQLAlchemy` to batch-upload the JSON data from Phase 1 into the database.

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
