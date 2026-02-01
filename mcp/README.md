# Cloud Crate MCP Server

A specialized Model Context Protocol (MCP) server for music discovery and library management. It acts as the central brain, connecting to Apple Music, Discogs, and the Cloud Crate Vector Service.

## Tools

The server exposes the following tools to the LLM, all strictly namespaced:

### 🍎 Apple Music (`apple_*`)
- `apple_search_catalog(query)`: Search the global Apple Music catalog.
- `apple_search_library(query)`: Search your personal library (Songs).
- `apple_get_track_context(track_id)`: Get detailed metadata for a specific track.
- `apple_create_playlist(name, track_ids)`: Create a new playlist with given tracks.

### 💿 Discogs (`discogs_*`)
- `discogs_search(query, format)`: Search for releases (Vinyl, Master, etc.).
- `discogs_get_release(release_id)`: Get detailed info about a release (tracklist, year, etc.).
- `discogs_get_versions(master_id)`: List all versions of a master release.
- `discogs_get_wantlist(page)`: Browse your Discogs wantlist.

### 🦇 Echo Locate (`echolocate_*`)
- `echolocate_similar(track_id)`: Find tracks sonically similar to a given track.
- `echolocate_interpolate(track_id_1, track_id_2, method)`: Generate a path of songs connecting two tracks.
- `echolocate_generate_playlist(track_id_1, track_id_2)`: Same as interpolate but formatted for playlist creation.
- `echolocate_sample(limit, random)`: Get a random sample of tracks from the vector DB.

## Configuration

The server requires several secrets, managed via **Google Secret Manager**. Ensure the following secrets exist:

| Secret Name | Description |
|-------------|-------------|
| `MCP_AUTH_SECRET` | Password/Token for MCP client authentication (if enabled). |
| `MCP_CLIENT_ID` | Allowed Client ID for auth. |
| `APPLE_TEAM_ID` | Apple Developer Team ID. |
| `APPLE_KEY_ID` | Apple Music Key ID. |
| `APPLE_PRIVATE_KEY` | Apple Music Private Key (PEM format). |
| `APPLE_MUSIC_USER_TOKEN`| User-specific token (generated via `/apple-auth`). |
| `DISCOGS_TOKEN` | Personal Access Token for Discogs API. |

### Environment Variables
- `VECTOR_SERVICE_URL`: URL of the deployed `cloud-crate-vector` service.
- `GOOGLE_CLOUD_PROJECT`: GCP Project ID (for Secret Manager).

## Deployment

Deploy using the script in this directory (or the root `deploy.sh`):

```bash
./deploy.sh
```

This will:
1. Build the Docker container.
2. Push to Google Container Registry (GCR) or Artifact Registry.
3. Deploy to Cloud Run as `cloud-crate-mcp`.

## Authentication Flow

1. **Client Auth**: The MCP client/user must authenticate via the `/authorize` flow (OAuth2-like) or provide a valid Session Cookie.
2. **Apple Music Auth**: To use user-library features, visit `/apple-auth` to log in with your Apple ID. This stores the `Music-User-Token`.
