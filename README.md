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
- **Vector service ingress**: Restricted to `internal-and-cloud-load-balancing` — direct access to the Cloud Run URL is blocked (returns 404).
- **MCP server**: Remains publicly reachable for the OAuth2 handshake (`/authorize`, `/token`). All sensitive routes are protected by app-level `AuthMiddleware`.

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

### Set up Load Balancer + IAP

After deploying, follow these steps to set up the shared load balancer with IAP authentication.

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
4. Click **Create** and copy the **Client ID** and **Client Secret**

#### Step 4: Run the setup script

```bash
./setup_iap.sh <your-google-email>
```

This script is idempotent (safe to re-run) and:
1. Tears down any old frontend-only LB resources.
2. Creates/reuses a static IP address.
3. Creates serverless NEGs for both frontend and vector services.
4. Creates a URL map with path-based routing (`/*` -> frontend, `/api/*` -> vector with path rewrite).
5. Provisions a Google-managed SSL certificate (nip.io domain).
6. Enables IAP on both backend services.
7. Grants your email IAP access.
8. Grants the MCP service account `roles/run.invoker` on the vector service.

#### Step 5: Attach the OAuth client to the backend services

Replace `CLIENT_ID` and `CLIENT_SECRET` with the values from Step 3:

```bash
gcloud compute backend-services update cloud-crate-frontend-backend \
    --global \
    --iap=enabled,oauth2-client-id=CLIENT_ID,oauth2-client-secret=CLIENT_SECRET \
    --project=cloud-crate-485418

gcloud compute backend-services update cloud-crate-vector-backend \
    --global \
    --iap=enabled,oauth2-client-id=CLIENT_ID,oauth2-client-secret=CLIENT_SECRET \
    --project=cloud-crate-485418
```

#### Step 6: Grant the IAP service agent permission to invoke Cloud Run

```bash
PROJECT_NUMBER=$(gcloud projects describe cloud-crate-485418 --format='value(projectNumber)')

gcloud run services add-iam-policy-binding cloud-crate-frontend \
    --region=us-central1 \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project=cloud-crate-485418

gcloud run services add-iam-policy-binding cloud-crate-vector \
    --region=us-central1 \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project=cloud-crate-485418
```

#### Step 7: Wait for SSL and verify

The SSL certificate takes 10-60 minutes to provision. Check status:
```bash
gcloud compute ssl-certificates describe cloud-crate-cert --global --format='value(managed.status)'
```

Once it shows `ACTIVE`, verify IAP is working:
```bash
# Expect 302 (redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://34-149-173-190.nip.io/
```

Then open the URL in your browser and sign in with the email you added as a test user.

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
# SSL cert active
gcloud compute ssl-certificates describe cloud-crate-cert --global --format='value(managed.status)'
# Expected: ACTIVE

# Frontend via LB (expect 302 redirect to Google login)
curl -s -o /dev/null -w '%{http_code}' https://34-149-173-190.nip.io/

# Vector via LB (expect 302 when unauthenticated)
curl -s -o /dev/null -w '%{http_code}' https://34-149-173-190.nip.io/api/

# Vector direct access blocked (expect 404 — Cloud Run returns 404 for blocked ingress)
VECTOR_URL=$(gcloud run services describe cloud-crate-vector --region=us-central1 --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}' $VECTOR_URL/
```

To verify the frontend works end-to-end, open `https://34-149-173-190.nip.io/` in a browser, sign in, and confirm that search and interpolation features load data via `/api/*`.

Use the provided scripts for deeper checks:
- `python vector/verify_service.py <VECTOR_URL>`
- `python mcp/verify_auth.py <MCP_URL>`
