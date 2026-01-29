import os
import asyncio
import json
from apple_music import AppleMusicClient

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
        client = AppleMusicClient(APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY)
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
        # Simulate Tool Logic
        parts = []
        if args.get("artist"): parts.append(args.get("artist"))
        if args.get("album"): parts.append(args.get("album"))
        if args.get("title"): parts.append(args.get("title"))
        query = " - ".join(parts)
        
        print(f"\n------------------------------------------------")
        print(f"🛠️  Testing Arguments: {args}")
        print(f"🔍 Constructed Query: '{query}'")
        
        try:
            results = await client.search_library(query, APPLE_MUSIC_USER_TOKEN, limit=3)
            
            # Parse and print results
            songs = results.get("results", {}).get("library-songs", {}).get("data", [])
            
            if not songs:
                print("⚠️ No results found.")
            else:
                print(f"✅ Found {len(songs)} results:")
                for song in songs:
                    attrs = song.get("attributes", {})
                    print(f"   🎵 {attrs.get('name')} - {attrs.get('artistName')}")
        except Exception as e:
            print(f"❌ Search failed: {e}")
            
    print(f"\n------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
