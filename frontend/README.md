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
./deploy.sh
```

After deployment, update `window.VECTOR_API_URL` in `index.html` to point to your deployed vector service URL.

## IAP Authentication

The frontend is protected by [Identity-Aware Proxy (IAP)](https://cloud.google.com/iap/docs/concepts-overview), restricting access to authorized Google accounts.

### First-time setup

1. Configure the OAuth consent screen in the [GCP Console](https://console.cloud.google.com/apis/credentials/consent?project=cloud-crate-485418) (one-time, external type with your account whitelisted).

2. Run the setup script:
```bash
./setup_iap.sh your-email@gmail.com
```

This creates a global static IP, load balancer, serverless NEG, Google-managed SSL certificate (via nip.io), and enables IAP on the backend service.

3. Deploy the service:
```bash
./deploy.sh
```

4. Wait for the SSL certificate to provision (10-60 minutes). Check status:
```bash
gcloud compute ssl-certificates describe cloud-crate-frontend-cert --global
```

5. Visit the HTTPS URL printed by the setup script. You'll see a Google sign-in page — only the whitelisted account will be granted access.

## Features

- **Text Search**: Search by artist, title, album
- **Semantic Search**: Natural language vibe queries (e.g., "warm jazz saxophone")
- **Similar Tracks**: Find sonically similar tracks
- **Playlist**: Build a queue, interpolate between tracks
- **Audio Player**: Stream audio via signed URLs from GCS
