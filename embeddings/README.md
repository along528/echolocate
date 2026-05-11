# Audio Embedding Prototype

This directory contains the proof-of-concept pipeline for generating semantic music embeddings using the **[MERT-v1-95M](https://arxiv.org/abs/2604.20270)** model.

## Overview

The system extracts 5-second segments (Intro, Mid, Outro) from audio files and converts them into 768-dimensional vectors. These vectors are designed to be used for "sonic interpolation" and context-aware music discovery.

## Files

*   **`embedding_lib.py`**: Core library containing:
    *   `load_and_segment`: Uses `librosa` to load audio and extract the 3 segments (Intro, Mid, Outro).
    *   `MusicEncoder`: A wrapper class for the `m-a-p/MERT-v1-95M` transformer model.
    *   `MusicEncoder`: A wrapper class for the `m-a-p/MERT-v1-95M` transformer model.
*   **`select_samples.py`**: Randomly selects audio files from the library and saves paths to a text file.
*   **`generate_embeddings.py`**: Scans files (from directory or list), extracts segments, generates embeddings, and saves to JSON.
*   **`generate_db.py`**: Loads the JSON embeddings, creates a DuckDB database with HNSW indexes, and handles ID hashing.

## Prerequisites

Dependencies are managed in the `requirements.txt` file. We pin specific versions to avoid compilation issues (with `llvmlite`/`cmake`) and ensure compatibility with the `torch` version available on macOS.

```bash
source .venv/bin/activate
pip install -r audio_embedding/requirements.txt
```

**Key Dependencies**:
*   `librosa` (0.10.1) & `numba` (0.59.0): Pinned to use binary wheels and avoid requiring local build tools.
*   `transformers` (4.46.0): Pinned to compatible with `torch` 2.2.2 (newer transformers require torch >= 2.6).

## Usage

Run the sample generator from the project root (to ensure correct python path resolution):

```bash
# 1. Select a sample of files (defaults to 10k)
# Use the optional argument to limit the number of files (e.g. 500)
python3 audio_embedding/select_samples.py [limit]

# 2. Generate Embeddings (uses data/library/sample_files.txt by default)
# Supports Resume: Skips files already in embeddings.jsonl
python3 audio_embedding/generate_embeddings.py

# Or process a specific directory
python3 audio_embedding/generate_embeddings.py "crate/Rage"
```

## Output

The script generates `embeddings.jsonl` (JSON Lines) containing one JSON object per line. This format supports:
*   **Incremental writing**: Data is saved immediately after processing each track.
*   **Resume Capability**: The script checks this file on startup to skip already processed tracks.

Each line contains:
*   File path and metadata
*   `v_intro`, `v_mid`, `v_outro`: 768-float vectors

## Verification

To verify the end-to-end flow of fetching Apple Music previews and ensuring they can be embedded, use the verification script:

```bash
python3 audio_embedding/verify_preview_embedding.py
```

This script:
1.  Searches for a sample song ("Taylor Swift Anti-Hero").
2.  Fetches the song details to get the preview URL.
3.  Downloads the preview audio to `audio_embedding/tmp/`.
4.  Generates a single embedding for the preview audio.
5.  Saves the embedding to `audio_embedding/tmp/`.
