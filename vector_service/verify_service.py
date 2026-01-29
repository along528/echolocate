import requests
import json
import random
import sys
import os

# Configuration
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else None

if not SERVICE_URL:
    print("Usage: python verify_service.py <SERVICE_URL>")
    # Try to find url from gcloud if not provided? 
    # For now, let's just error or ask user to provide it.
    # Actually, I can try to grab it from the deploy output if I could, 
    # but simpler to just run the deploy command manually or fetch it.
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
            # Fallback to local
            SERVICE_URL = "http://localhost:8000"
            print(f"Falling back to local: {SERVICE_URL}")

    except Exception as e:
        print(f"Error finding URL: {e}")
        SERVICE_URL = "http://localhost:8000"
        print(f"Falling back to local: {SERVICE_URL}")

try:
    # 1. Test List Endpoint
    print(f"\n--- Testing List Tracks ({SERVICE_URL}/tracks) ---")
    response = requests.get(f"{SERVICE_URL}/tracks", params={"limit": 5})
    if response.status_code == 200:
        tracks = response.json()
        print(f"✅ Success! Found {len(tracks)} tracks:")
        for t in tracks:
            print(f" - [{t['id']}] {t['title']} by {t['artist']}")
        
        if len(tracks) < 2:
            print("❌ Not enough tracks to test interpolation.")
            sys.exit(1)
            
        track1 = tracks[0]
        track2 = tracks[1]
    else:
        print(f"❌ Error listing tracks: {response.text}")
        sys.exit(1)

    # 2. Test Find Similar By ID
    print(f"\n--- Testing Similar By ID ({SERVICE_URL}/tracks/{{id}}/similar) ---")
    print(f"Finding similar to: {track1['title']} ({track1['id']})")
    
    response = requests.get(f"{SERVICE_URL}/tracks/{track1['id']}/similar", params={"limit": 3})
    if response.status_code == 200:
        results = response.json()
        print(f"✅ Success! Found {len(results)} similar tracks:")
        for res in results:
            print(f" - {res['similarity']:.4f}: {res['title']} by {res['artist']}")
    else:
        print(f"❌ Error finding similar tracks: {response.text}")

    # 3. Test Sonic Interpolation
    print(f"\n--- Testing Sonic Interpolation ({SERVICE_URL}/interpolate) ---")
    print(f"Interpolating between:")
    print(f"  A: {track1['title']} by {track1['artist']}")
    print(f"  B: {track2['title']} by {track2['artist']}")
    
    payload = {
        "track_id_1": track1['id'],
        "track_id_2": track2['id'],
        "limit": 5
    }
    
    response = requests.post(f"{SERVICE_URL}/interpolate", json=payload)
    if response.status_code == 200:
        results = response.json()
        print(f"✅ Success! Found {len(results)} interpolated tracks:")
        for res in results:
            print(f" - {res['similarity']:.4f}: {res['title']} by {res['artist']}")
    else:
        print(f"❌ Error interpolating: {response.text}")

except Exception as e:
    print(f"❌ Failed: {e}")
