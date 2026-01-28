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
    # 1. Fetch all tracks
    print(f"\n--- 1. Fetching Tracks ({SERVICE_URL}/tracks) ---")
    response = requests.get(f"{SERVICE_URL}/tracks", params={"limit": 100}) # Fetch enough to get a good random selection
    if response.status_code != 200:
        print(f"❌ Error listing tracks: {response.text}")
        sys.exit(1)
        
    tracks = response.json()
    print(f"✅ Found {len(tracks)} tracks.")
    
    if len(tracks) < 2:
        print("❌ Not enough tracks to perform interpolation test (need at least 2).")
        sys.exit(1)

    # 2. Randomly select 2 songs
    print(f"\n--- 2. Selecting Random Tracks ---")
    selected_tracks = random.sample(tracks, 2)
    track_a = selected_tracks[0]
    track_b = selected_tracks[1]
    
    print(f"Track A: {get_track_display(track_a)}")
    print(f"Track B: {get_track_display(track_b)}")

    # 3. Interpolate between them
    print(f"\n--- 3. Interpolating ({SERVICE_URL}/interpolate) ---")
    payload = {
        "track_id_1": track_a['id'],
        "track_id_2": track_b['id'],
        "limit": 5
    }
    
    response = requests.post(f"{SERVICE_URL}/interpolate", json=payload)
    if response.status_code != 200:
        print(f"❌ Error interpolating: {response.text}")
        sys.exit(1)
        
    interpolated_results = response.json()
    print(f"✅ Found {len(interpolated_results)} interpolated tracks:")
    for res in interpolated_results:
        print(f" - {res['similarity']:.4f}: {get_track_display(res)}")

    if not interpolated_results:
        print("⚠️ No interpolated tracks found. Cannot proceed with checking similar songs for interpolated track.")
    else:
        # Pick the top interpolated song
        interpolated_track = interpolated_results[0]
        print(f"\nSelected Interpolated Track: {get_track_display(interpolated_track)}")

        # 4. Find similar songs for Original A, Original B, and Interpolated
        tracks_to_check = [
            ("Original A", track_a),
            ("Original B", track_b),
            ("Interpolated", interpolated_track)
        ]

        print(f"\n--- 4. Checking Similar Songs ---")
        for label, track in tracks_to_check:
            print(f"\n> Similar to {label}: {get_track_display(track)}")
            response = requests.get(f"{SERVICE_URL}/tracks/{track['id']}/similar", params={"limit": 3})
            
            if response.status_code == 200:
                similar_results = response.json()
                for res in similar_results:
                    print(f"   - {res['similarity']:.4f}: {get_track_display(res)}")
            else:
                print(f"   ❌ Error finding similar: {response.text}")

except Exception as e:
    print(f"\n❌ Unexpected Error: {e}")
    sys.exit(1)
