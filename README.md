# Cloud Crate

Cloud Crate is an AI-powered music library manager that connects your personal music collection (via Apple Music) to Large Language Models (LLMs) using the Model Context Protocol (MCP).

It allows you to "chat" with your music library—asking for play history, analyzing taste profiles, searching by vibe or genre, and discovering forgotten gems.

## Architecture

The project consists of two main components:

1.  **Edge (macOS / Swift)**: A native tool that interfaces with MusicKit to export your library data securely.
    - [Read more in edge/README.md](edge/README.md)

2.  **Backend (Python / MCP)**: A server that ingests the library data and exposes it as tools to AI agents.
    - [Read more in backend/README.md](backend/README.md)

## Quick Start

### 1. Export Library
Run the Swift exporter to generate your library snapshot.

```bash
cd edge
./build.sh
cd ..
```
This creates `crate/my_library.json`.

### 2. Run Backend Server
Install dependencies and start the MCP server.

> [!IMPORTANT]
> You MUST use the `.venv` virtual environment for all python commands to ensure dependencies are found.


```bash
# Setup Environment (if not already done)
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Run Local Server
python backend/local_server.py
```

### 3. Connect to AI Client
Configure your MCP client (e.g., Claude Desktop) to run the server script.

**Claude Desktop Config (`~/Library/Application Support/Claude/claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "cloud-crate": {
      "command": "/ABSOLUTE/PATH/TO/PROJECT/.venv/bin/python3",
      "args": [
        "/ABSOLUTE/PATH/TO/PROJECT/backend/local_server.py"
      ]
    }
  }
}
```

## Features
- **Semantic Search**: Find songs by lyrics or vibe (Cloud mode).
- **Text Search**: Search library and Apple Music Catalog for artists, albums, and tracks.
- **Contextual Awareness**: detailed play counts and dates.
- **Album aggregation**: View stats and tracks at the album level.
- **Playlist Management**: Create new playlists from your library directly in Apple Music via Native APIs.

## Remote MCP Server (Cloud Run)

A hello world MCP server is deployed on Google Cloud Run for remote access.

| Endpoint | URL |
|----------|-----|
| **Health Check** | https://mcp-helloworld-403961692263.us-central1.run.app/ |
| **MCP SSE** | https://mcp-helloworld-403961692263.us-central1.run.app/sse |

**Claude Desktop Config (remote)**:
```json
{
  "mcpServers": {
    "cloud-run-hello": {
      "url": "https://mcp-helloworld-403961692263.us-central1.run.app/sse"
    }
  }
}
```

See [REMOTE_MCP.md](REMOTE_MCP.md) for full details.

