<p align="center">
  <a href="https://echolocate.app/">
    <img src="frontend/artwork.svg" alt="EchoLocate" width="140"/>
  </a>
</p>

# EchoLocate

**[echolocate.app](https://echolocate.app/)** — EchoLocate is a music discovery system powered by MCP (Model Context Protocol), Google Cloud Run, DuckDB, and audio vector search. It exposes sonic similarity search and playlist generation via an MCP server, backed by a high-performance vector search service.

## Architecture

- **`mcp/`**: Remote MCP server exposing 6 EchoLocate tools (`echolocate_*`). Handles OAuth2/JWT authentication and proxies requests to the vector service using Google Cloud ID tokens.
- **`vector/`**: Python vector search service using DuckDB. Serves audio embeddings and supports sonic interpolation. Used as a build dependency for the Rust service.
- **`vector-rs/`**: Rust/Axum vector search service (primary deployment). Baked-index architecture — DuckDB index is embedded in the container image, eliminating cold-start latency.
- **`frontend/`**: Browser UI for exploring tracks with semantic search and interpolation. Protected by Cloud Run native IAP.
- **`embeddings/`**: Scripts for processing audio files, generating MERT and CLAP embeddings, and building the DuckDB database.
- **`fma-ingest/`**: Cloud Run job for ingesting Free Music Archive data from GCS.
- **`firestore/`**: Firestore security rules and deployment config (used by the semantic search cache).

## Features

- **Sonic Search**: Find similar tracks based on audio embeddings (MERT model, 768-dim).
- **Semantic Search**: Text-to-audio search using CLAP embeddings (512-dim).
- **Sonic Interpolation**: Generate smooth playlists between two tracks using greedy walk, SLERP, or linear interpolation.
- **Frontend Explorer**: Browser UI with text search, semantic search, and interpolation playlist builder.

## Security Model

No load balancer — each service is accessed directly via its Cloud Run URL:

- **Frontend**: Protected by Cloud Run native IAP (`--iap` flag). Custom domain `echolocate.app` via Cloud Run domain mapping.
- **Vector service**: Public (`--allow-unauthenticated`) — read-only search. CORS restricted to `https://echolocate.app`. The MCP server has `roles/run.invoker` for service-to-service calls.
- **MCP server**: Publicly reachable for the OAuth2 handshake (`/authorize`, `/token`). All sensitive routes protected by `AuthMiddleware`.

## Deployment

The entire stack deploys to Google Cloud Run.

### Prerequisites
- Google Cloud SDK (`gcloud`) with beta component, authenticated.
- A Google Cloud Project with Cloud Run and Secret Manager enabled.
- A GCS bucket containing your DuckDB file (for the vector service), or a baked `data/index.duckdb` for the Rust service.

### Deploy all services

```bash
./deploy.sh
```

This deploys in order: vector service → MCP server → frontend.

### Set up IAP + Custom Domain

After deploying, configure IAP and the custom domain:

#### Step 1: Enable the IAP API

```bash
gcloud services enable iap.googleapis.com --project=<YOUR_PROJECT>
gcloud beta services identity create --service=iap.googleapis.com --project=<YOUR_PROJECT>
```

#### Step 2: Configure the OAuth consent screen

Go to the GCP Console → APIs & Services → OAuth consent screen. Set up an external app with your email as a test user.

#### Step 3: Create an OAuth client

Go to APIs & Services → Credentials → Create OAuth client ID (Web application). Store the client secret in Secret Manager:

```bash
echo -n "YOUR_CLIENT_SECRET" | gcloud secrets create iap-client-secret --data-file=- --project=<YOUR_PROJECT>
```

#### Step 4: Run the setup script

```bash
./setup_iap.sh <your-google-email>
```

#### Step 5: Configure DNS

Add the A/AAAA records from `gcloud beta run domain-mappings describe` at your domain registrar. Cloud Run provisions a managed TLS certificate automatically.

#### Step 6: Verify

```bash
# Expect 302 (redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://echolocate.app/
```

### Tear down old load balancer (one-time)

```bash
./teardown_lb.sh
```

### Local Development

```bash
# EchoLocate MCP Server (port 8080)
cd mcp && python main.py

# Vector Service — Rust (port 8080)
cd vector-rs && INDEX_DB_PATH=../data/index.duckdb cargo run

# Vector Service — Python legacy (port 8000)
cd vector && uvicorn main:app --reload
```

The frontend automatically uses `http://localhost:8001` as the vector API base when served from localhost.

## Verification

```bash
python vector/verify_service.py <VECTOR_URL>
python mcp/verify_auth.py <MCP_URL>

# Frontend (expect 302 redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://echolocate.app/
```

## Troubleshooting

### Vector API calls fail with CORS errors

**Cause**: `CORS_ALLOW_ORIGINS` on the vector service doesn't include the frontend origin.

**Fix**: Verify the vector service has `CORS_ALLOW_ORIGINS=https://echolocate.app`. Redeploy with `cd vector && ./deploy.sh` if needed.
