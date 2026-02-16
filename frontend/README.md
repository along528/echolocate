# EchoLocate Frontend

Web frontend for exploring 100k+ FMA tracks with AI-powered search.

## Features

- **Text Search**: Search by artist, title, album
- **Semantic Search**: Natural language vibe queries (e.g., "warm jazz saxophone")
- **Similar Tracks**: Find sonically similar tracks
- **Interpolation Builder**: Generate smooth playlists between two tracks
- **Audio Player**: Stream audio via signed URLs from GCS

## Local Development

1. Start the vector service (from repo root):
```bash
./vector/start_local.sh
```

2. Serve the frontend:
```bash
./frontend/start_local.sh
```

3. Open http://localhost:8082

In local dev, override the API URL in `index.html`:
```js
window.VECTOR_API_URL = 'http://localhost:8001';
```

## Deployment

The frontend is deployed as part of the full stack. From the repo root:

```bash
./deploy.sh
```

In production, the frontend sits behind a shared load balancer with IAP authentication. API calls use the relative path `/api/*`, which the LB routes to the vector service. See the [root README](../README.md#set-up-load-balancer--iap) for full setup instructions.
