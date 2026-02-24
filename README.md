# Cloud Crate

Cloud Crate is a music library management and discovery system powered by MCP (Model Context Protocol), Google Cloud Run, DuckDB, and Vector Search. This repository contains the code for the backend MCP server, the vector search service, a browser-based frontend, and the audio embedding pipeline.

## Architecture

- **`mcp/`**: A remote MCP server that exposes tools for Apple Music, Discogs, and Vector Search. It handles OAuth2/JWT authentication and orchestrates requests. Authenticates to the vector service using Google Cloud ID tokens.
- **`vector/`**: A high-performance vector search service using DuckDB. It serves audio embeddings and supports sonic interpolation. Public with CORS restricted to the frontend domain.
- **`frontend/`**: A browser-based UI for exploring FMA tracks with semantic search and interpolation. Protected by Cloud Run native Identity-Aware Proxy (IAP).
- **`embeddings/`**: Scripts for processing audio files, generating embeddings (using generic audio transformers), and building the DuckDB database.

## Features

- **Apple Music**: Search catalog, manage library, create playlists.
- **Discogs**: Search database, fetch release details, manage wantlist.
- **Echo Locate**: "Sonic" search finding similar tracks based on audio analysis, and "Sonic Interpolation" to generate smooth playlists between two tracks.
- **Frontend Explorer**: Browser UI with text search, semantic (CLAP) search, and interpolation playlist builder.
- **Strict Naming**: All MCP tools are namespaced (`apple_*`, `discogs_*`, `echolocate_*`).

## Security Model

No load balancer — each service is accessed directly via its Cloud Run URL:

- **Frontend**: Protected by Cloud Run native IAP (`--iap` flag). Requires Google login before access is granted. Custom domain `echolocate.app` via Cloud Run domain mapping.
- **Vector service**: Public (`--allow-unauthenticated`) since it's read-only search. CORS restricted to `https://echolocate.app`. The MCP server also has `roles/run.invoker` for service-to-service calls.
- **MCP server**: Publicly reachable for the OAuth2 handshake (`/authorize`, `/token`). All sensitive routes are protected by app-level `AuthMiddleware`.

## Deployment

The entire stack is designed to be deployed to Google Cloud Run.

### Prerequisites
- Google Cloud SDK (`gcloud`) with beta component installed and authenticated.
- A Google Cloud Project with Cloud Run and Secret Manager enabled.
- A GCS bucket containing your `cloudcrate.duckdb` file (for the vector service).

### Deploy all services

```bash
./deploy.sh
```

This deploys all three services:
1. `cloud-crate-vector` — vector search (requires a GCS bucket with `cloudcrate.duckdb`).
2. `cloud-crate-mcp` — MCP server, automatically linked to the vector service.
3. `cloud-crate-frontend` — browser UI.

### Set up IAP + Custom Domain

After deploying, follow these steps to configure IAP authentication and the custom domain.

#### Step 1: Enable the IAP API and create its service agent

```bash
gcloud services enable iap.googleapis.com --project=cloud-crate-485418
gcloud beta services identity create --service=iap.googleapis.com --project=cloud-crate-485418
```

#### Step 2: Configure the OAuth consent screen

Go to https://console.cloud.google.com/apis/credentials/consent and set up:
- **App name**: `Cloud Crate`
- **User support email**: your email
- **Audience/User type**: External
- **Developer contact email**: your email
- **Test users**: add your email

Skip the Scopes page. The app stays in "Testing" mode, so only the test users you add can log in.

#### Step 3: Create an OAuth client

Go to https://console.cloud.google.com/apis/credentials and:
1. Click **"+ Create Credentials"** -> **"OAuth client ID"**
2. Application type: **Web application**
3. Name: `IAP-Cloud-Crate`
4. Click **Create** and save the **Client ID** and **Client Secret**

Store the client secret in Secret Manager (or pass it via `IAP_CLIENT_SECRET` env var):
```bash
echo -n "YOUR_CLIENT_SECRET" | gcloud secrets create iap-client-secret --data-file=- --project=cloud-crate-485418
```

#### Step 4: Run the setup script

```bash
./setup_iap.sh <your-google-email>
```

This script is idempotent (safe to re-run) and:
1. Grants the IAP service agent `roles/run.invoker` on the frontend.
2. Configures the OAuth client ID/secret on the frontend's IAP settings.
3. Grants your email IAP access on the frontend Cloud Run service.
4. Grants the MCP service account `roles/run.invoker` on the vector service.
5. Creates a Cloud Run domain mapping for `echolocate.app`.

#### Step 5: Configure DNS

Add these records at your domain registrar (values from `gcloud beta run domain-mappings describe`):

| Type | Name | Value |
|------|------|-------|
| A    | @ | 216.239.32.21 |
| A    | @ | 216.239.34.21 |
| A    | @ | 216.239.36.21 |
| A    | @ | 216.239.38.21 |
| AAAA | @ | 2001:4860:4802:32::15 |
| AAAA | @ | 2001:4860:4802:34::15 |
| AAAA | @ | 2001:4860:4802:36::15 |
| AAAA | @ | 2001:4860:4802:38::15 |

Cloud Run automatically provisions and renews a managed TLS certificate once DNS is configured.

#### Step 6: Verify

```bash
# Expect 302 (redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://echolocate.app/
```

Open `https://echolocate.app` in your browser and sign in with the email you added as a test user.

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

### Tear down old load balancer (one-time)

If migrating from the previous LB-based setup, run:
```bash
./teardown_lb.sh
```

This removes all old LB resources (forwarding rule, HTTPS proxy, SSL cert, URL map, backend services, NEGs, static IP).

### Local Development

For local development, the frontend automatically uses `http://localhost:8001` as the vector API base URL when served from localhost.

The MCP server's vector client gracefully falls back to unauthenticated requests when no Google Cloud metadata server is available (i.e., local dev).

## Verification

After deployment and IAP setup:

```bash
# Frontend (expect 302 redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://echolocate.app/

# Vector service (expect 200 — publicly accessible)
curl -s -o /dev/null -w '%{http_code}' https://cloud-crate-vector-403961692263.us-central1.run.app/
```

To verify the frontend works end-to-end, open `https://echolocate.app` in a browser, sign in, and confirm that search and interpolation features work.

Use the provided scripts for deeper checks:
- `python vector/verify_service.py <VECTOR_URL>`
- `python mcp/verify_auth.py <MCP_URL>`

## Troubleshooting

### Vector API calls fail with CORS errors

**Cause**: The `CORS_ALLOW_ORIGINS` env var on the vector service doesn't include the frontend origin.

**Fix**: Verify the vector service has `CORS_ALLOW_ORIGINS=https://echolocate.app` set. Redeploy with `cd vector && ./deploy.sh` if needed.
