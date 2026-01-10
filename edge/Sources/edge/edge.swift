import MusicKit
import Foundation

struct TrackOutput: Codable {
    let id: String
    let title: String
    let artist_name: String
    let play_count: Int
    let last_played_at: String? // ISO8601
    let editorial_summary: String?
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
            request.limit = 100 
            
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
                    editorial_summary: nil // To be filled by backend LLM
                )
                output.append(track)
            }
            
            // 4. Output JSON
            let encoder = JSONEncoder()
            encoder.outputFormatting = .prettyPrinted
            let data = try encoder.encode(output)
            
            if let jsonString = String(data: data, encoding: .utf8) {
                print(jsonString)
            }
            
        } catch {
            print("Error fetching library: \(error)")
            exit(1)
        }
    }
}
