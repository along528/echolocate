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
        subcommands: [ExportLibrary.self, CreatePlaylist.self, SearchCatalog.self, GetCatalogResource.self, GetCatalogCharts.self]
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
    
    @Option(name: .long, help: "Types to search (songs, artists, albums)")
    var types: String = "songs"

    func run() async throws {
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed.")
            throw ExitCode(1)
        }
        
        var searchTypes: [MusicCatalogSearchable.Type] = []
        let typeStrings = types.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        
        if typeStrings.contains("songs") { searchTypes.append(Song.self) }
        if typeStrings.contains("artists") { searchTypes.append(Artist.self) }
        if typeStrings.contains("albums") { searchTypes.append(Album.self) }
        if typeStrings.contains("labels") { searchTypes.append(RecordLabel.self) }
        
        if searchTypes.isEmpty && !typeStrings.contains("genres") { searchTypes = [Song.self] }

        var results: [SearchResult] = []

        // Standard MusicKit Search
        if !searchTypes.isEmpty {
            var request = MusicCatalogSearchRequest(term: query, types: searchTypes)
            request.limit = limit
            let response = try await request.response()
            
            if searchTypes.contains(where: { $0 == Song.self }) {
                for song in response.songs {
                    results.append(SearchResult(
                        id: song.id.rawValue, 
                        title: song.title, 
                        artist: song.artistName, 
                        album: song.albumTitle
                    ))
                }
            }
            
            if searchTypes.contains(where: { $0 == Artist.self }) {
                for artist in response.artists {
                    results.append(SearchResult(
                        id: artist.id.rawValue,
                        title: artist.name,
                        artist: artist.name,
                        album: nil
                    ))
                }
            }
            
            if searchTypes.contains(where: { $0 == Album.self }) {
                for album in response.albums {
                    results.append(SearchResult(
                        id: album.id.rawValue,
                        title: album.title,
                        artist: album.artistName,
                        album: album.title
                    ))
                }
            }
            
            if searchTypes.contains(where: { $0 == RecordLabel.self }) {
                for label in response.recordLabels {
                    results.append(SearchResult(
                        id: label.id.rawValue,
                        title: label.name,
                        artist: "Record Label", 
                        album: nil
                    ))
                }
            }
        }
        
        // Manual Genre Search: Fetch all genres and filter locally
        if typeStrings.contains("genres") {
            let storefront = try await MusicDataRequest.currentCountryCode
            let url = URL(string: "https://api.music.apple.com/v1/catalog/\(storefront)/genres")!
            let dataRequest = MusicDataRequest(urlRequest: URLRequest(url: url))
            let dataResponse = try await dataRequest.response()
            
            if let json = try JSONSerialization.jsonObject(with: dataResponse.data) as? [String: Any],
               let dataArray = json["data"] as? [[String: Any]] {
                
                let lowerQuery = query.lowercased()
                
                // Helper to process genres recursively (if simple flattening is needed)
                // For now, just top level to avoid complexity
                for item in dataArray {
                    if let id = item["id"] as? String,
                       let attributes = item["attributes"] as? [String: Any],
                       let name = attributes["name"] as? String {
                        
                        // Simple substring match
                        if name.lowercased().contains(lowerQuery) {
                            results.append(SearchResult(
                                id: id,
                                title: name,
                                artist: "Genre",
                                album: nil
                            ))
                        }
                    }
                }
            }
        }
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(results)
        print(String(data: data, encoding: .utf8)!)
    }
}

struct GetCatalogResource: AsyncParsableCommand {
    static let configuration = CommandConfiguration(abstract: "Get details for a catalog resource (artist/album)")
    
    @Option(name: .long, help: "Resource ID")
    var id: String
    
    @Option(name: .long, help: "Resource Type (artist, album, song)")
    var type: String
    
    @Option(name: .long, help: "Limit for tracks/songs")
    var limit: Int = 5
    
    func run() async throws {
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed.")
            throw ExitCode(1)
        }
        
        var results: [SearchResult] = []
        
        if type == "artist" {
            var request = MusicCatalogResourceRequest<Artist>(matching: \.id, equalTo: MusicItemID(id))
            request.properties = [.topSongs]
            request.limit = limit
            let response = try await request.response()
            
            if let artist = response.items.first, let topSongs = artist.topSongs {
                for song in topSongs {
                    results.append(SearchResult(
                        id: song.id.rawValue,
                        title: song.title,
                        artist: song.artistName,
                        album: song.albumTitle
                    ))
                }
            }
        } else if type == "artist-albums" {
             var request = MusicCatalogResourceRequest<Artist>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.albums]
             request.limit = limit
             let response = try await request.response()
             
             if let artist = response.items.first, let albums = artist.albums {
                 for album in albums {
                      results.append(SearchResult(
                         id: album.id.rawValue,
                         title: album.title,
                         artist: album.artistName,
                         album: album.title
                     ))
                 }
             }
        } else if type == "album" {
            var request = MusicCatalogResourceRequest<Album>(matching: \.id, equalTo: MusicItemID(id))
            request.properties = [.tracks]
            let response = try await request.response()
            
            if let album = response.items.first, let tracks = album.tracks {
                for track in tracks {
                    if case let .song(song) = track {
                         results.append(SearchResult(
                            id: song.id.rawValue,
                            title: song.title,
                            artist: song.artistName,
                            album: song.albumTitle
                        ))
                    }
                }
            }
        } else if type == "record-label-latest" {
             var request = MusicCatalogResourceRequest<RecordLabel>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.latestReleases]
             request.limit = limit
             let response = try await request.response()
             
             if let label = response.items.first, let albums = label.latestReleases {
                 for album in albums {
                      results.append(SearchResult(
                         id: album.id.rawValue,
                         title: album.title,
                         artist: album.artistName,
                         album: album.title
                     ))
                 }
             }
        } else if type == "record-label-top" {
             var request = MusicCatalogResourceRequest<RecordLabel>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.topReleases]
             request.limit = limit
             let response = try await request.response()
             
             if let label = response.items.first, let albums = label.topReleases {
                 for album in albums {
                      results.append(SearchResult(
                         id: album.id.rawValue,
                         title: album.title,
                         artist: album.artistName,
                         album: album.title
                     ))
                 }
             }
        } else if type == "song" {
             var request = MusicCatalogResourceRequest<Song>(matching: \.id, equalTo: MusicItemID(id))
             let response = try await request.response()
             
             if let song = response.items.first {
                 results.append(SearchResult(
                    id: song.id.rawValue,
                    title: song.title,
                    artist: song.artistName,
                    album: song.albumTitle
                ))
             }
        } else if type == "song-genres" {
             var request = MusicCatalogResourceRequest<Song>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.genres]
             let response = try await request.response()
             
             if let song = response.items.first, let genres = song.genres {
                 for genre in genres {
                     results.append(SearchResult(
                        id: genre.id.rawValue,
                        title: genre.name,
                        artist: "Genre",
                        album: nil
                    ))
                 }
             }
        } else if type == "album-genres" {
             var request = MusicCatalogResourceRequest<Album>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.genres]
             let response = try await request.response()
             
             if let album = response.items.first, let genres = album.genres {
                 for genre in genres {
                     results.append(SearchResult(
                        id: genre.id.rawValue,
                        title: genre.name,
                        artist: "Genre",
                        album: nil
                    ))
                 }
             }
        } else if type == "artist-genres" {
             var request = MusicCatalogResourceRequest<Artist>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.genres]
             let response = try await request.response()
             
             if let artist = response.items.first, let genres = artist.genres {
                 for genre in genres {
                     results.append(SearchResult(
                        id: genre.id.rawValue,
                        title: genre.name,
                        artist: "Genre",
                        album: nil
                    ))
                 }
             }
        } else if type == "similar-artists" {
             var request = MusicCatalogResourceRequest<Artist>(matching: \.id, equalTo: MusicItemID(id))
             request.properties = [.similarArtists]
             request.limit = limit
             let response = try await request.response()
             
             if let artist = response.items.first, let similar = artist.similarArtists {
                 for sim in similar {
                     results.append(SearchResult(
                        id: sim.id.rawValue,
                        title: sim.name,
                        artist: sim.name,
                        album: nil
                    ))
                 }
             }
        }
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(results)
        print(String(data: data, encoding: .utf8)!)
    }
}

struct GetCatalogCharts: AsyncParsableCommand {
    static let configuration = CommandConfiguration(abstract: "Get catalog charts for a genre")
    
    @Option(name: .long, help: "Genre ID (optional)")
    var genre: String?
    
    @Option(name: .long, help: "Limit")
    var limit: Int = 5
    
    @Option(name: .long, help: "Types (songs, albums, playlists)")
    var types: String = "songs"

    func run() async throws {
        let status = await MusicAuthorization.request()
        guard status == .authorized else {
            printToStderr("Error: MusicKit authorization failed.")
            throw ExitCode(1)
        }
        
        var chartTypes: [MusicCatalogChartRequestable.Type] = []
        if types.contains("songs") { chartTypes.append(Song.self) }
        if types.contains("albums") { chartTypes.append(Album.self) }
        if types.contains("playlists") { chartTypes.append(Playlist.self) }
        if chartTypes.isEmpty { chartTypes = [Song.self] }
        
        // Fetch genre object if provided
        var genreObj: Genre? = nil
        if let genreId = genre {
            let request = MusicCatalogResourceRequest<Genre>(matching: \.id, equalTo: MusicItemID(genreId))
            let response = try await request.response()
            genreObj = response.items.first
        }
        
        var chartRequest = MusicCatalogChartsRequest(genre: genreObj, types: chartTypes)
        chartRequest.limit = limit
        
        let response = try await chartRequest.response()
        
        var results: [SearchResult] = []
        
        if chartTypes.contains(where: { $0 == Song.self }) {
            for chart in response.songCharts {
                for song in chart.items {
                    results.append(SearchResult(
                        id: song.id.rawValue,
                        title: song.title,
                        artist: song.artistName,
                        album: song.albumTitle
                    ))
                }
            }
        }
        
        if chartTypes.contains(where: { $0 == Album.self }) {
             for chart in response.albumCharts {
                for album in chart.items {
                    results.append(SearchResult(
                        id: album.id.rawValue,
                        title: album.title,
                        artist: album.artistName,
                        album: album.title
                    ))
                }
            }
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
        
        // 0. Ensure "Cloud Crate" Folder Exists
        let folderId = try await getOrCreateFolder(name: "Cloud Crate")
        printToStderr("Using Folder ID: \(folderId)")

        
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
            ],
            "parent": [
                "data": [
                    [
                        "id": folderId,
                        "type": "library-playlist-folders"
                    ]
                ]
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
                
                // Count catalog tracks from input
                let catalogCount = input.tracks.filter { $0.type == "catalog" || (!$0.type.isEmpty && $0.type != "library" && !$0.id.starts(with: "i.")) }.count
                
                let output = ["status": "success", "playlistId": id, "addedToLibraryCount": "\(catalogCount)"]
                let outputJson = try JSONEncoder().encode(output)
                print(String(data: outputJson, encoding: .utf8)!)
                
            } else {
                printToStderr("Error: Unexpected response format from Apple Music API.")
                printToStderr("Response: \(String(data: response.data, encoding: .utf8) ?? "")")
                throw ExitCode(1)
            }
            
        } catch {
            printToStderr("Error creating playlist: \(error)")
            if let musicError = error as? MusicDataRequest.Error {
                 printToStderr("Status Code: \(musicError.status)")
            }
            throw ExitCode(1)
        }
    }
    
    // MARK: - Folder Management
    func getOrCreateFolder(name: String) async throws -> String {
        // 1. Search for existing folder
        // Only way is to fetch all folders and filter? Or is there a search?
        // Let's fetch top-level folders.
        let url = URL(string: "https://api.music.apple.com/v1/me/library/playlist-folders")!
        let request = MusicDataRequest(urlRequest: URLRequest(url: url))
        let response = try await request.response()
        
        if let json = try JSONSerialization.jsonObject(with: response.data) as? [String: Any],
           let data = json["data"] as? [[String: Any]] {
            
            for item in data {
                 if let attributes = item["attributes"] as? [String: Any],
                    let folderName = attributes["name"] as? String,
                    folderName == name,
                    let id = item["id"] as? String {
                     return id
                 }
            }
        }
        
        // 2. Create if not found
        printToStderr("Folder '\(name)' not found. Creating...")
        let createUrl = URL(string: "https://api.music.apple.com/v1/me/library/playlist-folders")!
        var urlRequest = URLRequest(url: createUrl)
        urlRequest.httpMethod = "POST"
        
        let payload: [String: Any] = [
            "attributes": [
                "name": name,
                "description": "Folder for Cloud Crate playlists"
            ]
        ]
        urlRequest.httpBody = try JSONSerialization.data(withJSONObject: payload)
        
        let createRequest = MusicDataRequest(urlRequest: urlRequest)
        let createResponse = try await createRequest.response()
        
        if let json = try JSONSerialization.jsonObject(with: createResponse.data) as? [String: Any],
           let data = json["data"] as? [[String: Any]],
           let first = data.first,
           let id = first["id"] as? String {
            return id
        }
        
        throw NSError(domain: "EdgeCLI", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to create folder."])
    }
}
// Remove runAppleScript helper if no longer used, or keep for potential fallbacks? 
// User explicit requested MusicKit, so removing ambiguity.

