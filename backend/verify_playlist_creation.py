
import sys
import os

# Append current directory to path for imports
sys.path.append(os.getcwd())

from backend import local_server

def test_playlist_creation():
    # Use IDs we saw earlier in the crate
    track_ids = ["i.QXkvxtpV370", "i.6JNxBH8vAY1"] 
    playlist_name = "Cloud Crate Verification"
    
    print(f"Attempting to create playlist '{playlist_name}' in Cloud Crate folder with tracks: {track_ids}")
    
    result = local_server.create_playlist(playlist_name, track_ids)
    print("\nResult:")
    print(result)

if __name__ == "__main__":
    test_playlist_creation()
