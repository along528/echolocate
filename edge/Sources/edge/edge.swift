import MusicKit
import Foundation

struct TrackOutput: Codable {
    let id: String
    let title: String
    let artist_name: String
    let play_count: Int
    let last_played_at: String? // ISO8601
    let editorial_summary: String?
    let album_title: String?
}

@main
struct EdgeCLI {
    static func main() async {
        // 1. Request Authorization
        let status = await MusicAuthorization.request()
        
        guard status == .authorized else {
            print("Error: MusicKit authorization failed. Status: \(status)")
            print("Note: Run this tool from a context that allows Media Library access (e.g. Terminal with permissions).")
            exit(1)
        }
        
        let args = CommandLine.arguments
        
        // Mode selection
        if args.contains("-createPlaylist") {
            await createPlaylistMode(args: args)
        } else {
            await dumpLibraryMode()
        }
    }
    
    static func createPlaylistMode(args: [String]) async {
        guard let nameIndex = args.firstIndex(of: "-createPlaylist"),
              nameIndex + 1 < args.count,
              let tracksIndex = args.firstIndex(of: "-tracks"),
              tracksIndex + 1 < args.count else {
            print("Usage: edge -createPlaylist <name> -tracks <id1,id2,...>")
            exit(1)
        }
        
        let playlistName = args[nameIndex + 1]
        let trackIdsString = args[tracksIndex + 1]
        let trackIds = trackIdsString.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
        
        print("Creating playlist '\(playlistName)' with \(trackIds.count) tracks...")
        
        do {
            // 1. Create Playlist via API
            let createURL = URL(string: "https://api.music.apple.com/v1/me/library/playlists")!
            let createBody: [String: Any] = [
                "attributes": [
                    "name": playlistName,
                    "description": "Created via Cloud Crate"
                ]
            ]
            
            let createRequestData = try JSONSerialization.data(withJSONObject: createBody)
            
            var urlRequest = URLRequest(url: createURL)
            urlRequest.httpMethod = "POST"
            urlRequest.httpBody = createRequestData
            
            let request = MusicDataRequest(urlRequest: urlRequest)
            let response = try await request.response()
            
            guard let json = try JSONSerialization.jsonObject(with: response.data) as? [String: Any],
                  let data = json["data"] as? [[String: Any]],
                  let first = data.first,
                  let playlistId = first["id"] as? String else {
                print("Error: Could not parse playlist creation response.")
                print(String(data: response.data, encoding: .utf8) ?? "")
                exit(1)
            }
            
            print("Playlist created! ID: \(playlistId)")
            
            // 2. Add Tracks
            let tracksData = trackIds.map { ["id": $0, "type": "library-songs"] }
            let addBody = ["data": tracksData]
            let addRequestData = try JSONSerialization.data(withJSONObject: addBody)
            
            let addURL = URL(string: "https://api.music.apple.com/v1/me/library/playlists/\(playlistId)/tracks")!
            var addUrlRequest = URLRequest(url: addURL)
            addUrlRequest.httpMethod = "POST"
            addUrlRequest.httpBody = addRequestData
            
            let addRequest = MusicDataRequest(urlRequest: addUrlRequest)
            let addResponse = try await addRequest.response()
            
            // Attempt to get status code if possible, or rely on lack of error
            // MusicDataResponse usually has .urlResponse property which is URLResponse
            if let httpResponse = addResponse.urlResponse as? HTTPURLResponse {
                 if (200...299).contains(httpResponse.statusCode) {
                     print("Successfully added \(tracksData.count) tracks.")
                 } else {
                     print("Error adding tracks. Status: \(httpResponse.statusCode)")
                     print(String(data: addResponse.data, encoding: .utf8) ?? "")
                 }
            } else {
                // Determine success by lack of error or content?
                print("Tracks added (status code unavailable, but no error thrown).")
            }
            
        } catch {
            print("Error parsing/executing request: \(error)")
            exit(1)
        }
    }
    
    static func dumpLibraryMode() async {
        do {
            // 2. Query Library
            // Fetching a limit for MVP sanity, or all if feasible.
            // Paginating through library can be slow, let's try to get a reasonable batch.
            var request = MusicLibraryRequest<Song>()
            request.limit = 100000000
            
            // Debug version
             let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
             try? "Version 100000".write(to: URL(fileURLWithPath: "/Users/alex.long/Projects/cloud-crate/crate/edge_version.txt"), atomically: true, encoding: .utf8) 
            
            let response = try await request.response()
            let songs = response.items
            
            var output: [TrackOutput] = []
            
            // 3. Transform
            for song in songs {
                // Formatting date
                let lastPlayed: String? = song.lastPlayedDate?.ISO8601Format()
                

                 let track = TrackOutput(
                    id: song.id.rawValue,
                    title: song.title,
                    artist_name: song.artistName,
                    play_count: song.playCount ?? 0,
                    last_played_at: lastPlayed,
                    editorial_summary: nil, // To be filled by backend LLM
                    album_title: song.albumTitle
                )

                output.append(track)
            }
            
            // 4. Output JSON
            let encoder = JSONEncoder()
            encoder.outputFormatting = .prettyPrinted
            let data = try encoder.encode(output)
            
            // let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            // let fileURL = documentsPath.appendingPathComponent("my_library.json")
            let fileURL = URL(fileURLWithPath: "/Users/alex.long/Projects/cloud-crate/crate/my_library.json")
            
            try? "Version 500".write(to: URL(fileURLWithPath: "/Users/alex.long/Projects/cloud-crate/crate/edge_version.txt"), atomically: true, encoding: .utf8) 
            
            try data.write(to: fileURL)
            print("Library exported to: \(fileURL.path)")
            
            // Keep window open briefly if visible (hack for Finder)
            try? await Task.sleep(nanoseconds: 2 * 1_000_000_000)
            
        } catch {
            print("Error fetching library: \(error)")
            // Keep window open on error
            try? await Task.sleep(nanoseconds: 5 * 1_000_000_000)
            exit(1)
        }
    }
}
