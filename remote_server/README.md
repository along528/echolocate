# Remote MCP Server Codebase

This directory contains the Python codebase for the Cloud Crate Remote MCP server, designed to run on Google Cloud Run.

## Overview

The server implements the **Model Context Protocol (MCP)** using the `Streamable HTTP` transport strategy (SSE-compatible), which is required for remote connections from clients like Claude Desktop.

It is built using:
- **Starlette**: A lightweight ASGI framework/toolkit.
- **mcp**: The official Python MCP SDK.
- **uvicorn**: An ASGI web server.

## Key Design Decisions

### 1. Manual Session Management
Unlike standard `FastMCP` implementations, this server manually composes `StreamableHTTPSessionManager`. This is required to customize the transport security settings.

### 2. Disabled Host Validation
Cloud Run services often run behind load balancers with dynamic or internal hostnames. We explicitly disable DNS rebinding protection to prevent `421 Misdirected Request` errors:

```python
security_settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)
```

### 3. Root Mount (Catch-All)
We mount the MCP session manager at the root `/` path. This allows the server to handle requests to `/sse`, `/messages`, or any other path the client uses without triggering 307 Temporary Redirects (which can cause protocol errors for POST requests).

### 4. Lifespan Management
We explicitly manage the `manager.run()` context within the Starlette `lifespan` handler to ensure background task groups are properly initialized and cleaned up.

## Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Server**:
   ```bash
   # Runs on port 8080 by default
   python main.py
   ```

3. **Test Endpoints**:
   - Health: `http://localhost:8080/health`
   - SSE: `http://localhost:8080/sse` (POST/GET)

## Deployment

### 1. Prerequisites (One-time)

```bash
# Set project and enable APIs
gcloud config set project cloud-crate-485418
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

### 2. Configure Secrets

Create the necessary secrets in Google Secret Manager:

```bash
# Generate random secrets for Auth and JWT
echo -n `openssl rand -hex 32` | gcloud secrets create MCP_AUTH_SECRET --data-file=-
echo -n `openssl rand -hex 32` | gcloud secrets create MCP_JWT_SECRET --data-file=-

# Set your Client ID (must match what you enter in Claude.ai)
echo -n "cloud-crate-mcp" | gcloud secrets create MCP_CLIENT_ID --data-file=-

# Grant the Cloud Run service account access to secrets (Read & Write)
# - secretAccessor: Read secrets
# - secretVersionAdder: Add new versions (for User Token updates)
gcloud projects add-iam-policy-binding cloud-crate-485418 \
     --member=serviceAccount:PROJECT-NUMBER-compute@developer.gserviceaccount.com \
     --role=roles/secretmanager.secretAccessor

gcloud projects add-iam-policy-binding cloud-crate-485418 \
     --member=serviceAccount:PROJECT-NUMBER-compute@developer.gserviceaccount.com \
     --role=roles/secretmanager.secretVersionAdder

# Apple Music Secrets (Required for Music Tools)
# 1. Get these from Apple Developer Portal -> Certificates, Identifiers & Profiles -> Keys
echo -n "YOUR_TEAM_ID" | gcloud secrets create APPLE_TEAM_ID --data-file=-
echo -n "YOUR_KEY_ID" | gcloud secrets create APPLE_KEY_ID --data-file=-
gcloud secrets create APPLE_PRIVATE_KEY --data-file=path/to/AuthKey_XXXXXX.p8

# Discogs Token (Required for Discogs Tools)
# 1. Get from https://www.discogs.com/settings/developers
echo -n "YOUR_DISCOGS_TOKEN" | gcloud secrets create DISCOGS_TOKEN --data-file=-
```


### 3. Deploy

```bash
gcloud run deploy mcp-helloworld \
  --source . \
  --region us-central1 \
  --port 8080 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=cloud-crate-485418,VECTOR_SERVICE_URL=https://cloudcrate-vector-ie7zxu4hbq-uc.a.run.app
```

For more details, see the root [REMOTE_MCP.md](../REMOTE_MCP.md).

### 5. Apple Music Integration
The `AppleMusicClient` supports both Catalog search and Library search:
- `search(query)`: Search Global Catalog.
- `search_library(query, user_token)`: Search User's Personal Library.
- `get_songs(ids)`: Batch fetch song details (e.g. for preview URLs).

### 6. Vector Service Integration
The server connects to an internal or external Vector Service to provide sonic analysis:
- **Similarity**: Find songs that "sound like" a target song (MERT-v1 embeddings).
- **Interpolation**: Generate a playlist that smoothly transitions between two songs. Use `generate_interpolation_playlist`.

Configure the URL via `VECTOR_SERVICE_URL` env var or secret.
