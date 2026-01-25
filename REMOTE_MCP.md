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

You must set these environment variables on Cloud Run:

| Variable | Description |
|----------|-------------|
| `MCP_AUTH_SECRET` | The password required on the `/authorize` login page. |
| `MCP_JWT_SECRET` | A secure random string used to sign Access Tokens. |
| `MCP_CLIENT_ID` | (Optional) If set, validates the `client_id` from Claude. |
| `MCP_CLIENT_SECRET` | (Optional) If set, validates the `client_secret` from Claude. |

### Endpoints

- `GET /authorize`: Renders the login page.
- `POST /authorize`: Validates password and issues auth code.
- `POST /token`: Exchanges code for Bearer Token (JWT).

## Available Tools

- `greet(name)` - Returns a greeting from Cloud Run
- `add(a, b)` - Adds two numbers
- `echo(message)` - Echoes back a message

## Client Configuration

### Claude.ai (Web/Mobile)

To use this server on mobile, add it as a **Custom Connector** in [Claude.ai Settings](https://claude.ai/settings/connectors):

1. **URL**: `https://<YOUR-CLOUD-RUN-URL>`
2. **Auth Type**: OAuth 2.1
3. **Authorization URL**: `https://<YOUR-CLOUD-RUN-URL>/authorize`
4. **Token URL**: `https://<YOUR-CLOUD-RUN-URL>/token`
5. **Client ID**: `cloud-crate` (or matching your env var)
6. **Client Secret**: `ignored` (or matching your env var)

### Claude Desktop

You can also use it in `claude_desktop_config.json`, but currently Desktop config requires hardcoding headers or using a local proxy if standard OAuth isn't supported directly in the config file. For Desktop, it is recommended to use the **Connectors** feature via the web dashboard if available, or manually generate a token.

## Deployment Commands

### Initial Setup (one-time)

```bash
# Set project
gcloud config set project cloud-crate-485418

# Enable APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

### Deploy/Update

```bash
cd remote_server
gcloud run deploy mcp-helloworld \
  --source . \
  --region us-central1 \
  --port 8080 \
  --set-env-vars MCP_AUTH_SECRET=changeme,MCP_JWT_SECRET=changeme
```

## Files

| File | Purpose |
|------|---------|
| [main.py](remote_server/main.py) | Starlette + Streamable HTTP Manager + OAuth Provider |
| [Dockerfile](remote_server/Dockerfile) | Container configuration |
| [requirements.txt](remote_server/requirements.txt) | Python dependencies |

## Implementation Notes

The server uses:
- **Starlette** as the ASGI framework (lightweight, robust)
- **StreamableHTTPSessionManager** manually configured to handle protocol negotiation
- **Security**: Host header validation disabled (`enable_dns_rebinding_protection=False`) for Cloud Run compatibility
- **Authentication**: Custom OAuth 2.1 implementation using `python-jose` for JWTs.
- **Routing**: Mounted at root `/` to handle paths like `/sse` and `/messages` without redirection issues
- **uvicorn** to run the server

## Future Migration Path

1. ✅ **Phase 1**: Hello world MCP on Cloud Run
2. ✅ **Phase 2**: Authentication (OAuth 2.1) for Mobile Support
3. **Phase 3**: Migrate read-only tools (`search_library`, etc.)
4. **Phase 4**: BigQuery integration for library data
5. **Phase 5**: Vertex AI embeddings for semantic search
6. **Phase 6**: Hybrid local/remote for write operations

> [!NOTE]
> Write operations like `create_playlist` require local MusicKit access and will remain on the local `edge` CLI.
