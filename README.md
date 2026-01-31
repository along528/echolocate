# Cloud Crate

Cloud Crate is an AI-powered music library manager that connects your personal music collection (via Apple Music) to Large Language Models (LLMs) using the Model Context Protocol (MCP).

It allows you to "chat" with your music library—asking for play history, analyzing taste profiles, searching by vibe or genre, and discovering forgotten gems.

## Architecture

The project consists of a central MCP server and a vector service:

1.  **Cloud Crate MCP (`mcp/`)**: The main Python server running on Cloud Run. It delegates to:
    - **Apple Crate**: Interfaces with Apple Music API.
    - **Record Crate**: Interfaces with Discogs API.
    - **Echo Locate**: Interfaces with Vector DBs for sonic pathfinding.

2.  **Vector Service (`vector_service/`)**: A dedicated service hosting DuckDB for embedding storage and similarity search.

## Quick Start

### 1. Deploy All Services

Use the top-level deployment script to deploy both the Vector Service and the MCP Server.

```bash
./deploy.sh
```

This will:
1. Deploy `vector_service` to Cloud Run.
2. Capture its URL.
3. Deploy `mcp` server to Cloud Run, linked to the Vector Service.

### 2. Connect to AI Client

Configure your MCP client (e.g., Claude Desktop or generic client) to connect to the remote SSE endpoint.

**Claude Desktop Config (`~/Library/Application Support/Claude/claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "cloud-crate-remote": {
      "url": "https://cloud-crate-mcp-[YOUR_HASH].us-central1.run.app/sse"
    }
  }
}
```

## Features
- **Semantic Search**: Find songs by lyrics or vibe.
- **Text Search**: Search library and Apple Music Catalog for artists, albums, and tracks.
- **Contextual Awareness**: detailed play counts and dates.
- **Album aggregation**: View stats and tracks at the album level.
- **Playlist Management**: Create new playlists from your library directly in Apple Music via Native APIs.
- **Vibe Steering**: Generate playlists that Sonically interpolate between two tracks, steering through a specific "vibe" or track.

## Directory Structure

- `mcp/`: Main MCP server code (Python).
- `vector_service/`: Vector database service (DuckDB + FastAPI).
- `data/`: Storage for generated embeddings and DB files.

## Documentation
- [MCP Server Details](mcp/README.md)
- [Remote Setup Guide](REMOTE_MCP.md)
- [Vector Service](vector_service/README.md)
