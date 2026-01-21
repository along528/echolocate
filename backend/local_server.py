from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
import subprocess
from datetime import datetime

# Initialize FastMCP
mcp = FastMCP("Cloud Crate Local")

# Configuration
# Resolve absolute path to the data file based on this script's location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Data is in ../crate/my_library.json relative to backend/ (where this script is)
DATA_PATH = os.path.join(SCRIPT_DIR, "..", "crate", "my_library.json")

def load_library():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Could not find library at {DATA_PATH}")
    
    df = pd.read_json(DATA_PATH)
    # Ensure date column is datetime objects
    df['last_played_at'] = pd.to_datetime(df['last_played_at'], utc=True, errors='coerce')
    
    # Handle missing new columns if reading old file
    if 'album_title' not in df.columns:
        df['album_title'] = "Unknown Album"
        
    return df

def create_albums_df(df):
    if df.empty: return pd.DataFrame()
    
    # Explode genres? No, we want album level genres.
    # Group by album and artist
    grouped = df.groupby(['album_title', 'artist_name'])
    
    albums_data = []
    
    for (album, artist), group in grouped:
        albums_data.append({
            'album_title': album,
            'artist_name': artist,
            'total_plays': group['play_count'].sum(),
            'last_played': group['last_played_at'].max(),
            'track_ids': group['id'].tolist()
        })
        
    return pd.DataFrame(albums_data)

# Global dataframe (lazy load could be better but this is simple)
try:
    df = load_library()
    albums_df = create_albums_df(df)
    print(f"Loaded {len(df)} tracks and {len(albums_df)} albums.")
except Exception as e:
    print(f"Error loading library: {e}")
    df = pd.DataFrame()
    albums_df = pd.DataFrame()

EDGE_BINARY_PATH = os.path.join(SCRIPT_DIR, "..", "edge", "edge.app", "Contents", "MacOS", "edge")
# Fallback to using swift run if binary looks missing (or handle in invoke)
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

def invoke_edge(command, args, input_json=None):
    """
    Invoke the edge CLI.
    """
    # Build command
    # Use binary if exists, else swift run
    if os.path.exists(EDGE_BINARY_PATH):
        cmd = [EDGE_BINARY_PATH, command] + args
    else:
        # Fallback to swift run
        # Note: This is slower
        cmd = ["swift", "run", "--package-path", os.path.join(SCRIPT_DIR, "..", "edge"), "edge", command] + args
        
    print(f"Executing: {' '.join(cmd)}")
    
    # Handle input file
    input_file_path = None
    if input_json:
        import uuid
        input_file_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.json")
        with open(input_file_path, 'w') as f:
            json.dump(input_json, f)
        cmd.extend(["--input-file", input_file_path])
        
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Edge CLI Error: {e.stderr}")
        raise e
    finally:
        if input_file_path and os.path.exists(input_file_path):
            os.remove(input_file_path)


@mcp.tool()
def search_library(query: str, limit: int = 10) -> str:
    """
    Search the music library using text matching on Title and Artist.
    Args:
        query: The search terms (e.g. "Pink Floyd", "Dark Side")
        limit: Number of results to return
    """
    if df.empty:
        return "Library is empty or not loaded."
    
    # Simple case-insensitive string match
    mask = (
        df['title'].str.contains(query, case=False, na=False) | 
        df['artist_name'].str.contains(query, case=False, na=False)
    )
    # Results
    matches = df[mask]
    
    if matches.empty:
        return "No matches found."
        
    # Return random sample if more than limit
    if len(matches) > limit:
        results = matches.sample(n=limit)
    else:
        results = matches
        
    
    formatted = []
    for _, row in results.iterrows():
        formatted.append(f"""
---
Track ID: library:{row['id']}
Title: {row['title']}
Artist: {row['artist_name']}
Album: {row['album_title']}
Play Count: {row['play_count']}
Last Played: {row['last_played_at']}
""")
    
    return "".join(formatted)

@mcp.tool()
def get_track_context(track_id: str) -> str:
    """
    Get full metadata for a specific track by its ID.
    Args:
        track_id: The ID of the track
    """
    if df.empty: return "Library not loaded."
    
    track = df[df['id'] == track_id]
    if track.empty:
        return "Track not found."
    
    row = track.iloc[0]
    return f"""
Title: {row['title']}
Artist: {row['artist_name']}
Play Count: {row['play_count']}
Last Played: {row['last_played_at']}
    """

@mcp.tool()
def get_rotation(category: str) -> str:
    """
    Get tracks based on rotation category using local play counts.
    Args:
        category: 'Heavy' (>20 plays), 'Gold' (>50 plays), 'Unplayed' (0 plays), 'Random'
    """
    if df.empty: return "Library not loaded."
    
    limit = 10
    
    if category.lower() == 'heavy':
        subset = df[df['play_count'] > 20].sort_values('play_count', ascending=False)
    elif category.lower() == 'gold':
        subset = df[df['play_count'] > 50].sort_values('play_count', ascending=False)
    elif category.lower() == 'unplayed':
        subset = df[df['play_count'] == 0]
    else:
        return "Unknown category. Use Heavy, Gold, or Unplayed."
    
    
    # Shuffle results by sampling
    if len(subset) > limit:
        results = subset.sample(n=limit)
    else:
        results = subset
    if results.empty:
        return "No tracks found in this category."

    formatted = []
    for _, row in results.iterrows():
        formatted.append(f"""
---
Track ID: {row['id']}
Title: {row['title']}
Artist: {row['artist_name']}
Album: {row['album_title']}
Play Count: {row['play_count']}
Last Played: {row['last_played_at']}
""")

    return "".join(formatted)

@mcp.tool()
def filter_by_date_range(start_date: str = None, end_date: str = None, limit: int = 20) -> str:
    """
    Filter tracks by their 'last_played_at' date.
    Args:
        start_date: ISO8601 string (e.g. "2020-01-01"). If None, no lower bound.
        end_date: ISO8601 string (e.g. "2023-01-01"). If None, no upper bound.
        limit: Max results to return.
    """
    if df.empty: return "Library not loaded."
    
    subset = df.copy()
    
    # Drop rows where last_played_at is NaT (never played) if we are filtering by date?
    # Or keep them? Usually if we filter range, we imply existence of date.
    subset = subset.dropna(subset=['last_played_at'])
    
    if start_date:
        try:
            dt_start = pd.to_datetime(start_date, utc=True)
            subset = subset[subset['last_played_at'] >= dt_start]
        except:
            return f"Invalid start_date format: {start_date}"
            
    if end_date:
        try:
            dt_end = pd.to_datetime(end_date, utc=True)
            subset = subset[subset['last_played_at'] <= dt_end]
        except:
             return f"Invalid end_date format: {end_date}"
             
    if subset.empty:
        return "No tracks found in this date range."
        
    # Sort by date (oldest first if end_date provided (looking for old stuff), newest first if start_date (looking for recent))
    # Heuristic: if end_date is present, probably looking for "forgotten" stuff -> Ascending.
    ascending = True if end_date else False
    
    results = subset.sort_values('last_played_at', ascending=ascending).head(limit)
    
    formatted = []
    for _, row in results.iterrows():
        date_str = row['last_played_at'].strftime('%Y-%m-%d')
        formatted.append(f"""
---
Track ID: {row['id']}
Title: {row['title']}
Artist: {row['artist_name']}
Album: {row['album_title']}
Play Count: {row['play_count']}
Last Played: {date_str}
""")
        
    return "".join(formatted)

@mcp.tool()
def search_albums(query: str) -> str:
    """
    Search for albums by title.
    Args:
        query: The search term for album title.
    """
    if albums_df.empty: return "Library not loaded or no albums found."
    
    mask = albums_df['album_title'].str.contains(query, case=False, na=False)
    matches = albums_df[mask]
    
    if matches.empty: return "No albums found."
    
    if len(matches) > 10:
        results = matches.sample(n=10)
    else:
        results = matches
    
    formatted = []
    for _, row in results.iterrows():
        date_str = row['last_played'].strftime('%Y-%m-%d') if pd.notnull(row['last_played']) else "Never"
        formatted.append(f"""
---
Album: {row['album_title']}
Artist: {row['artist_name']}
Total Plays: {row['total_plays']}
Most Recent Play: {date_str}
Track IDs: {", ".join(row['track_ids'])}
""")
        
    return "".join(formatted)

@mcp.tool()
def get_album_context(album_name: str) -> str:
    """
    Get detailed context for an album, including statistics and track IDs.
    Args:
        album_name: The exact name of the album (or close match).
    """
    if albums_df.empty: return "Library not loaded."
    
    # Exact match first, then loose
    match = albums_df[albums_df['album_title'].str.lower() == album_name.lower()]
    if match.empty:
        # Try contains
        match = albums_df[albums_df['album_title'].str.contains(album_name, case=False, na=False)]
        
    if match.empty: return "Album not found."
    
    row = match.iloc[0]
    date_str = row['last_played'].strftime('%Y-%m-%d') if pd.notnull(row['last_played']) else "Never"
    
    return f"""
Album: {row['album_title']}
Artist: {row['artist_name']}
Total Plays: {row['total_plays']}
Most Recent Play: {date_str}
Track IDs: {", ".join(row['track_ids'])}
    """

@mcp.tool()
def get_batch_track_context(track_ids: list[str]) -> str:
    """
    Get full metadata for multiple tracks by their IDs.
    Args:
        track_ids: A list of track IDs
    """
    if df.empty: return "Library not loaded."
    
    results = []
    for tid in track_ids:
        track = df[df['id'] == tid]
        if track.empty:
            results.append(f"Track ID {tid}: Not found.")
            continue
        
        row = track.iloc[0]
        results.append(f"""
---
Track ID: {tid}
Title: {row['title']}
Artist: {row['artist_name']}
Play Count: {row['play_count']}
Last Played: {row['last_played_at']}
""")
    
    return "\n".join(results)

@mcp.tool()
def get_batch_album_context(album_names: list[str]) -> str:
    """
    Get detailed context for multiple albums.
    Args:
        album_names: List of album names (exact or close match).
    """
    if albums_df.empty: return "Library not loaded."
    
    results = []
    for name in album_names:
        # Exact match first, then loose
        match = albums_df[albums_df['album_title'].str.lower() == name.lower()]
        if match.empty:
            # Try contains
            match = albums_df[albums_df['album_title'].str.contains(name, case=False, na=False)]
            
        if match.empty:
            results.append(f"Album '{name}': Not found.")
            continue
        
        row = match.iloc[0]
        date_str = row['last_played'].strftime('%Y-%m-%d') if pd.notnull(row['last_played']) else "Never"
        
        results.append(f"""
---
Album: {row['album_title']}
Artist: {row['artist_name']}
Total Plays: {row['total_plays']}
Most Recent Play: {date_str}
Track IDs: {", ".join(row['track_ids'])}
""")
            
    return "\n".join(results)

@mcp.tool()
def search_apple_music(query: str, limit: int = 5) -> str:
    """
    Search the global Apple Music Catalog for songs.
    Use this to find music not in the user's library.
    Args:
        query: Search term (e.g. "Despacito", "Taylor Swift")
        limit: Max results (default 5)
    """
    try:
        output_json = invoke_edge("search-catalog", ["--query", query, "--limit", str(limit), "--types", "songs"])
        results = json.loads(output_json)
        
        if not results:
            return "No results found in Apple Music Catalog."
            
        formatted = []
        for item in results:
            formatted.append(f"""
---
Track ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
Album: {item.get('album', 'Unknown')}
""")
        return "".join(formatted)
            
    except Exception as e:
        return f"Error searching Apple Music: {e}"

@mcp.tool()
def search_artist_top_songs(artist_name: str, limit: int = 5) -> str:
    """
    Search for an artist in Apple Music Catalog and get their top songs.
    Args:
        artist_name: Name of the artist (e.g. "The Beatles")
        limit: Number of top songs to return.
    """
    try:
        # 1. Search for Artist
        search_output = invoke_edge("search-catalog", ["--query", artist_name, "--limit", "1", "--types", "artists"])
        search_results = json.loads(search_output)
        
        if not search_results:
            return f"Artist '{artist_name}' not found in catalog."
            
        artist = search_results[0]
        artist_id = artist['id']
        
        # 2. Get Top Songs
        resource_output = invoke_edge("get-catalog-resource", ["--id", artist_id, "--type", "artist", "--limit", str(limit)])
        songs = json.loads(resource_output)
        
        formatted = [f"Top songs for {artist['title']} (ID: {artist_id}):"]
        for item in songs:
             formatted.append(f"""
---
Track ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
Album: {item.get('album', 'Unknown')}
""")
        return "".join(formatted)

    except Exception as e:
         return f"Error fetching artist top songs: {e}"

@mcp.tool()
def search_artist_top_albums(artist_name: str, limit: int = 5) -> str:
    """
    Search for an artist in Apple Music Catalog and get their top albums.
    Args:
        artist_name: Name of the artist
        limit: Number of albums to return.
    """
    try:
        # 1. Search for Artist
        search_output = invoke_edge("search-catalog", ["--query", artist_name, "--limit", "1", "--types", "artists"])
        search_results = json.loads(search_output)
        
        if not search_results:
            return f"Artist '{artist_name}' not found in catalog."
            
        artist = search_results[0]
        artist_id = artist['id']
        
        # 2. Get Top Albums
        resource_output = invoke_edge("get-catalog-resource", ["--id", artist_id, "--type", "artist-albums", "--limit", str(limit)])
        albums = json.loads(resource_output)
        
        formatted = [f"Top albums for {artist['title']}:"]
        for item in albums:
             formatted.append(f"""
---
Album ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
""")
        return "".join(formatted)

    except Exception as e:
         return f"Error fetching artist top albums: {e}"

@mcp.tool()
def search_album_tracks(album_name: str, artist_name: str = "") -> str:
    """
    Search for an album in Apple Music Catalog and get its tracks.
    Args:
        album_name: Name of the album
        artist_name: Optional artist name to refine search
    """
    try:
        query = f"{album_name} {artist_name}".strip()
        # 1. Search for Album
        search_output = invoke_edge("search-catalog", ["--query", query, "--limit", "1", "--types", "albums"])
        search_results = json.loads(search_output)
        
        if not search_results:
            return f"Album '{album_name}' not found in catalog."
            
        album = search_results[0]
        album_id = album['id']
        
        # 1.5 Get Album Details for Record Label
        label_info = ""
        try:
            details_out = invoke_edge("get-catalog-resource", ["--id", album_id, "--type", "album-details"])
            details = json.loads(details_out)
            if details:
                d = details[0]
                if d.get('recordLabelName'):
                    label_info = f"\nRecord Label: {d['recordLabelName']}"
                    if d.get('recordLabelId'):
                        label_info += f" (ID: catalog:{d['recordLabelId']})"
        except Exception as e:
            print(f"Warning: Failed to fetch album details: {e}")

        # 2. Get Tracks
        resource_output = invoke_edge("get-catalog-resource", ["--id", album_id, "--type", "album"])
        tracks = json.loads(resource_output)
        
        formatted = [f"Tracks for album '{album['title']}' by {album['artist']}:{label_info}"]
        for item in tracks:
             formatted.append(f"""
---
Track ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
Album: {item.get('album', 'Unknown')}
""")
        return "".join(formatted)

    except Exception as e:
         return f"Error fetching album tracks: {e}"

@mcp.tool()
def get_album_details(album_id: str) -> str:
    """
    Get detailed information about an album, including Record Label.
    Args:
        album_id: The catalog ID of the album.
    """
    try:
        # Handle prefix
        if album_id.startswith("catalog:"):
            album_id = album_id.split(":", 1)[1]
            
        output = invoke_edge("get-catalog-resource", ["--id", album_id, "--type", "album-details"])
        results = json.loads(output)
        
        if not results:
            return "Album details not found."
            
        album = results[0]
        label_info = ""
        if album.get('recordLabelName'):
             label_info = f"\nRecord Label: {album['recordLabelName']}"
             if album.get('recordLabelId'):
                 label_info += f" (ID: catalog:{album['recordLabelId']})"
        
        return f"""
---
Album ID: catalog:{album['id']}
Title: {album['title']}
Artist: {album['artist']}{label_info}
"""
    except Exception as e:
        return f"Error fetching album details: {e}"

@mcp.tool()
def search_record_label(name: str, limit: int = 5) -> str:
    """
    Search for a record label.
    Args:
        name: Name of the record label (e.g. "Def Jam")
        limit: Max results
    """
    try:
        output_json = invoke_edge("search-catalog", ["--query", name, "--limit", str(limit), "--types", "labels"])
        results = json.loads(output_json)
        
        if not results:
            return "No labels found."
            
        formatted = []
        for item in results:
            formatted.append(f"""
---
Label ID: catalog:{item['id']}
Name: {item['title']}
""")
        return "".join(formatted)
            
    except Exception as e:
        return f"Error searching record labels: {e}"

@mcp.tool()
def get_record_label_releases(label_name: str, sort: str = 'latest', limit: int = 20) -> str:
    """
    Get releases (albums) associated with a record label.
    Args:
        label_name: Name of the record label
        sort: 'latest' or 'top' (default 'latest')
        limit: Max albums to return
    """
    try:
        # 1. Search for Label
        search_output = invoke_edge("search-catalog", ["--query", label_name, "--limit", "1", "--types", "labels"])
        search_results = json.loads(search_output)
        
        if not search_results:
            return f"Label '{label_name}' not found."
            
        label = search_results[0]
        label_id = label['id']
        
        # 2. Get Releases
        resource_type = "record-label-top" if sort == 'top' else "record-label-latest"
        
        resource_output = invoke_edge("get-catalog-resource", ["--id", label_id, "--type", resource_type, "--limit", str(limit)])
        albums = json.loads(resource_output)
        
        formatted = [f"{sort.capitalize()} releases for {label['title']}:"]
        for item in albums:
             formatted.append(f"""
---
Album ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
""")
            
        return "".join(formatted)

    except Exception as e:
        return f"Error fetching label releases: {e}"


@mcp.tool()
def get_genres(resource_id: str, resource_type: str) -> str:
    """
    Get genres associated with a song, album, or artist.
    Args:
        resource_id: The catalog ID of the resource (e.g. "12345")
        resource_type: "song", "album", or "artist"
    """
    valid_types = {
        "song": "song-genres",
        "album": "album-genres", 
        "artist": "artist-genres"
    }
    
    if resource_type not in valid_types:
        return "Invalid resource_type. Must be 'song', 'album', or 'artist'."
        
    edge_type = valid_types[resource_type]
    
    try:
        # Check for prefix
        if resource_id.startswith("catalog:"):
            clean_id = resource_id.split(":", 1)[1]
        else:
            clean_id = resource_id
            
        resource_output = invoke_edge("get-catalog-resource", ["--id", clean_id, "--type", edge_type])
        genres = json.loads(resource_output)
        
        if not genres:
            return "No genres found."
            
        formatted = []
        for item in genres:
            formatted.append(f"""
---
Genre ID: catalog:{item['id']}
Name: {item['title']}
""")
        return "".join(formatted)

    except Exception as e:
        return f"Error fetching genres: {e}"


    except Exception as e:
        return f"Error fetching genres: {e}"


@mcp.tool()
def explore_genre(name: str, limit: int = 5) -> str:
    """
    Explore a music genre. Finds top songs for the genre.
    Args:
        name: Name of the genre (e.g. "Alternative", "Pop", "Jazz")
        limit: Number of top songs to return
    """
    try:
        # 1. Search for Genre
        search_output = invoke_edge("search-catalog", ["--query", name, "--limit", "1", "--types", "genres"])
        search_results = json.loads(search_output)
        
        if not search_results:
            return f"Genre '{name}' not found."
            
        genre = search_results[0]
        genre_id = genre['id']
        
        # 2. Get Top Charts for Genre
        charts_output = invoke_edge("get-catalog-charts", ["--genre", genre_id, "--limit", str(limit), "--types", "songs"])
        charts_results = json.loads(charts_output)
        
        formatted = [f"Top Songs for {genre['title']}:"]
        for item in charts_results:
             formatted.append(f"""
---
Track ID: catalog:{item['id']}
Title: {item['title']}
Artist: {item['artist']}
Album: {item.get('album', 'Unknown')}
""")
        return "".join(formatted)

    except Exception as e:
        return f"Error exploring genre: {e}"


@mcp.tool()
def get_related_artists(artist_id: str, limit: int = 5) -> str:
    """
    Get similar artists for a given artist.
    Args:
        artist_id: The catalog ID of the artist
        limit: Max related artists to return
    """
    try:
        # Check for prefix
        if artist_id.startswith("catalog:"):
            clean_id = artist_id.split(":", 1)[1]
        else:
            clean_id = artist_id
            
        resource_output = invoke_edge("get-catalog-resource", ["--id", clean_id, "--type", "similar-artists", "--limit", str(limit)])
        artists = json.loads(resource_output)
        
        if not artists:
            return "No related artists found."
            
        formatted = [f"Artists similar to ID {clean_id}:"]
        for item in artists:
            formatted.append(f"""
---
Artist ID: catalog:{item['id']}
Name: {item['title']}
""")
        return "".join(formatted)
        
    except Exception as e:
        return f"Error fetching related artists: {e}"


@mcp.tool()
def create_playlist(name: str, track_ids: list[str], confirm: bool = False) -> str:
    """
    Create a new playlist in Apple Music with the specified tracks.
    Supports both Library tracks (ID starts with 'library:') and Catalog tracks (ID starts with 'catalog:').
    Catalog tracks will be automatically added to the library if needed.
    
    IMPORTANT: You MUST first call this tool with confirm=False (default) to generate a preview.
    Then call again with confirm=True.

    Args:
        name: The name of the new playlist.
        track_ids: A list of track IDs (e.g. ["library:123", "catalog:456"]).
        confirm: set to True only after user approval. Defaults to False (preview only).
    """
    if not track_ids: return "Error: No track IDs provided."
    
    # 1. Parse IDs to Type/ID and resolve Metadata
    # Handle mixed raw IDs (legacy) and prefixed IDs
    parsed_tracks = []
    
    for tid in track_ids:
        track_type = "library" # Default
        clean_id = tid
        
        if tid.startswith("library:"):
            clean_id = tid.split(":", 1)[1]
            track_type = "library"
        elif tid.startswith("catalog:"):
            clean_id = tid.split(":", 1)[1]
            track_type = "catalog"
        else:
            # Fallback for raw IDs
            if not df.empty and tid in df['id'].values:
                track_type = "library"
            else:
                track_type = "catalog"
        
        # Resolve Metadata (Title/Artist)
        title = "Unknown"
        artist = "Unknown"
        
        if track_type == "library" and not df.empty:
            row = df[df['id'] == clean_id]
            if not row.empty:
                title = row.iloc[0]['title']
                artist = row.iloc[0]['artist_name']
        
        parsed_tracks.append({
            "id": clean_id, 
            "type": track_type,
            "title": title,
            "artist": artist
        })

    # Resolve details for preview (optional but good UI)
    preview_details = []
    for t in parsed_tracks:
        if t['type'] == 'library':
             preview_details.append(f"{t['title']} by {t['artist']} (Library)")
        else:
            preview_details.append(f"Catalog ID {t['id']} (Catalog - Auto-add limited)")
            
    # PREVIEW MODE
    if not confirm:
        preview_lines = [f"I will create a playlist named '{name}' with {len(parsed_tracks)} tracks:"]
        for line in preview_details[:20]:
            preview_lines.append(f"- {line}")
        
        if len(preview_details) > 20:
            preview_lines.append(f"... and {len(preview_details) - 20} more.")
            
        preview_lines.append("\nPlease ask the user if they would like to proceed. If yes, call create_playlist again with confirm=True.")
        return "\n".join(preview_lines)
    
    # 2. Invoke Native Bridge
    payload = {
        "name": name,
        "description": "Created via Cloud Crate",
        "tracks": parsed_tracks
    }
    
    try:
        output_json = invoke_edge("create-playlist", [], input_json=payload)
        # Parse result
        # Expected: {"status": "success", "playlistId": "...", "addedToLibraryCount": "..."} 
        # (Note: edge code printed raw JSON string)
        res = json.loads(output_json)
        
        return f"Playlist '{name}' created successfully.\nPlaylist ID: {res.get('playlistId')}\nNew tracks added to library: {res.get('addedToLibraryCount', '0')}"
        
    except Exception as e:
        return f"Error creating playlist: {e}"

if __name__ == "__main__":
    mcp.run()
