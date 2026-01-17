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
Track ID: {row['id']}
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
def create_playlist(name: str, track_ids: list[str], confirm: bool = False) -> str:
    """
    Create a new playlist in Apple Music with the specified tracks.
    
    IMPORTANT: You MUST first call this tool with confirm=False (default) to generate a preview 
    of the playlist. Present this preview to the user and ask for confirmation.
    
    Only after the user explicitly agrees should you call this tool again with confirm=True 
    to actually create the playlist.

    Args:
        name: The name of the new playlist.
        track_ids: A list of track IDs to add to the playlist.
        confirm: set to True only after user approval. Defaults to False (preview only).
    """
    if df.empty: return "Library not loaded."
    if not track_ids: return "Error: No track IDs provided."
    
    # 1. Resolve IDs to Metadata
    tracks_to_add = []
    missing_ids = []
    
    for tid in track_ids:
        # Check type
        if tid not in df['id'].values:
            missing_ids.append(tid)
            continue
            
        row = df[df['id'] == tid].iloc[0]
        # Escape quotes for AppleScript
        title = row['title'].replace('"', '\\"')
        artist = row['artist_name'].replace('"', '\\"')
        tracks_to_add.append({'title': title, 'artist': artist, 'orig_title': row['title'], 'orig_artist': row['artist_name']})
    
    if not tracks_to_add:
        return f"Error: None of the provided track IDs found in loaded library. Missing: {missing_ids}"
        
    # PREVIEW MODE
    if not confirm:
        preview_lines = [f"I will create a playlist named '{name}' with the following {len(tracks_to_add)} tracks:"]
        for t in tracks_to_add[:20]: # Show first 20 in preview to avoid huge output
            preview_lines.append(f"- {t['orig_title']} by {t['orig_artist']}")
        
        if len(tracks_to_add) > 20:
            preview_lines.append(f"... and {len(tracks_to_add) - 20} more.")
            
        preview_lines.append("\nPlease ask the user if they would like to proceed. If yes, call create_playlist again with confirm=True.")
        return "\n".join(preview_lines)
    
    print(f"Preparing to add {len(tracks_to_add)} tracks to new playlist '{name}'...")

    # 2. Build AppleScript
    # Escape for AppleScript
    escaped_name = name.replace('"', '\\"')
    folder_name = "Cloud Crate"
    
    create_pl_script = f'''
    tell application "Music"
        -- Ensure folder exists
        if not (exists folder playlist "{folder_name}") then
            make new folder playlist with properties {{name:"{folder_name}"}}
        end if
        set parentFolder to folder playlist "{folder_name}"
        
        -- Create playlist in folder or get existing
    # ... (inside create_pl_script)
        if not (exists user playlist "{escaped_name}" of parentFolder) then
            set targetPlaylist to (make new user playlist at parentFolder with properties {{name:"{escaped_name}"}})
        else
            set targetPlaylist to user playlist "{escaped_name}" of parentFolder
        end if
        return id of targetPlaylist
    end tell
    '''
    
    playlist_id = None
    try:
        result = subprocess.run(['osascript', '-e', create_pl_script], check=True, capture_output=True, text=True)
        playlist_id = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error creating playlist: {e.stderr}"

    if not playlist_id:
        return "Error: Could not retrieve playlist ID."

    # 3. Add Tracks via AppleScript
    # Batching to avoid huge command lines
    success_count = 0
    fail_count = 0
    batch_size = 50
    chunks = [tracks_to_add[i:i + batch_size] for i in range(0, len(tracks_to_add), batch_size)]
    
    for chunk in chunks:
        # Use ID to reference playlist directly, avoiding folder complexity
        script_commands = [
            'tell application "Music"', 
            f'set targetPlaylist to playlist id {playlist_id}'
        ]
        
        for t in chunk:
            # Match by Name and Artist
            # Note: t['title'] and t['artist'] are already escaped in step 1
            search_criteria = f'name is "{t["title"]}" and artist is "{t["artist"]}"'
            cmd = f'try\n duplicate (every track of library playlist 1 whose {search_criteria}) to targetPlaylist\n end try'
            script_commands.append(cmd)
            
        script_commands.append('end tell')
        
        full_script = "\n".join(script_commands)
        
        try:
            subprocess.run(['osascript', '-e', full_script], check=True, capture_output=True)
            success_count += len(chunk) # Approximation
        except subprocess.CalledProcessError as e:
            print(f"Error adding batch to playlist: {e.stderr}")
            fail_count += len(chunk)

    return f"Playlist '{name}' created/updated. Attempted adding {len(tracks_to_add)} tracks."

if __name__ == "__main__":
    mcp.run()
