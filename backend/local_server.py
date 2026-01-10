from mcp.server.fastmcp import FastMCP
import pandas as pd
import json
import os
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
    return df

# Global dataframe (lazy load could be better but this is simple)
try:
    df = load_library()
    print(f"Loaded {len(df)} tracks.")
except Exception as e:
    print(f"Error loading library: {e}")
    df = pd.DataFrame()

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
    results = df[mask].head(limit)
    
    if results.empty:
        return "No matches found."
        
    formatted = []
    for _, row in results.iterrows():
        formatted.append(f"- {row['title']} by {row['artist_name']} (ID: {row['id']})")
    
    return "\n".join(formatted)

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
    
    results = subset.head(limit)
    if results.empty:
        return "No tracks found in this category."

    formatted = [f"- {row['title']} by {row['artist_name']} ({row['play_count']} plays)" for _, row in results.iterrows()]
    return "\n".join(formatted)

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
        formatted.append(f"- {row['title']} by {row['artist_name']} (Last Played: {date_str})")
        
    return "\n".join(formatted)

if __name__ == "__main__":
    mcp.run()
