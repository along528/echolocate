# Audio Embedding Pipeline

Offline pipeline that turns audio files into the vector database the engine serves. Every track is embedded with **[MERT-v1-95M](https://arxiv.org/abs/2306.00107)** (768-dim, sonic similarity) and **[CLAP](https://arxiv.org/abs/2206.04769)** (512-dim, text-matchable), then projected to 2D map coordinates and stripped into the baked index.

## Overview

The system extracts 5-second segments (Intro, Mid, Outro) from audio files and converts them into 768-dimensional MERT vectors, plus one 512-dimensional CLAP vector per track. These power sonic interpolation, similarity search, semantic text search, and the sonar map.

## Files

*   **`embedding_lib.py`**: Core library containing:
    *   `load_and_segment`: Uses `librosa` to load audio and extract the 3 segments (Intro, Mid, Outro).
    *   `MusicEncoder`: A wrapper class for the `m-a-p/MERT-v1-95M` transformer model.
*   **`select_samples.py`**: Randomly selects audio files from the library and saves paths to a text file.
*   **`generate_embeddings.py`**: Scans files (from directory or list), extracts segments, generates MERT embeddings, and saves to JSONL.
*   **`generate_clap.py`**: Generates the 512-dim CLAP embeddings used for semantic text search.
*   **`generate_db.py`**: Loads the JSONL embeddings, creates a DuckDB database with HNSW indexes, and handles ID hashing.
*   **`generate_projection.py`**: Computes the 2D sonar-map `x,y` columns (PCA of `v_mid` by default; `clap-axes` and `umap` also implemented — see [DESIGN.md](../DESIGN.md)). Run against the full DB **before** `generate_index_db.py`.
*   **`generate_index_db.py`**: Builds the stripped ~1.4 GB index DB (metadata + `v_mid` + `v_clap` + `x,y` + HNSW) from the full DB, for the baked-index deployment.
*   **`generate_sample_index.py`**: Produces the committed 600-track sample index used by CI and the dev sandbox.

## Prerequisites

Dependencies are managed in the `requirements.txt` file. We pin specific versions to avoid compilation issues (with `llvmlite`/`cmake`) and ensure compatibility with the `torch` version available on macOS.

```bash
source .venv/bin/activate
pip install -r embeddings/requirements.txt
```

**Key Dependencies**:
*   `librosa` (0.10.1) & `numba` (0.59.0): Pinned to use binary wheels and avoid requiring local build tools.
*   `transformers` (4.46.0): Pinned to compatible with `torch` 2.2.2 (newer transformers require torch >= 2.6).

## Usage

Run from the project root (to ensure correct python path resolution):

```bash
# 1. Select a sample of files (defaults to 10k)
# Use the optional argument to limit the number of files (e.g. 500)
python3 embeddings/select_samples.py [limit]

# 2. Generate MERT embeddings (uses data/library/sample_files.txt by default)
# Supports Resume: Skips files already in embeddings.jsonl
python3 embeddings/generate_embeddings.py

# Or process a specific directory
python3 embeddings/generate_embeddings.py "crate/Rage"

# 3. Generate CLAP embeddings, build the DB, project, and strip the index
python3 embeddings/generate_clap.py
python3 embeddings/generate_db.py
python3 embeddings/generate_projection.py
python3 embeddings/generate_index_db.py
```

## Output

`generate_embeddings.py` writes `embeddings.jsonl` (JSON Lines) containing one JSON object per line. This format supports:
*   **Incremental writing**: Data is saved immediately after processing each track.
*   **Resume Capability**: The script checks this file on startup to skip already processed tracks.

Each line contains:
*   File path and metadata
*   `v_intro`, `v_mid`, `v_outro`: 768-float vectors
