# Cloud Crate Backend

This directory contains the Python-based backend service for Cloud Crate. It provides a Model Context Protocol (MCP) server that exposes your music library to AI agents.

## Components

### 1. Local MCP Server (`local_server.py`)
A FastMCP-based server that runs locally and serves data from `../crate/my_library.json`.

**Tools:**
- `search_library(query)`: Search for tracks by title or artist.
- `search_albums(query)`: Search for albums by title.
- `get_track_context(track_id)`: Get detailed metadata for a specific track.
- `get_album_context(album_name)`: Get aggregated statistics (plays, tracks) for an album.
- `get_rotation(category)`: content filtering (Heavy, Gold, Unplayed).
- `filter_by_date_range(start_date, end_date)`: Time-based library filtering.

### 2. Data Ingestion (Legacy/Cloud Mode)
- `ingest_library.py`: Uploads JSON library export to Google BigQuery.
- `generate_embeddings.py`: Generates vector embeddings for semantic search using Vertex AI.
- `setup_bq.py`: BigQuery schema setup.

## Setup & Running

**Prerequisites:**
- Python 3.10+
- Dependencies installed in the top-level virtual environment (`.venv`).

**Running the Server:**
The server is designed to be run as an MCP server, typically invoked by an AI client like Claude Desktop.

```bash
# From project root
.venv/bin/python backend/local_server.py
```

**Running Tests:**
verification scripts are available to test features without a client.
```bash
# Run album feature verification
.venv/bin/python backend/verify_albums.py
```
