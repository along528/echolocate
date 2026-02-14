import requests
import json
import random
import sys
import os

# Configuration
SERVICE_URL = sys.argv[1] if len(sys.argv) > 1 else None

if not SERVICE_URL:
    print("Usage: python verify_dissimilar.py <SERVICE_URL>")
    print("Attempting to find service URL via gcloud...")
    try:
        import subprocess
        result = subprocess.run(
            ["gcloud", "run", "services", "describe", "cloud-crate-vector", 
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

try:
    # 1. Get a random track to test with
    print(f"\n--- Getting a Random Track ({SERVICE_URL}/tracks) ---")
    response = requests.get(f"{SERVICE_URL}/tracks", params={"limit": 1, "random": True, "source": "all"})
    if response.status_code != 200 or not response.json():
        print(f"❌ Error getting random track: {response.text}")
        sys.exit(1)
        
    track = response.json()[0]
    print(f"Testing with Track: [{track['id']}] {track['title']} by {track['artist']}")

    # 2. Test Find Similar
    print(f"\n--- Testing Similar ({SERVICE_URL}/tracks/{{id}}/similar) ---")
    
    sim_response = requests.get(f"{SERVICE_URL}/tracks/{track['id']}/similar", params={"limit": 5})
    similar_scores = []
    if sim_response.status_code == 200:
        results = sim_response.json()
        print(f"✅ Found {len(results)} similar tracks:")
        for res in results:
            print(f" - {res['similarity']:.4f}: {res['title']} by {res['artist']}")
            similar_scores.append(res['similarity'])
    else:
        print(f"❌ Error finding similar tracks: {sim_response.text}")

    # 3. Test Find Dissimilar
    print(f"\n--- Testing Dissimilar ({SERVICE_URL}/tracks/{{id}}/dissimilar) ---")
    
    dis_response = requests.get(f"{SERVICE_URL}/tracks/{track['id']}/dissimilar", params={"limit": 5})
    dissimilar_scores = []
    if dis_response.status_code == 200:
        results = dis_response.json()
        print(f"✅ Found {len(results)} dissimilar tracks:")
        for res in results:
            print(f" - {res['similarity']:.4f}: {res['title']} by {res['artist']}")
            dissimilar_scores.append(res['similarity'])
    else:
        print(f"❌ Error finding dissimilar tracks: {dis_response.text}")
        
    # 4. Compare
    if similar_scores and dissimilar_scores:
        avg_sim = sum(similar_scores) / len(similar_scores)
        avg_dis = sum(dissimilar_scores) / len(dissimilar_scores)
        
        print(f"\n--- Comparison ---")
        print(f"Avg Similarity (Top Similar): {avg_sim:.4f}")
        print(f"Avg Similarity (Top Dissimilar): {avg_dis:.4f}")
        
        if avg_dis < avg_sim:
            print("✅ Verification PASSED: Dissimilar tracks have lower similarity scores.")
        else:
            print("❌ Verification FAILED: Dissimilar tracks do not have lower similarity scores.")
    else:
        print("⚠️ Not enough data to compare.")

except Exception as e:
    print(f"❌ Failed: {e}")
