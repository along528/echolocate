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
- `search_apple_music(query)`: Search the global Apple Music Catalog for songs.
- `search_artist_top_songs(artist_name)`: Search for an artist and get their top songs.
- `search_artist_top_albums(artist_name)`: Search for an artist and get their top albums.
- `search_album_tracks(album_name, artist_name)`: Search for an album and get its tracks.
- `create_playlist(name, track_ids, confirm=False)`: 2-step process to create playlists.
    - Uses the **Native Native Playlist Bridge** (calling the `edge` Swift CLI via MusicKit API) to create playlists directly in Apple Music.
    - Supports both Local Library IDs (`library:ID`) and Global Catalog IDs (`catalog:ID`).


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

# Run playlist creation verification
.venv/bin/python backend/verify_playlist_creation.py
```
