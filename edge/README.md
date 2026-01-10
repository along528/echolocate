# Cloud Crate Edge

This directory contains the "Edge" component of Cloud Crate: a native Swift executable that interfaces with Apple's MusicKit to export your local library metadata.

## Purpose
The primary goal of this tool is to securely access your Apple Music library, extract relevant metadata (tracks, albums, artists, play counts), and serialize it into a standard JSON format that the backend can consume.

## Structure
- **Package.swift**: Swift Package Manager configuration.
- **Sources/edge/edge.swift**: Main application logic.
    - Requests MusicKit authorization.
    - Fetches library songs.
    - Maps `MusicKit.Song` to `TrackOutput` JSON structure.
    - Exports to `../crate/my_library.json`.

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
swift run edge
```

**Permissions:**
On the first run, macOS will prompt you to grant the application access to "Media & Apple Music". You must approve this for the export to work.

## Output
The tool writes a JSON file to:
`../crate/my_library.json`

**Data Fields:**
- `id`: Unique track ID
- `title`: Song title
- `artist_name`: Artist name
- `album_title`: Album name
- `play_count`: Total play count
- `last_played_at`: ISO 8601 timestamp

