# Cloud Run Remote MCP Server

This document describes the remote MCP server deployed on Google Cloud Run.

## Live Deployment

| Component | Value |
|-----------|-------|
| **Service URL** | https://mcp-helloworld-403961692263.us-central1.run.app |
| **SSE Endpoint** | https://mcp-helloworld-403961692263.us-central1.run.app/sse |
| **Health Check** | https://mcp-helloworld-403961692263.us-central1.run.app/ |
| **Project ID** | cloud-crate-485418 |
| **Region** | us-central1 |

## Architecture

```
┌─────────────────────┐         HTTPS/SSE          ┌──────────────────────┐
│   (Claude Desktop)  │  <-- Authenticated -->     │   MCP Server         │
│      (Mobile)       │      (OAuth 2.1)           │   (Starlette/Python) │
│                     │                            │   (Streamable HTTP)  │
└─────────────────────┘                            └──────────────────────┘
```

**Transport**: Remote MCP uses SSE (Server-Sent Events) instead of stdio.

## Authentication (OAuth 2.1)

This server acts as a minimal OAuth 2.1 Provider to support Claude Mobile Connectors.

### Configuration Variables

You can set these as **Environment Variables** (for local dev) or create them in **Google Secret Manager** (recommended for production).

| Variable / Secret Name | Description |
|------------------------|-------------|
| `MCP_AUTH_SECRET` | The password required on the `/authorize` login page. |
| `MCP_JWT_SECRET` | A secure random string used to sign Access Tokens. |
| `MCP_CLIENT_ID` | (Optional) If set, validates the `client_id` from Claude. |
| `MCP_CLIENT_SECRET` | (Optional) If set, validates the `client_secret` from Claude. |
| `APPLE_TEAM_ID` | Apple Developer Team ID (Membership). |
| `APPLE_KEY_ID` | MusicKit Private Key ID (Keys -> MusicKit). |
| `APPLE_PRIVATE_KEY` | Contents of the `.p8` private key file. |
| `DISCOGS_TOKEN` | Discogs Personal Access Token. |
| `VECTOR_SERVICE_URL` | URL of the internal Vector Service (e.g. `https://cloudcrate-vector-ie7zxu4hbq-uc.a.run.app`). |

### Using Google Secret Manager

1. **Enable API**: `gcloud services enable secretmanager.googleapis.com`
2. **Create Secrets**:
   > **Tip**: Generate strong secrets: `openssl rand -hex 32`
   
   ```bash
   echo -n `openssl rand -hex 32` | gcloud secrets create MCP_AUTH_SECRET --data-file=-
   echo -n `openssl rand -hex 32` | gcloud secrets create MCP_JWT_SECRET --data-file=-
   echo -n "cloud-crate" | gcloud secrets create MCP_CLIENT_ID --data-file=-
   
   # Apple Music Secrets
   echo -n "YOUR_TEAM_ID" | gcloud secrets create APPLE_TEAM_ID --data-file=-
   echo -n "YOUR_KEY_ID" | gcloud secrets create APPLE_KEY_ID --data-file=-
   gcloud secrets create APPLE_PRIVATE_KEY --data-file=path/to/AuthKey_XXXXXX.p8

   # Discogs Secret
   echo -n "YOUR_DISCOGS_TOKEN" | gcloud secrets create DISCOGS_TOKEN --data-file=-
   
   # Vector Service URL (Optional, defaults to http://vector-service:8080)
   echo -n "https://cloudcrate-vector-ie7zxu4hbq-uc.a.run.app" | gcloud secrets create VECTOR_SERVICE_URL --data-file=-
   ```
3. **Grant Access**:
   The Cloud Run service account must have `roles/secretmanager.secretAccessor`.
   ```bash
   # Find your Service Account (usually default compute)
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com \
     --role=roles/secretmanager.secretAccessor

   # Allow server to update User Token
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com \
     --role=roles/secretmanager.secretVersionAdder
   ```

### Endpoints

- `GET /authorize`: Renders the login page.
- `POST /authorize`: Validates password and issues auth code.
- `POST /authorize`: Validates password and issues auth code.
- `POST /token`: Exchanges code for Bearer Token (JWT).
- `GET /apple-auth`: Renders "Log in with Apple Music" page.

## Available Tools

- `greeting(name)` - Returns a greeting from Cloud Run
- `search_apple_music(query)` - Search Apple Music Catalog
- `search_library(query)` - Search your Apple Music Library
- `sample_vector_db()` - List tracks in Vector DB to find IDs
- `find_similar_tracks(track_id)` - Find similar tracks (requires Vector DB ID)
- `interpolate_tracks(track_id_1, track_id_2)` - Sonic interpolation (requires Vector DB IDs)
- `generate_interpolation_playlist(...)` - Generate sonic playlist data (requires library search)
- `search_discogs(query)` - Search for albums (master releases)
- `get_discogs_versions(master_id)` - Get versions for a master release (with marketplace links)
- `get_discogs_release(release_id)` - Get details for a specific release
- `get_discogs_wantlist()` - Get your Discogs wantlist items

## Client Configuration

### Claude.ai (Web/Mobile)

To use this server on mobile, add it as a **Custom Connector** in [Claude.ai Settings](https://claude.ai/settings/connectors):

1. **URL**: `https://<YOUR-CLOUD-RUN-URL>`
2. **Auth Type**: OAuth 2.1
3. **Authorization URL**: `https://<YOUR-CLOUD-RUN-URL>/authorize`
4. **Token URL**: `https://<YOUR-CLOUD-RUN-URL>/token`
5. **Client ID**: `cloud-crate` (or matching your secret)
6. **Client Secret**: `ignored` (or matching your secret)

### Claude Desktop

You can also use it in `claude_desktop_config.json`, but currently Desktop config requires hardcoding headers or using a local proxy if standard OAuth isn't supported directly in the config file. For Desktop, it is recommended to use the **Connectors** feature via the web dashboard if available, or manually generate a token.

## Deployment Commands

### Initial Setup (one-time)

```bash
# Set project
gcloud config set project cloud-crate-485418

# Enable APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

### Deploy/Update

```bash
cd remote_server
gcloud run deploy mcp-helloworld \
  --source . \
  --region us-central1 \
  --port 8080 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=cloud-crate-485418,VECTOR_SERVICE_URL=https://cloudcrate-vector-ie7zxu4hbq-uc.a.run.app
```
*Note: We set `GOOGLE_CLOUD_PROJECT` explicitly just to be safe, though Cloud Run usually provides it. We NO LONGER pass secrets as env vars.*

## Files

| File | Purpose |
|------|---------|
| [main.py](remote_server/main.py) | Starlette + Streamable HTTP Manager + OAuth Provider + Secret Manager |
| [Dockerfile](remote_server/Dockerfile) | Container configuration |
| [requirements.txt](remote_server/requirements.txt) | Python dependencies |
| [discogs.py](remote_server/discogs.py) | Discogs API Client |

## Implementation Notes

The server uses:
- **Starlette** as the ASGI framework (lightweight, robust)
- **StreamableHTTPSessionManager** manually configured to handle protocol negotiation
- **Security**: Host header validation disabled (`enable_dns_rebinding_protection=False`) for Cloud Run compatibility
- **Authentication**: Custom OAuth 2.1 implementation using `python-jose` for JWTs.
- **Secrets**: Auto-fetches from Google Secret Manager if available, falls back to Env Vars.
- **Routing**: Mounted at root `/` to handle paths like `/sse` and `/messages` without redirection issues
- **uvicorn** to run the server

## Future Migration Path

1. ✅ **Phase 1**: Hello world MCP on Cloud Run
2. ✅ **Phase 2**: Authentication (OAuth 2.1) for Mobile Support
3. ✅ **Phase 3**: Google Secret Manager Integration
4. ✅ **Phase 4**: Migrate read-only tools (`search_library`, `vector_search`, etc.)
5. **Phase 5**: BigQuery integration for library data
6. **Phase 6**: Vertex AI embeddings for semantic search
7. **Phase 7**: Hybrid local/remote for write operations

> [!NOTE]
> Write operations like `create_playlist` require local MusicKit access and will remain on the local `edge` CLI.
