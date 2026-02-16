# EchoLocate Frontend

Web frontend for exploring 100k+ FMA tracks with AI-powered search.

## Local Development

1. Start the vector service (from repo root):
```bash
cd vector
DB_PATH=../data/cloudcrate.duckdb uvicorn main:app --reload --port 8001
```

3. Serve the frontend:
```bash
./frontend/start_local.sh
```

4. Open http://localhost:8082

## Deploy to Cloud Run

```bash
chmod +x deploy.sh
./deploy.sh
```

After deployment, update `window.VECTOR_API_URL` in `index.html` to point to your deployed vector service URL.

## Features

- **Text Search**: Search by artist, title, album
- **Semantic Search**: Natural language vibe queries (e.g., "warm jazz saxophone")
- **Similar Tracks**: Find sonically similar tracks
- **Playlist**: Build a queue, interpolate between tracks
- **Audio Player**: Stream audio via signed URLs from GCS
