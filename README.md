# Cloud Crate

Cloud Crate is a music library management and discovery system powered by MCP (Model Context Protocol), Google Cloud Run, DuckDB, and Vector Search. This repository contains the code for the backend MCP server, the vector search service, a browser-based frontend, and the audio embedding pipeline.

## Architecture

- **`mcp/`**: A remote MCP server that exposes tools for Apple Music, Discogs, and Vector Search. It handles OAuth2/JWT authentication and orchestrates requests. Authenticates to the vector service using Google Cloud ID tokens.
- **`vector/`**: A high-performance vector search service using DuckDB. It serves audio embeddings and supports sonic interpolation. Locked down to only accept traffic from the load balancer (browser) and the MCP server (service account).
- **`frontend/`**: A browser-based UI for exploring FMA tracks with semantic search and interpolation. Served behind Identity-Aware Proxy (IAP) for access control.
- **`embeddings/`**: Scripts for processing audio files, generating embeddings (using generic audio transformers), and building the DuckDB database.

## Features

- **Apple Music**: Search catalog, manage library, create playlists.
- **Discogs**: Search database, fetch release details, manage wantlist.
- **Echo Locate**: "Sonic" search finding similar tracks based on audio analysis, and "Sonic Interpolation" to generate smooth playlists between two tracks.
- **Frontend Explorer**: Browser UI with text search, semantic (CLAP) search, and interpolation playlist builder.
- **Strict Naming**: All MCP tools are namespaced (`apple_*`, `discogs_*`, `echolocate_*`).

## Security Model

The frontend and vector service sit behind a shared Google Cloud HTTPS Load Balancer with Identity-Aware Proxy (IAP):

- **Frontend** (`/*`): Served through the LB. IAP requires Google login before access is granted.
- **Vector API** (`/api/*`): Routed through the same LB with a path rewrite (`/api/tracks` -> `/tracks`). IAP protects browser access. The MCP server authenticates directly via Google Cloud ID tokens (service account with `roles/run.invoker`).
- **Vector service ingress**: Restricted to `internal-and-cloud-load-balancing` — direct access to the Cloud Run URL returns 403.
- **MCP server**: Remains publicly reachable for the OAuth2 handshake (`/authorize`, `/token`). All sensitive routes are protected by app-level `AuthMiddleware`.

## Deployment

The entire stack is designed to be deployed to Google Cloud Run.

### Prerequisites
- Google Cloud SDK (`gcloud`) installed and authenticated.
- A Google Cloud Project with Cloud Run, Secret Manager, and IAP enabled.
- A GCS bucket containing your `cloudcrate.duckdb` file (for the vector service).
- OAuth consent screen configured in the GCP Console.

### Deploy all services

```bash
./deploy.sh
```

This deploys all three services:
1. `cloud-crate-vector` — vector search (requires a GCS bucket with `cloudcrate.duckdb`).
2. `cloud-crate-mcp` — MCP server, automatically linked to the vector service.
3. `cloud-crate-frontend` — browser UI.

### Set up Load Balancer + IAP

After deploying, run the IAP setup script to create the shared load balancer and enable authentication:

```bash
./setup_iap.sh <your-google-email>
```

This script:
1. Tears down any old frontend-only LB resources.
2. Creates serverless NEGs for both frontend and vector services.
3. Creates a URL map with path-based routing (`/*` -> frontend, `/api/*` -> vector with path rewrite).
4. Provisions a Google-managed SSL certificate (nip.io domain).
5. Enables IAP on both backend services.
6. Grants your email IAP access.
7. Grants the MCP service account `roles/run.invoker` on the vector service.

The SSL certificate takes 10-60 minutes to provision. Check status:
```bash
gcloud compute ssl-certificates describe cloud-crate-cert --global
```

### Connect to Claude
Once deployed, configure your Claude Desktop or other MCP client with the Remote MCP URL:

```json
{
  "mcpServers": {
    "cloud-crate": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sse", "<YOUR_MCP_URL>/sse"]
    }
  }
}
```

### Local Development

For local development, the frontend defaults to `/api` as the vector API base URL. Override this in the browser console or by editing `frontend/index.html`:

```js
window.VECTOR_API_URL = 'http://localhost:8001';
```

The MCP server's vector client gracefully falls back to unauthenticated requests when no Google Cloud metadata server is available (i.e., local dev).

## Verification

After deployment and IAP setup:

```bash
# SSL cert provisioned
gcloud compute ssl-certificates describe cloud-crate-cert --global

# Frontend via LB (expect 302 redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://<IP>.nip.io/

# Vector via LB (expect 302 when unauthenticated)
curl -s -o /dev/null -w '%{http_code}' https://<IP>.nip.io/api/

# Vector direct access blocked (expect 403)
curl -s -o /dev/null -w '%{http_code}' https://cloud-crate-vector-....run.app/

# MCP -> vector works (test via an echolocate MCP tool)
```

Use the provided scripts for deeper checks:
- `python vector/verify_service.py <VECTOR_URL>`
- `python mcp/verify_auth.py <MCP_URL>`
