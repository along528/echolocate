
import sys
import os
import json

# Append current directory to path for imports
sys.path.append(os.getcwd())

from backend import local_server

def test_native_playlist():
    print("--- Test: Native Playlist Creation ---")
    
    # Mock data - Real IDs from library + a dummy Catalog ID
    # Note: local_server relies on loaded DF. Ensure it's loaded.
    
    # 1. Library Track (assuming one exists)
    lib_id = "i.QXkvxtpV370" # From verify_playlist_creation.py
    
    # 2. Catalog Track (Anti-Hero by Taylor Swift)
    cat_id = "1649434293"
    
    track_ids = [f"library:{lib_id}", f"catalog:{cat_id}"]
    playlist_name = "Native Verification Playlist"
    
    print(f"Creating playlist '{playlist_name}' with: {track_ids}")
    
    # Preview
    print("\n[Preview Mode]")
    preview = local_server.create_playlist(playlist_name, track_ids, confirm=False)
    print(preview)
    
    if "Catalog ID" not in preview:
        print("FAILED: Preview didn't detect Catalog ID")
        return

    # Create
    print("\n[Creation Mode]")
    # We can't actually verify success of AppleScript without Music app running and authorized,
    # but we can check if it returns the expected mocked/json success string format from edge CLI.
    # Note: invoke_edge falls back to 'swift run' if binary missing.
    
    result = local_server.create_playlist(playlist_name, track_ids, confirm=True)
    print(result)
    
    if "created successfully" in result:
        print("\nSUCCESS: Playlist creation command executed.")
    else:
        print("\nFAILED: Creation command returned unexpected result.")
        
if __name__ == "__main__":
    local_server.mcp.run = lambda: None # Mock run
    test_native_playlist()
