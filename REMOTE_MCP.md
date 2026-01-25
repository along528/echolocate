# Cloud Run Remote MCP Server Deployment

Deploy a "hello world" MCP server to Google Cloud Run as a foundation for eventually hosting the full Cloud Crate backend remotely.

## Background

The current Cloud Crate architecture uses a **local** Python MCP server (`backend/local_server.py`) that runs on the user's Mac. This plan sets up a **remote** MCP server pattern on Cloud Run, starting with a simple "hello world" implementation before migrating the full Cloud Crate functionality.

### Why Cloud Run for MCP?

- **SSE/HTTP Transport**: Cloud Run supports Server-Sent Events (SSE) and HTTP streaming, which are required for remote MCP servers
- **Serverless**: No infrastructure management, automatic scaling
- **Cost-effective**: Pay only for requests, ideal for personal tools
- **Integration**: Native GCP ecosystem (BigQuery, Vertex AI) for future Cloud Crate features

## User Review Required

> [!IMPORTANT]
> **GCP Project Setup**: You'll need a Google Cloud project with billing enabled. If you don't have one, we'll need to create it or use an existing project.

> [!IMPORTANT]
> **MCP Client Configuration**: After deployment, you'll need to configure your MCP client (Claude Desktop, Cline, etc.) to connect to the remote server URL instead of the local stdio transport.

## Proposed Changes

### Architecture Overview

```
┌─────────────────────┐         HTTPS/SSE          ┌──────────────────────┐
│   MCP Client        │ ──────────────────────────▶│   Cloud Run          │
│   (Claude Desktop)  │                            │   MCP Server         │
└─────────────────────┘                            │   (Python + FastMCP) │
                                                   └──────────────────────┘
```

**Key Difference from Local Setup**:
- **Local**: Uses `stdio` transport (stdin/stdout piping)
- **Remote**: Uses `SSE` or `Streamable HTTP` transport (HTTP endpoints)

---

### Remote MCP Server (Hello World)

#### [NEW] [remote_server/](file:///Users/alex.long/Projects/cloud-crate/remote_server/)

New directory for the Cloud Run MCP server.

#### [NEW] [main.py](file:///Users/alex.long/Projects/cloud-crate/remote_server/main.py)

Minimal MCP server using FastMCP with SSE transport:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Hello World MCP")

@mcp.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! This is coming from Cloud Run."

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

# For Cloud Run, we need to expose via HTTP
if __name__ == "__main__":
    mcp.run(transport="sse")
```

#### [NEW] [requirements.txt](file:///Users/alex.long/Projects/cloud-crate/remote_server/requirements.txt)

```
mcp>=1.0.0
uvicorn
starlette
```

#### [NEW] [Dockerfile](file:///Users/alex.long/Projects/cloud-crate/remote_server/Dockerfile)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Cloud Run sets PORT env var
ENV PORT=8080
EXPOSE 8080

# Run with uvicorn for production
CMD ["python", "main.py"]
```

---

### GCP Configuration

#### [NEW] [cloudbuild.yaml](file:///Users/alex.long/Projects/cloud-crate/remote_server/cloudbuild.yaml) (Optional)

For automated builds via Cloud Build:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/mcp-helloworld', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/mcp-helloworld']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'mcp-helloworld'
      - '--image'
      - 'gcr.io/$PROJECT_ID/mcp-helloworld'
      - '--region'
      - 'us-central1'
      - '--allow-unauthenticated'
images:
  - 'gcr.io/$PROJECT_ID/mcp-helloworld'
```

---

### Design Document Update

#### [MODIFY] [DESIGN.md](file:///Users/alex.long/Projects/cloud-crate/DESIGN.md)

Add a new section documenting the remote server architecture and deployment approach.

---

## Deployment Steps

### 1. Prerequisites

```bash
# Install gcloud CLI if not already installed
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login

# Set project (replace with your project ID)
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com
# Or for Artifact Registry (recommended):
gcloud services enable artifactregistry.googleapis.com
```

### 2. Build and Deploy

```bash
cd remote_server

# Build the container
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/mcp-helloworld

# Deploy to Cloud Run
gcloud run deploy mcp-helloworld \
  --image gcr.io/YOUR_PROJECT_ID/mcp-helloworld \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080
```

### 3. Configure MCP Client

After deployment, Cloud Run provides a URL like:
`https://mcp-helloworld-xxxxx-uc.a.run.app`

Configure your MCP client to connect using SSE transport:

**Claude Desktop (claude_desktop_config.json)**:
```json
{
  "mcpServers": {
    "cloud-run-hello": {
      "url": "https://mcp-helloworld-xxxxx-uc.a.run.app/sse"
    }
  }
}
```

---

## Verification Plan

### Automated Tests

1. **Local Docker Test**:
   ```bash
   cd remote_server
   docker build -t mcp-helloworld .
   docker run -p 8080:8080 mcp-helloworld
   # In another terminal, test the SSE endpoint
   curl http://localhost:8080/sse
   ```

2. **MCP Protocol Test** (after deployment):
   Create a simple Python client to verify the tools work:
   ```bash
   python verify_remote_mcp.py https://your-cloud-run-url.run.app/sse
   ```

### Manual Verification

1. **Deploy and Get URL**: After `gcloud run deploy`, note the service URL
2. **Configure Client**: Add the URL to your MCP client config
3. **Test Tools**: 
   - Ask Claude/LLM to use the `greet` tool with your name
   - Ask it to use the `add` tool to add two numbers
4. **Check Cloud Run Logs**: Verify requests appear in the Cloud Run console

---

## Future Migration Path

Once the hello world deployment is verified, the path to full Cloud Crate remote hosting:

1. **Phase 1** (This plan): Hello world MCP on Cloud Run ✓
2. **Phase 2**: Migrate read-only tools (`search_library`, `get_track_context`) to remote
3. **Phase 3**: Set up BigQuery and migrate library data to cloud
4. **Phase 4**: Add Vertex AI embeddings for semantic search
5. **Phase 5**: Handle write operations (playlist creation) - may require hybrid local/remote

> [!NOTE]
> Write operations like `create_playlist` will still need the local `edge` CLI to interact with Apple Music on the Mac. The remote server can orchestrate, but the actual MusicKit calls must happen locally.
