import ArgumentParser
import MusicKit
import Foundation

// MARK: - Data Structures
struct TrackOutput: Codable {
    let id: String
    let title: String
    let artist_name: String
    let play_count: Int
    let last_played_at: String?
    let editorial_summary: String?
    let album_title: String?
}

struct SearchResult: Codable {
    let id: String
    let title: String
    let artist: String
    let album: String?
}

struct PlaylistInput: Codable {
    let name: String
    let description: String?
    let tracks: [TrackInput]
}

struct TrackInput: Codable {
    let id: String
    let type: String // "library" or "catalog"
    let title: String
    let artist: String
}

// MARK: - CLI
@main
struct EdgeCLI: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        abstract: "Cloud Crate Edge Interface",
        subcommands: [ExportLibrary.self, CreatePlaylist.self, SearchCatalog.self]
        // No default subcommand to avoid expensive export on accidental run
    )
}

struct ExportLibrary: AsyncParsableCommand {
    static let configuration = CommandConfiguration(abstract: "Export local library to JSON")

    func run() async throws {
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed.")
            throw ExitCode(1)
        }

        var request = MusicLibraryRequest<Song>()
        request.limit = 100000000
        let response = try await request.response()
        
        var output: [TrackOutput] = []
        for song in response.items {
            let lastPlayed = song.lastPlayedDate?.ISO8601Format()
            output.append(TrackOutput(
                id: song.id.rawValue,
                title: song.title,
                artist_name: song.artistName,
                play_count: song.playCount ?? 0,
                last_played_at: lastPlayed,
                editorial_summary: nil,
                album_title: song.albumTitle
            ))
        }
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(output)
        
        // Output path is currently hardcoded relative to project structure for legacy reasons
        let fileURL = URL(fileURLWithPath: "/Users/alex.long/Projects/cloud-crate/crate/my_library.json")
        try data.write(to: fileURL)
        print("Library exported to: \(fileURL.path)")
    }
}

struct SearchCatalog: AsyncParsableCommand {
    static let configuration = CommandConfiguration(abstract: "Search Apple Music Catalog")
    
    @Option(name: .long, help: "Search query")
    var query: String
    
    @Option(name: .long, help: "Max results")
    var limit: Int = 5

    func run() async throws {
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed.")
            throw ExitCode(1)
        }

        var request = MusicCatalogSearchRequest(term: query, types: [Song.self])
        request.limit = limit
        let response = try await request.response()
        
        var results: [SearchResult] = []
        let songs = response.songs
        for song in songs {
            results.append(SearchResult(
                id: song.id.rawValue, 
                title: song.title, 
                artist: song.artistName, 
                album: song.albumTitle
            ))
        }
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(results)
        print(String(data: data, encoding: .utf8)!)
    }
}

struct CreatePlaylist: AsyncParsableCommand {
    static let configuration = CommandConfiguration(abstract: "Create a playlist")
    
    @Option(name: .long, help: "Path to JSON input file")
    var inputFile: String

    func run() async throws {
        // MusicKit Authorization is REQUIRED for MusicDataRequest
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed. Cannot use Apple Music API.")
            throw ExitCode(1)
        }

        let fileURL = URL(fileURLWithPath: inputFile)
        let data = try Data(contentsOf: fileURL)
        let input = try JSONDecoder().decode(PlaylistInput.self, from: data)
        
        printToStderr("Creating playlist '\(input.name)' via Apple Music API (MusicKit)...")
        
        // 1. Prepare Track Relationship Data
        var tracksData: [[String: String]] = []
        for track in input.tracks {
            var type = "songs" // Default to catalog song
            if track.type == "library" || track.id.starts(with: "i.") {
                type = "library-songs"
            }
            tracksData.append([
                "id": track.id,
                "type": type
            ])
        }
        
        // 2. Build Request Body
        let attributes: [String: Any] = [
            "name": input.name,
            "description": input.description ?? "Created via Cloud Crate"
        ]
        
        let relationships: [String: Any] = [
            "tracks": [
                "data": tracksData
            ]
        ]
        
        let payload: [String: Any] = [
            "attributes": attributes,
            "relationships": relationships
        ]
        
        let jsonData = try JSONSerialization.data(withJSONObject: payload)
        
        // 3. Create MusicDataRequest
        let url = URL(string: "https://api.music.apple.com/v1/me/library/playlists")!
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "POST"
        urlRequest.httpBody = jsonData
        
        let musicRequest = MusicDataRequest(urlRequest: urlRequest)
        
        // 4. Send Request
        do {
            let response = try await musicRequest.response()
            
            // 5. Parse Response for ID
            // Response is standard JSONAPI. data: [ { id: "...", ... } ]
            // POST usually returns the created resource
            
             if let jsonObject = try JSONSerialization.jsonObject(with: response.data) as? [String: Any],
               let dataArray = jsonObject["data"] as? [[String: Any]],
               let firstItem = dataArray.first,
               let id = firstItem["id"] as? String {
                
                let output = ["status": "success", "playlistId": id, "addedToLibraryCount": "0"]
                let outputJson = try JSONEncoder().encode(output)
                print(String(data: outputJson, encoding: .utf8)!)
                
            } else {
                printToStderr("Error: Unexpected response format from Apple Music API.")
                printToStderr("Response: \(String(data: response.data, encoding: .utf8) ?? "")")
                throw ExitCode(1)
            }
            
        } catch {
            printToStderr("Error creating playlist: \(error)")
            // Decode error response if possible
            if let musicError = error as? MusicDataRequest.Error {
                 printToStderr("Status Code: \(musicError.status)")
            }
            throw ExitCode(1)
        }
    }
}
// Remove runAppleScript helper if no longer used, or keep for potential fallbacks? 
// User explicit requested MusicKit, so removing ambiguity.

