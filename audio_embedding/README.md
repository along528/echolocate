# Audio Embedding Prototype

This directory contains the proof-of-concept pipeline for generating semantic music embeddings using the **MERT-v1-95M** model.

## Overview

The system extracts 5-second segments (Intro, Mid, Outro) from audio files and converts them into 768-dimensional vectors. These vectors are designed to be used for "sonic interpolation" and context-aware music discovery.

## Files

*   **`embedding_lib.py`**: Core library containing:
    *   `load_and_segment`: Uses `librosa` to load audio and extract the 3 segments (Intro, Mid, Outro).
    *   `MusicEncoder`: A wrapper class for the `m-a-p/MERT-v1-95M` transformer model.
*   **`generate_sample.py`**: A CLI script to batch process a directory of audio files and output a JSON file.

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
# Process files in a specific directory
python3 audio_embedding/generate_sample.py "path/to/music/directory"

# Example
python3 audio_embedding/generate_sample.py "crate/Rage"
```

## Output

The script generates `embeddings_sample.json` containing:
*   File path and metadata
*   `v_intro`, `v_mid`, `v_outro`: 768-float vectors

## Next Steps

*   Integration with PostgreSQL (`pgvector`) for persistent storage.
*   Building "Sonic Interpolation" queries.
