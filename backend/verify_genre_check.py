from local_server import get_genres, search_apple_music
import sys
import re

def verify():
    print("--- Verifying Genre Fetching ---")
    
    # 1. Search for a song to get ID
    print("\n1. Searching for 'Bohemian Rhapsody'...")
    search_res = search_apple_music(query="Bohemian Rhapsody", limit=1)
    if "No results" in search_res or "Error" in search_res:
        print(f"FAILED: Could not find song. Result: {search_res}")
        return

    # Extract ID
    match = re.search(r"Track ID: catalog:(\d+)", search_res)
    if not match:
        print(f"FAILED: Could not extract ID. Result: {search_res}")
        return
        
    song_id = match.group(1)
    print(f"Found Song ID: {song_id}")
    
    # 2. Get Genres for Song
    print(f"\n2. Fetching genres for Song ID {song_id}...")
    genres = get_genres(resource_id=song_id, resource_type="song")
    print(f"Result:\n{genres}")
    
    if "Genre ID:" in genres:
        print("SUCCESS: Fetched genres for song.")
    else:
        print("FAILED: Did not find expected genre data.")

if __name__ == "__main__":
    verify()
