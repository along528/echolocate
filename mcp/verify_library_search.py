import os
import asyncio
import json
from apple_crate import AppleCrate

# --- Secret Configuration (Copied/Adapted from main.py) ---

def get_secret(secret_name, default=None, force_gsm=False):
    """
    Attempts to fetch a secret from Google Secret Manager.
    Falls back to environment variable if:
    1. GOOGLE_CLOUD_PROJECT is not set (local dev).
    2. Secret Manager API call fails (permissions/disabled).
    3. force_gsm is False and Env Var is present.
    """
    # 1. Check Env Var first (unless forced to ignore)
    if not force_gsm:
        env_val = os.getenv(secret_name)
        if env_val:
            return env_val

    # 2. Try Secret Manager
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            # print(f"Warning: Could not fetch secret {secret_name} from GSM: {e}")
            pass

    return default

# Load Secrets
APPLE_TEAM_ID = get_secret("APPLE_TEAM_ID")
APPLE_KEY_ID = get_secret("APPLE_KEY_ID")
APPLE_PRIVATE_KEY = get_secret("APPLE_PRIVATE_KEY")
APPLE_MUSIC_USER_TOKEN = get_secret("APPLE_MUSIC_USER_TOKEN", force_gsm=True)

async def main():
    if not all([APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY]):
        print("❌ Error: Missing Apple Music Developer Credentials")
        return

    if not APPLE_MUSIC_USER_TOKEN:
        print("❌ Error: Missing Apple Music User Token (APPLE_MUSIC_USER_TOKEN)")
        return

    print("✅ Credentials Found. Initializing Client...")
    try:
        client = AppleCrate(APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY)
    except Exception as e:
        print(f"❌ Error initializing client: {e}")
        return

    # Simulate Tool Arguments
    test_cases = [
        {"artist": "The Beatles"},
        {"title": "Fool On the Hill"},
        {"artist": "The Beatles", "title": "Fool On the Hill"}, # The problematic case
    ]

    for args in test_cases:
        # Simulate Tool Logic (Search + Filter)
        
        # 1. Determine Primary Search Term
        query = None
        if args.get("title"):
             query = args.get("title")
        elif args.get("album"):
             query = args.get("album")
        elif args.get("artist"):
             query = args.get("artist")
             
        if not query:
            print("❌ Error: No search terms provided")
            continue
            
        print(f"\n------------------------------------------------")
        print(f"🛠️  Testing Arguments: {args}")
        print(f"🔍 Primary Query: '{query}'")
        
        try:
            # --- Pass 1: Strict Search (Query + Filters) ---
            print("   (Pass 1: Strict Search)")
            strict_results = []
            limit_per_req = 25
            max_total = 100
            offset = 0
            
            while len(strict_results) < max_total:
                # Use primary query
                results = await client.search_library(query, APPLE_MUSIC_USER_TOKEN, limit=limit_per_req, offset=offset)
                batch = results.get("results", {}).get("library-songs", {}).get("data", [])
                
                if not batch: break
                
                for song in batch:
                    attrs = song.get("attributes", {})
                    # Apply Strict Filters
                    match = True
                    if args.get("artist"):
                        if args.get("artist").lower() not in attrs.get("artistName", "").lower():
                            match = False
                    if match and args.get("album"):
                         if args.get("album").lower() not in attrs.get("albumName", "").lower():
                            match = False
                    if match and args.get("title") and query != args.get("title"):
                         if args.get("title").lower() not in attrs.get("name", "").lower():
                            match = False
                            
                    if match:
                        strict_results.append(song)
                
                offset += len(batch)
                if len(batch) < limit_per_req: break
            
            print(f"     -> Found {len(strict_results)} strict matches")

            # --- Pass 2: Broad Title Search (Optional) ---
            broad_results = []
            
            if args.get("title"):
                print("   (Pass 2: Broad Title Search)")
                try:
                    res = await client.search_library(
                        args.get("title"), APPLE_MUSIC_USER_TOKEN, limit=5
                    )
                    broad_results = res.get("results", {}).get("library-songs", {}).get("data", [])
                    print(f"     -> Found {len(broad_results)} broad matches")
                except Exception as e:
                    print(f"     -> Broad search error: {e}")

            # --- Merge & Deduplicate ---
            final_songs = []
            seen_ids = set()
            
            for song in strict_results:
                if song['id'] not in seen_ids:
                    final_songs.append(song)
                    seen_ids.add(song['id'])
            
            for song in broad_results:
                if song['id'] not in seen_ids:
                    final_songs.append(song)
                    seen_ids.add(song['id'])
                    
            if not final_songs:
                print("⚠️ No results found.")
            else:
                print(f"✅ Final Results: {len(final_songs)}")
                max_results = args.get("limit", 5)
                for song in final_songs[:max_results]: 
                    attrs = song.get("attributes", {})
                    print(f"   🎵 {attrs.get('name')} - {attrs.get('artistName')}")
                    print(f"      Album: {attrs.get('albumName')}")
        except Exception as e:
            print(f"❌ Search failed: {e}")
            
    print(f"\n------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
