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
