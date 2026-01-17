# Cloud Crate Edge

This directory contains the "Edge" component of Cloud Crate: a native Swift executable that interfaces with Apple's MusicKit to export your local library metadata.

## Purpose
The primary goal of this tool is to securely access your Apple Music library, extract relevant metadata (tracks, albums, artists, play counts), and serialize it into a standard JSON format that the backend can consume.

## Purpose
The primary goal of this tool is to provide a native bridge to Apple Music (MusicKit). It supports:
1. **Exporting Library**: Extracting metadata for ingestion.
2. **Creating Playlists**: Creating new playlists via the Apple Music API (`MusicDataRequest`).
3. **Searching Catalog**: Searching the global Apple Music catalog.

## Structure
- **Package.swift**: Swift Package Manager configuration.
- **Sources/edge/edge.swift**: Main logic using `SwiftArgumentParser` and `MusicKit`.

## Usage

**Prerequisites:**
- macOS with a configured Music app library and Apple Music account.
- Swift installed (via Xcode).

**Building and Running:**
You can use the helper script from the `edge` directory:

```bash
./build_and_run.sh
```

Or run manually with swift:

```bash
swift run edge --help
```

### Commands

#### 1. Export Library
Exports your local library metadata to JSON.
```bash
swift run edge export-library
```
*Note: This is no longer the default command.*

#### 2. Search Catalog
Search for songs in the Apple Music Global Catalog.
```bash
swift run edge search-catalog --query "Taylor Swift" --limit 5
```

#### 3. Create Playlist
Creates a playlist from a JSON definition file.
```bash
swift run edge create-playlist --input-file input.json
```

**Example `input.json`:**
```json
{
  "name": "My New Playlist",
  "description": "Created via Cloud Crate",
  "tracks": [
    {
      "id": "i.12345", 
      "type": "library",
      "title": "Local Song",
      "artist": "Local Artist"
    },
    {
      "id": "12345678", 
      "type": "catalog",
      "title": "Catalog Song",
      "artist": "Catalog Artist"
    }
  ]
}
```

**Permissions & Known Issues in Headless Environments:**
- All commands require `MusicAuthorization` (TCC Permission).
- In a headless environment (like an Agent session), triggering the permission prompt causes a `SIGABRT` crash.
- **Solution**: Run the tool manually in a terminal one time to approve permissions.

## Output
The tool writes a JSON file to:
`../crate/my_library.json` (for export command)
stdout (for search and playlist commands)

