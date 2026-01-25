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

Deployment is handled via `gcloud run`. See the root [REMOTE_MCP.md](../REMOTE_MCP.md) for full deployment instructions.
