# Apple Music API Integration Plan

This plan pivots Cloud Crate from using AppleScript automation to a robust **Native API** approach for playlist management.

## User Review Required

> [!IMPORTANT]
> **Developer Token Requirement (Potential)**: 
> If utilizing the Apple Music Web API is necessary (because native macOS MusicKit is read-only), a **Developer Token** (JWT) signed by an Apple Developer Account key is required. 
> *Current Strategy*: We will first attempt to use the local **MusicKit** framework via the Swift `edge` component. If that fails, we will discuss the Developer Token requirement.

## Proposed Changes

### 1. Architecture Update
- **Old Flow**: Python -> AppleScript (automating Music.app UI).
- **New Flow**: Python -> `edge` CLI (Swift) -> MusicKit (System Framework).

### 2. Component Specifications

#### A. Edge CLI (Swift)
- **Location**: `edge/`
- **New Command**: `search-catalog`
  - **Arguments**: `--query <string>`, `--limit <int>`
  - **Logic**: Use `MusicCatalogSearchRequest` to find songs in the global Apple Music catalog.
  - **Output**: JSON list of tracks with `id` (CatalogID), `title`, `artist`, `album`.

- **New Command**: `create-playlist`
  - **Arguments**: 
    - `--input-file <path>`: Path to a JSON file containing playlist details.
  - **Input JSON Format**:
    ```json
    {
      "name": "Playlist Name",
      "description": "Optional Description",
      "tracks": [
        {"id": "String", "type": "library|catalog"} 
      ]
    }
    ```
  - **Logic**:
    1. Parse JSON input.
    2. Request MusicKit authorization.
    3. Iterate through tracks:
        - If `type == 'library'`: Find in local library.
        - If `type == 'catalog'`: 
            - Attempt to find in local library first (by CatalogID matching).
            - If not found, queue for addition.
    4. **Add to Library logic**: For catalog tracks not in library, use `MusicLibrary.shared.add(items:)` to add them. Use a "Cloud Crate Imports" folder or similar if organization is needed, or just add to library.
    5. **Create/Update Playlist**: Use `MusicLibrary.shared.createPlaylist` with the mixed list of items (Library items and newly added Catalog items).
  - **Output**: JSON to stdout indicating success, count of tracks added to library, and final playlist ID.

#### B. Backend Bridge (Python)
- **Location**: `backend/local_server.py`
- **New Tool**: `search_apple_music(query, limit)`
  - Calls `subprocess.run(["./edge", "search-catalog", ...])`.
  - Returns formatted string for LLM.
- **Updated Tool**: `create_playlist(name, track_ids)`
  - Needs to distinguish between Library IDs and Catalog IDs. 
  - *Strategy*: `search_library` returns Library IDs (integers/UUIDs). `search_apple_music` returns Catalog IDs (usually integers or specific string formats). 
  - The tool should accept a list that might contain both. 
  - We might need to update the tool signature or internal logic to guess the type, or update `search_` tools to return a typed ID (e.g., `lib:123` vs `cat:123`).
  - *Decision*: Update tool to accept specific ID format or infer. For now, assume simple string IDs. The `edge` CLI will try to resolve.

### 3. File Changes

#### [MODIFY] [edge/Package.swift](file:///Users/alex.long/Projects/cloud-crate/edge/Package.swift)
- Add `swift-argument-parser` dependency.

#### [MODIFY] [edge/Sources/edge/edge.swift](file:///Users/alex.long/Projects/cloud-crate/edge/Sources/edge/edge.swift)
- Implement `SearchCatalog` subcommand using `MusicCatalogSearchRequest`.
- Implement `CreatePlaylist` subcommand with "Add to Library" fallback.

#### [MODIFY] [backend/local_server.py](file:///Users/alex.long/Projects/cloud-crate/backend/local_server.py)
- Add `search_apple_music` tool.
- Update `create_playlist` to construct the unified JSON payload for `edge`.

## Verification Plan

### Automated Tests
- **[NEW] `backend/verify_catalog_search.py`**:
    - Calls `search_apple_music` mock/CLI.
    - Verifies we get results from outside the library.
- **[UPDATE] `backend/verify_native_playlist.py`**: 
    - Add test case: "Create playlist with 1 Library track and 1 Catalog track (not in library)".
    - Verify track was added to library (check play count/date is empty/new) and is in the playlist.

### Manual Verification
1. **Search**: Ask "Find 'Despacito' on Apple Music".
2. **Mix Playlist**: Ask "Make a playlist with my favorite song 'Time' and that 'Despacito' song you found."
3. **Verify**: Check Apple Music. 'Despacito' should be in the playlist and added to the library (if it wasn't there).
