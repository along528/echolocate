
import sys
import os
import json

# Append current directory to path for imports
sys.path.append(os.getcwd())

from backend import local_server

def test_catalog_search():
    print("--- Test: Catalog Search ---")
    
    # We can't easily mock the subprocess call without mocking invoke_edge, 
    # but we can try to run it if the binary exists (integration test) 
    # or mock invoke_edge.
    
    # Let's try to verify if invoke_edge works (Integration Test)
    # This requires the edge binary to be built and MusicKit permissions.
    # If not running in an environment with MusicKit access, this might fail or return standard error.
    
    query = "Taylor Swift"
    print(f"Searching for: {query}")
    
    result = local_server.search_apple_music(query, limit=2)
    print("Result:")
    print(result)
    
    if "Error" in result:
        print("\n[WARN] Search failed (expected if no MusicKit access)")
    elif "catalog:" in result:
        print("\nSUCCESS: Found catalog items.")
    else:
        print("\n[WARN] No items found or format unexpected.")

if __name__ == "__main__":
    local_server.mcp.run = lambda: None # Mock run
    test_catalog_search()
