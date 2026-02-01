# Cloud Crate

Cloud Crate is a music library management and discovery system powered by MCP (Model Context Protocol), Google Cloud Run, DuckDB, and Vector Search. This repository contains the code for the backend MCP server, the vector search service, and the audio embedding pipeline.

## Architecture

![Architecture](https://via.placeholder.com/800x400?text=Cloud+Crate+Architecture)

- **`mcp/`**: A remote MCP server that exposes tools for Apple Music, Discogs, and Vector Search. It handles authentication and orchestrates requests.
- **`vector/`**: A high-performance vector search service using DuckDB. It serves audio embeddings and supports sonic interpolation.
- **`embeddings/`**: Scripts for processing audio files, generating embeddings (using generic audio transformers), and building the DuckDB database.
- **`crate/`**: Local music directory (synced or managed via other means).

## Features

- **Apple Music**: Search catalog, manage library, create playlists.
- **Discogs**: Search database, fetch release details, view wantlist.
- **Echo Locate**: "Sonic" search finding similar tracks based on audio analysis, and "Sonic Interpolation" to generate smooth playlists between two tracks.
- **Strict Naming**: All MCP tools are namespaced (`apple_*`, `discogs_*`, `echolocate_*`).

## Deployment

The entire stack is designed to be deployed to Google Cloud Run.

### Prerequisites
- Google Cloud SDK (`gcloud`) installed and authenticated.
- A Google Cloud Project with Cloud Run and Secret Manager enabled.
- A GCS bucket containing your `cloudcrate.duckdb` file (for the vector service).

### Deploying components
You can deploy both services at once using the top-level deployment script:

```bash
./deploy.sh
```

This script will:
1. Deploy the `cloud-crate-vector` service (requires a GCS bucket with `cloudcrate.duckdb`).
2. Deploy the `cloud-crate-mcp` service, automatically linking it to the vector service.

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

## Verification
Use the provided scripts to verify deployments remotely:
- `python vector/verify_service.py <VECTOR_URL>`
- `python mcp/verify_auth.py <MCP_URL>`
