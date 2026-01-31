import requests
import sys
import random
import subprocess
import time

# Configuration
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else None

if not SERVICE_URL:
    print("Attempting to find service URL via gcloud...")
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "describe", "cloudcrate-vector", 
             "--region", "us-central1", "--format", "value(status.url)"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            SERVICE_URL = result.stdout.strip()
            print(f"Found URL: {SERVICE_URL}")
        else:
            print("Could not find service URL via gcloud.")
            SERVICE_URL = "http://localhost:8000"
            print(f"Falling back to local: {SERVICE_URL}")

    except Exception as e:
        print(f"Error finding URL: {e}")
        SERVICE_URL = "http://localhost:8000"
        print(f"Falling back to local: {SERVICE_URL}")

def get_track_display(track):
    return f"[{track.get('id', 'Unknown')}] {track.get('title', 'Unknown')}"

try:
    # 1. Fetch Tracks
    print(f"Fetching tracks from {SERVICE_URL}...")
    response = requests.get(f"{SERVICE_URL}/tracks", params={"limit": 100})
    if response.status_code != 200:
        print(f"Error listing tracks: {response.text}")
        sys.exit(1)
    tracks = response.json()
    
    if len(tracks) < 2:
        print("Not enough tracks.")
        sys.exit(1)

    # 2. Select 2 Random Tracks
    selected_tracks = random.sample(tracks, 2)
    track_a = selected_tracks[0]
    track_b = selected_tracks[1]
    
    print(f"Track A: {get_track_display(track_a)}")
    print(f"Track B: {get_track_display(track_b)}")

    # 3. Request Playlist Interpolation with SLERP (Default)
    print("\n--- Testing SLERP Playlist ---")
    payload_slerp = {
        "track_id_1": track_a['id'],
        "track_id_2": track_b['id'],
        "limit": 10,
        "method": "slerp"
    }
    resp_slerp = requests.post(f"{SERVICE_URL}/interpolate/playlist", json=payload_slerp)
    results_slerp = []
    if resp_slerp.status_code == 200:
        results_slerp = resp_slerp.json()
        print(f"SLERP success. Got {len(results_slerp)} songs.")
    else:
        print(f"SLERP Failed: {resp_slerp.text}")
        sys.exit(1)

    # 4. Request Playlist Interpolation with Linear
    print("\n--- Testing Linear Playlist ---")
    payload_linear = {
        "track_id_1": track_a['id'],
        "track_id_2": track_b['id'],
        "limit": 10,
        "method": "linear"
    }
    resp_linear = requests.post(f"{SERVICE_URL}/interpolate/playlist", json=payload_linear)
    results_linear = []
    if resp_linear.status_code == 200:
        results_linear = resp_linear.json()
        print(f"Linear success. Got {len(results_linear)} songs.")
    else:
        print(f"Linear Failed: {resp_linear.text}")
        sys.exit(1)

    # 5. Compare Results with Formatted Output
    print("\n" + "="*80)
    print(f"{'IDX':<4} | {'SLERP TRACK':<35} | {'LINEAR TRACK':<35}")
    print("-" * 80)
    
    ids_slerp = [t['id'] for t in results_slerp]
    ids_linear = [t['id'] for t in results_linear]
    
    # Titles for display
    titles_slerp = [t.get('title', 'Unknown')[:30] for t in results_slerp]
    titles_linear = [t.get('title', 'Unknown')[:30] for t in results_linear]
    
    max_len = max(len(ids_slerp), len(ids_linear))
    
    for i in range(max_len):
        slerp_val = titles_slerp[i] if i < len(titles_slerp) else ""
        linear_val = titles_linear[i] if i < len(titles_linear) else ""
        
        # Check if IDs match (not titles, as titles could be dupes but IDs distinct)
        sid = ids_slerp[i] if i < len(ids_slerp) else None
        lid = ids_linear[i] if i < len(ids_linear) else None
        
        diff_mark = " " if sid == lid else "*"
        print(f"{i:<4} | {slerp_val:<35} | {linear_val:<35} {diff_mark}")

    print("-" * 80)
    if ids_slerp == ids_linear:
        print("⚠️  Playlists are IDENTICAL.")
    else:
        print("✅ Playlists are DIFFERENT (* marks differences).")
    print("="*80)

    # Also trigger single interpolation just to check logs
    print("\n--- Triggering single interpolation for log check ---")
    requests.post(f"{SERVICE_URL}/interpolate", json={"track_id_1": track_a['id'], "track_id_2": track_b['id'], "method": "slerp"})
    requests.post(f"{SERVICE_URL}/interpolate", json={"track_id_1": track_a['id'], "track_id_2": track_b['id'], "method": "linear"})
    print("Requests sent. Check Cloud Run logs for 'Interpolating with method: ...'")

except Exception as e:
    print(f"Unexpected Error: {e}")
    sys.exit(1)
