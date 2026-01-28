import requests
import json
import random
import sys

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
            sys.exit(1)
    except Exception as e:
        print(f"Error finding URL: {e}")
        sys.exit(1)

# Load a sample vector
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "../data/embeddings.json")

try:
    with open(DATA_PATH, "r") as f:
        data = json.load(f)
        
    # Get a random vector
    if isinstance(data, list):
        item = random.choice(data)
        vector = item.get('v_mid') or item.get('v_intro')
    elif isinstance(data, dict):
        key = random.choice(list(data.keys()))
        item = data[key]
        vector = item.get('v_mid') or item.get('v_intro')
        
    if not vector:
        print("Could not find a valid vector in sample data.")
        sys.exit(1)

    print(f"Querying {SERVICE_URL} with vector from '{item.get('filename') or item.get('title')}'...")
    
    response = requests.post(
        f"{SERVICE_URL}/search",
        json={"vector": vector, "limit": 5}
    )
    
    if response.status_code == 200:
        results = response.json()
        print(f"✅ Success! Found {len(results)} results:")
        for res in results:
            rel_path = res.get('relative_path', 'N/A')
            print(f" - {res['similarity']:.4f}: {res['title']} by {res['artist']} ({rel_path})")
    else:
        print(f"❌ Error {response.status_code}: {response.text}")

except Exception as e:
    print(f"❌ Failed: {e}")
