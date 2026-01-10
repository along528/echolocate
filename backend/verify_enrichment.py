
import sys
import os
import pandas as pd

# Mocking the MCP server environment to test the logic directly
try:
    from local_server import search_library, get_rotation, search_albums, df, albums_df
except Exception as e:
    print(f"Error importing local_server: {e}")
    sys.exit(1)

def test_enrichment(func, *args, name=""):
    print(f"Testing {name}...")
    res = func(*args)
    print("Sample Output Start:")
    print(res[:500] + "..." if len(res) > 500 else res)
    
    if "---" in res and "Track ID:" in res and "Album:" in res:
        print(f"SUCCESS: {name} returns enriched details (ID, Album).")
    elif "---" in res and "Album:" in res and "Track IDs:" in res: # For search_albums
        print(f"SUCCESS: {name} returns enriched Album details.")
    else:
        print(f"FAILURE: {name} missing required fields.")
        print("Expected '---', 'Track ID:' (or 'Track IDs:' for albums), and 'Album:'.")

print("Library Size:", len(df))

if len(df) > 0:
    test_enrichment(search_library, "e", 2, name="search_library")
    test_enrichment(get_rotation, "Heavy", name="get_rotation")
    test_enrichment(search_albums, "a", name="search_albums")

