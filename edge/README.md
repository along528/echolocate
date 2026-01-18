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
You should use the helper script from the `edge` directory. This script handles building using `xcodebuild` (required for proper signing) and packaging the application.

```bash
./build.sh
```

The output application will be located at `edge/edge.app`.

### Editing in Xcode
To edit the project in Xcode (with full IDE support):
1. Open Xcode.
2. Select "Open Other..." (or File > Open).
3. Navigate to and select the `edge/Package.swift` file (or the `edge` folder).
4. Xcode will open it as a Swift Package.

**To configure Signing:**
1. Click on the root `edge` package icon in the Project Navigator.
2. Select the `edge` executable target in the main view.
3. Switch to the `Signing & Capabilities` tab.
4. Ensure your Team and Signing Certificate are selected.

### Commands

#### 1. Export Library
Exports your local library metadata to JSON.
```bash
./edge.app/Contents/MacOS/edge export-library
```

#### 2. Search Catalog
Search for resources in the Apple Music Global Catalog.
```bash
# Search for songs (default)
./edge.app/Contents/MacOS/edge search-catalog --query "Taylor Swift" --limit 5

# Search for artists
./edge.app/Contents/MacOS/edge search-catalog --query "Taylor Swift" --types artists --limit 1

# Search for albums
./edge.app/Contents/MacOS/edge search-catalog --query "1989" --types albums
```

#### 3. Get Catalog Resource
Fetch details for a specific catalog resource.
- **Artists**: Returns top songs.
- **Albums**: Returns tracks.
```bash
# Get Artist Top Songs
./edge.app/Contents/MacOS/edge get-catalog-resource --id <ARTIST_ID> --type artist

# Get Artist Top Albums
./edge.app/Contents/MacOS/edge get-catalog-resource --id <ARTIST_ID> --type artist-albums

# Get Album Tracks
./edge.app/Contents/MacOS/edge get-catalog-resource --id <ALBUM_ID> --type album
```

#### 4. Create Playlist
Creates a playlist from a JSON definition file.
```bash
./edge.app/Contents/MacOS/edge create-playlist --input-file input.json
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

