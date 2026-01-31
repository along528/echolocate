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
    return f"[{track.get('id', 'Unknown')}] {track.get('title', 'Unknown')} - {track.get('artist', 'Unknown')}"

def get_table_display(track):
    title = track.get('title', 'Unknown')
    artist = track.get('artist', 'Unknown')
    # Truncate to fit column
    display = f"{title} - {artist}"
    if len(display) > 48:
        display = display[:45] + "..."
    return display

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

    # 5. Request Playlist Interpolation with Greedy Walk
    print("\n--- Testing Greedy Walk Playlist ---")
    payload_greedy = {
        "track_id_1": track_a['id'],
        "track_id_2": track_b['id'],
        "limit": 10,
        "method": "greedy_walk"
    }
    resp_greedy = requests.post(f"{SERVICE_URL}/interpolate/playlist", json=payload_greedy)
    results_greedy = []
    if resp_greedy.status_code == 200:
        results_greedy = resp_greedy.json()
        print(f"Greedy Walk success. Got {len(results_greedy)} songs.")
    else:
        print(f"Greedy Walk Failed: {resp_greedy.text}")
        # Not exiting here so we can see other results

    # 6. Compare Results with Formatted Output
    print("\n" + "="*165)
    print(f"{'IDX':<4} | {'SLERP TRACK':<50} | {'LINEAR TRACK':<50} | {'GREEDY WALK TRACK':<50}")
    print("-" * 165)
    
    ids_slerp = [t['id'] for t in results_slerp]
    ids_linear = [t['id'] for t in results_linear]
    ids_greedy = [t['id'] for t in results_greedy]
    
    # Titles for display
    titles_slerp = [get_table_display(t) for t in results_slerp]
    titles_linear = [get_table_display(t) for t in results_linear]
    titles_greedy = [get_table_display(t) for t in results_greedy]
    
    max_len = max(len(ids_slerp), len(ids_linear), len(ids_greedy))
    
    for i in range(max_len):
        slerp_val = titles_slerp[i] if i < len(titles_slerp) else ""
        linear_val = titles_linear[i] if i < len(titles_linear) else ""
        greedy_val = titles_greedy[i] if i < len(titles_greedy) else ""
        
        print(f"{i:<4} | {slerp_val:<50} | {linear_val:<50} | {greedy_val:<50}")

    print("-" * 165)
    
    # Also trigger single interpolation just to check logs
    print("\n--- Triggering single interpolation for log check ---")
    requests.post(f"{SERVICE_URL}/interpolate", json={"track_id_1": track_a['id'], "track_id_2": track_b['id'], "method": "slerp"})
    requests.post(f"{SERVICE_URL}/interpolate", json={"track_id_1": track_a['id'], "track_id_2": track_b['id'], "method": "linear"})
    requests.post(f"{SERVICE_URL}/interpolate", json={"track_id_1": track_a['id'], "track_id_2": track_b['id'], "method": "greedy_walk"})
    print("Requests sent. Check Cloud Run logs for 'Interpolating with method: ...'")

except Exception as e:
    print(f"Unexpected Error: {e}")
    sys.exit(1)
