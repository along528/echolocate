import sys
import os
import json
import subprocess

# Add current directory to path so we can import local_server
sys.path.append(os.getcwd())

from local_server import explore_genre, get_related_artists, search_artist_top_songs

def test_explore_genre():
    print("Testing explore_genre...")
    try:
        result = explore_genre("Alternative", limit=2)
        print(f"Result for 'Alternative':\n{result}")
        if "Error" in result and "MusicKit authorization failed" in result:
             print("Please enable MusicKit permissions for Terminal/Edge.")
        elif "Top Songs" in result:
             print("SUCCESS: Found songs.")
        else:
             print("WARNING: Unexpected output.")
    except Exception as e:
        print(f"FAILED: {e}")

def test_related_artists():
    print("\nTesting get_related_artists...")
    try:
        # Use search_artist_top_songs to find an artist ID (we updated it to print ID)
        print("Searching for Artist 'Daft Punk' to get ID...")
        search_res = search_artist_top_songs("Daft Punk", limit=1)
        
        import re
        # Look for "Top songs for Daft Punk (ID: 12345):"
        match = re.search(r"\(ID: (\d+)\):", search_res)
        if match:
            artist_id = match.group(1)
            print(f"Found Artist ID: {artist_id}. Getting related...")
            related = get_related_artists(artist_id, limit=2)
            print(f"Related Artists:\n{related}")
             
            if "Artists similar to" in related:
                print("SUCCESS: Found related artists.")
            else:
                 print("WARNING: Unexpected output.")
        else:
            print(f"SKIPPING: Could not find Artist ID in output:\n{search_res}")
            
    except Exception as e:
         print(f"FAILED: {e}")

if __name__ == "__main__":
    test_explore_genre()
    test_related_artists()
