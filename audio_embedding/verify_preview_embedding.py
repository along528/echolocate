
import os
import sys
import asyncio
import httpx
import tempfile
import numpy as np

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from remote_server.apple_music import AppleMusicClient
from audio_embedding.embedding_lib import MusicEncoder, load_and_segment

async def main():
    print("Starting verification...")
    
    # 1. Initialize Client
    team_id = os.getenv("APPLE_TEAM_ID")
    key_id = os.getenv("APPLE_KEY_ID")
    private_key = os.getenv("APPLE_PRIVATE_KEY")
    
    if not all([team_id, key_id, private_key]):
        print("Error: Missing Apple Music credentials in environment variables.")
        return

    client = AppleMusicClient(team_id, key_id, private_key)
    print("Apple Music Client initialized.")
    
    # 2. Search for songs to get IDs
    query = "Taylor Swift Anti-Hero"
    print(f"Searching for '{query}'...")
    search_results = await client.search(query, limit=3)
    
    songs = search_results.get("results", {}).get("songs", {}).get("data", [])
    if not songs:
        print("No songs found.")
        return
        
    ids = [s["id"] for s in songs]
    print(f"Found IDs: {ids}")
    
    # 3. Test get_songs (Batch Fetch)
    print("Fetching songs by ID (testing get_songs)...")
    batch_results = await client.get_songs(ids)
    
    batch_data = batch_results.get("data", [])
    print(f"Fetched {len(batch_data)} songs details.")
    
    # 4. Process Previews
    encoder = None
    
    for song in batch_data:
        attrs = song["attributes"]
        name = attrs["name"]
        artist = attrs["artistName"]
        previews = attrs.get("previews", [])
        
        if not previews:
            print(f"No preview for {name} - {artist}")
            continue
            
        preview_url = previews[0]["url"]
        print(f"\nProcessing {name} - {artist}")
        print(f"Preview URL: {preview_url}")
        
        # Prepare tmp directory
        tmp_dir = os.path.join(os.path.dirname(__file__), "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        
        # Sanitize filename
        safe_name = "".join([c for c in f"{name}-{artist}" if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        file_path = os.path.join(tmp_dir, f"{safe_name}.m4a")
        
        try:
            # Download Preview
            if not os.path.exists(file_path):
                async with httpx.AsyncClient() as http:
                    resp = await http.get(preview_url)
                    resp.raise_for_status()
                    with open(file_path, "wb") as f:
                        f.write(resp.content)
                print(f"Saved preview to {file_path}")
            else:
                print(f"Preview already exists at {file_path}")
            
            # Load and Segment
            print("Loading audio...")
            import librosa
            import json
            # Load the entire preview (usually ~30s)
            y, sr = librosa.load(file_path, sr=24000, mono=True)
            
            # Initialize Encoder (lazy load)
            if encoder is None:
                print("Loading Music Encoder...")
                encoder = MusicEncoder(device="cpu") # Force CPU for verification script to be safe/simple
                
            # Generate Embedding
            print("Generating Embedding...")
            embedding = encoder.get_embedding(y)
            print(f"Preview Embedding Shape: {len(embedding)}")
            
            # Save Embedding
            emb_path = os.path.join(tmp_dir, f"{safe_name}.json")
            with open(emb_path, "w") as f:
                json.dump(embedding, f)
            print(f"Saved embedding to {emb_path}")
            
            print("✅ Success!")
            
        except Exception as e:
            print(f"Error processing song: {e}")

if __name__ == "__main__":
    asyncio.run(main())
