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
│   MCP Client        │ ──────────────────────────▶│   Cloud Run          │
│   (Claude Desktop)  │                            │   MCP Server         │
└─────────────────────┘                            │   (FastAPI + FastMCP)│
                                                   └──────────────────────┘
```

**Transport**: Remote MCP uses SSE (Server-Sent Events) instead of stdio.

## Available Tools

- `greet(name)` - Returns a greeting from Cloud Run
- `add(a, b)` - Adds two numbers
- `echo(message)` - Echoes back a message

## Client Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cloud-run-hello": {
      "url": "https://mcp-helloworld-403961692263.us-central1.run.app/sse"
    }
  }
}
```

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
gcloud run deploy mcp-helloworld --source . --region us-central1 --port 8080
```

## Files

| File | Purpose |
|------|---------|
| [main.py](remote_server/main.py) | FastAPI + FastMCP server with SSE |
| [Dockerfile](remote_server/Dockerfile) | Container configuration |
| [requirements.txt](remote_server/requirements.txt) | Python dependencies |

## Implementation Notes

The server uses:
- **FastAPI** as the ASGI framework
- **FastMCP** with `mcp.sse_app()` mounted at `/sse`
- **uvicorn** to run the server
- Must bind to `0.0.0.0` and use `PORT` env var for Cloud Run

## Future Migration Path

1. ✅ **Phase 1**: Hello world MCP on Cloud Run
2. **Phase 2**: Migrate read-only tools (`search_library`, etc.)
3. **Phase 3**: BigQuery integration for library data
4. **Phase 4**: Vertex AI embeddings for semantic search
5. **Phase 5**: Hybrid local/remote for write operations

> [!NOTE]
> Write operations like `create_playlist` require local MusicKit access and will remain on the local `edge` CLI.
