# Cloud Crate Vector Service

A high-performance vector search service built with **DuckDB** and **FastAPI**, designed to run on Google Cloud Run. It serves audio embeddings for similarity search and sonic interpolation.

## Features

- **DuckDB Backend**: Uses `duckdb` with `vss` extension for efficient vector operations.
- **Serverless**: Optimized for Cloud Run (stateless-ish, reads from mounted GCS bucket or local file).
- **Sonic Interpolation**: Algorithms to find paths between songs (Greedy Walk, SLERP, etc.).
- **ONNX Text Encoder**: [CLAP](https://arxiv.org/abs/2206.04769) text encoder exported to ONNX for fast semantic search (~25x faster inference, no PyTorch at runtime).

## API Endpoints

### tracks
- `GET /tracks`: List tracks (supports pagination and random sampling).
  - Params: `limit` (int), `offset` (int), `random` (bool)

- `GET /tracks/{id}/similar`: Find nearest neighbors for a specific track.
  - Params: `limit` (int)

### Search

- `GET /search`: Text-based search by artist, album, or title.
  - Params: `query` (str), `artist` (str), `album` (str), `title` (str), `limit` (int)
  - All params are optional but at least one required. Multiple params use AND logic.
  - Example: `/search?artist=Testament&album=Legacy&limit=5`

- `POST /vector-search`: Search by raw embedding vector.
  - Body: `{"vector": [...], "limit": 10}`

### Interpolation
- `POST /interpolate`: Generate a path between two tracks.
  - Body:
    ```json
    {
      "track_id_1": "string",
      "track_id_2": "string",
      "limit": 10,
      "method": "greedy_walk" | "slerp" | "linear",
      "steer_track_id": "optional_string"
    }
    ```

- `POST /interpolate/playlist`: Same as above but optimized/formatted for playlist generation contexts.

## Deployment

Deploy using the script in this directory:

```bash
./deploy.sh
```

**Service Name**: `cloud-crate-vector`

### Requirements
- A Google Cloud Storage bucket containing `cloudcrate.duckdb`.
- The `deploy.sh` script handles mounting this bucket using gcsfuse.

## ONNX Export

The Docker build handles ONNX export automatically via a two-stage build. To export locally (for validation or development):

```bash
python export_clap_text.py --output-dir ./clap_text_onnx
```

To validate the ONNX model matches PyTorch output:

```bash
python validate_onnx.py --onnx-dir ./clap_text_onnx
```

### How it works

The full [CLAP](https://arxiv.org/abs/2206.04769) model (`laion/clap-htsat-unfused`, ~615MB) includes both audio and text encoders, but the vector service only uses the text encoder for semantic search. The export script wraps `text_model` + `text_projection` into a single ONNX model (~478MB), eliminating the need for PyTorch and transformers at runtime. This reduces cold start time by ~4-7s on Cloud Run.

## Local Development

To run the service locally, you can use the provided helper script which sets up the environment variables and enables CORS for local development:

```bash
./start_local.sh
```

This will start the service on `http://localhost:8001` with `CORS_ALLOW_ORIGINS="*"`.
