# Cloud Crate MCP Server

This directory contains the Python codebase for the Cloud Crate Remote MCP server, designed to run on Google Cloud Run.

## Overview

The server implements the **Model Context Protocol (MCP)** using the `Streamable HTTP` transport strategy (SSE-compatible).

It delegates logic to specialized "Crates":
- **Apple Crate**: Auth and interaction with Apple Music (Catalog & Library).
- **Record Crate**: Interaction with Discogs (Releases & Wantlists).
- **Echo Locate**: Abstraction layer for Vector Services (Similarity & Interpolation).

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
   - SSE: `http://localhost:8080/sse`

## Deployment

Deploy using the script in this directory, or the top-level orchestrator.

```bash
./deploy.sh
```

**Service Name**: `cloud-crate-mcp`

### Configuration (Environment Variables & Secrets)

The server relies on **Google Secret Manager** for sensitive keys. Ensure the following secrets exist:
- `MCP_AUTH_SECRET`, `MCP_JWT_SECRET`
- `MCP_CLIENT_ID`
- `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`
- `DISCOGS_TOKEN`

Environment Variables:
- `VECTOR_SERVICE_URL`: URL of the primary vector service.
- `LIBRARY_VECTOR_URL` (Optional): specific URL for library vector service.
- `FMA_VECTOR_URL` (Optional): specific URL for FMA vector service.

## Integration Details

### Apple Music (`AppleCrate`)
- `search_apple_music`: Search Global Catalog.
- `search_library`: Search User's Personal Library.
- `create_playlist`: Create playlists for the authenticated user.

### Discogs (`RecordCrate`)
- `search_discogs`: Search Database.
- `get_discogs_versions`: List versions of a master release.
- `get_discogs_wantlist`: Fetch user wantlist.

### Vector Service (`EchoLocate`)
The server connects to `VECTOR_SERVICE_URL` (Cloud Run) to provide:
- **Similarity**: Find songs that "sound like" a target.
- **Interpolation**: Generate a playlist that smoothly transitions between two songs.
