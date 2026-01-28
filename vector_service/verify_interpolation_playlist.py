import requests
import json
import random
import sys
import os

# Configuration
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else None

if not SERVICE_URL:
    print("Attempting to find service URL via gcloud...")
    try:
        import subprocess
        result = subprocess.run(
            ["gcloud", "run", "services", "describe", "cloudcrate-vector", 
             "--region", "us-central1", "--format", "value(status.url)"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            SERVICE_URL = result.stdout.strip()
            print(f"Found URL: {SERVICE_URL}")
        else:
            print("Could not find service URL.")
            SERVICE_URL = "http://localhost:8000"
            print(f"Falling back to local: {SERVICE_URL}")

    except Exception as e:
        print(f"Error finding URL: {e}")
        SERVICE_URL = "http://localhost:8000"
        print(f"Falling back to local: {SERVICE_URL}")

def get_track_display(track):
    return f"[{track.get('id', 'Unknown')}] {track.get('title', 'Unknown Title')} by {track.get('artist', 'Unknown Artist')}"

try:
    # 1. Fetch Tracks
    print(f"\n--- 1. Fetching Tracks ({SERVICE_URL}/tracks) ---")
    response = requests.get(f"{SERVICE_URL}/tracks", params={"limit": 100})
    if response.status_code != 200:
        print(f"❌ Error listing tracks: {response.text}")
        sys.exit(1)
        
    tracks = response.json()
    print(f"✅ Found {len(tracks)} tracks.")
    
    if len(tracks) < 2:
        print("❌ Not enough tracks.")
        sys.exit(1)

    # 2. Select 2 Random Tracks
    selected_tracks = random.sample(tracks, 2)
    track_a = selected_tracks[0]
    track_b = selected_tracks[1]
    
    print(f"\n--- 2. Generating Playlist ---")
    print(f"Start: {get_track_display(track_a)}")
    print(f"End:   {get_track_display(track_b)}")

    # 3. Request Playlist
    print(f"\nRequesting playlist from {SERVICE_URL}/interpolate/playlist...")
    payload = {
        "track_id_1": track_a['id'],
        "track_id_2": track_b['id'],
        "limit": 20
    }
    
    response = requests.post(f"{SERVICE_URL}/interpolate/playlist", json=payload)
    if response.status_code != 200:
        print(f"❌ Error generating playlist: {response.text}")
        sys.exit(1)
        
    playlist = response.json()
    print(f"✅ Received Playlist with {len(playlist)} songs:\n")
    
    for i, track in enumerate(playlist):
        print(f"{i+1}. {get_track_display(track)}")

except Exception as e:
    print(f"\n❌ Unexpected Error: {e}")
    sys.exit(1)
