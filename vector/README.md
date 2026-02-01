# Cloud Crate Vector Service

A high-performance vector search service built with **DuckDB** and **FastAPI**, designed to run on Google Cloud Run. It serves audio embeddings for similarity search and sonic interpolation.

## Features

- **DuckDB Backend**: Uses `duckdb` with `vss` extension for efficient vector operations.
- **Serverless**: Optimized for Cloud Run (stateless-ish, reads from mounted GCS bucket or local file).
- **Sonic Interpolation**: Algorithms to find paths between songs (Greedy Walk, SLERP, etc.).

## API Endpoints

### tracks
- `GET /tracks`: List tracks (supports pagination and random sampling).
  - Params: `limit` (int), `offset` (int), `random` (bool)

- `GET /tracks/{id}/similar`: Find nearest neighbors for a specific track.
  - Params: `limit` (int)

### Search
- `POST /search`: Search by raw vector.
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
