import asyncio
import os
from discogs import DiscogsClient

async def get_secret_from_gsm(secret_name):
    # Try fetching from Google Secret Manager
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    # Try to guess project ID from gcloud if not set
    if not project_id:
        try:
             import subprocess
             result = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True)
             if result.returncode == 0:
                 project_id = result.stdout.strip()
        except Exception:
            pass
            
    if project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            print(f"Could not fetch {secret_name} from GSM: {e}")
            return None
    return None

async def run_verification():
    token = os.getenv("DISCOGS_TOKEN")
    if not token:
        print("Token not in env, trying Google Secret Manager...")
        token = await get_secret_from_gsm("DISCOGS_TOKEN")
        
    if not token:
        print("❌ DISCOGS_TOKEN not found in Env or GSM. Using a dummy token for loose verification...")
        token = "DUMMY_TOKEN"
    
    client = DiscogsClient(token)
    print(f"✅ Client initialized with token prefix: {token[:4]}...")

    # Test 1: Search (Mocked if dummy)
    print("\n--- Testing Search ---")
    try:
        if token == "DUMMY_TOKEN":
            print("⚠️  Skipping real API call due to dummy token.")
        else:
            results = await client.search("Daft Punk Random Access Memories", type="master")
            print(f"✅ Search successful. Found {len(results.get('results', []))} results.")
            if results.get('results'):
                first = results['results'][0]
                print(f"   First result: {first.get('title')} (ID: {first.get('id')})")
                
                # Test 2: Versions
                print("\n--- Testing Versions ---")
                master_id = first.get('id')
                versions = await client.get_master_versions(master_id, per_page=5)
                print(f"✅ Versions successful. Found {len(versions.get('versions', []))} versions.")
    except Exception as e:
        print(f"❌ API Error: {e}")

    # Test 3: Marketplace URL construction
    print("\n--- Testing Marketplace URL ---")
    url = client.get_marketplace_url("12345")
    expected = "https://www.discogs.com/sell/release/12345?ev=rb"
    if url == expected:
        print(f"✅ Marketplace URL correct: {url}")
    else:
        print(f"❌ Marketplace URL mismatch. Got: {url}")

    # Test 4: Batch Fetch (Mock if dummy)
    print("\n--- Testing Batch Fetch ---")
    if token == "DUMMY_TOKEN":
        print("⚠️  Skipping real batch fetch due to dummy token.")
    else:
        # Fetch the same release twice just to test concurrency mechanism
        ids = ["249504", "249504"] 
        print(f"Fetching {len(ids)} releases concurrently...")
        batch_results = await client.get_releases(ids)
        if len(batch_results) == 2 and not isinstance(batch_results[0], Exception):
             print(f"✅ Batch fetch successful. Got {len(batch_results)} results.")
        else:
             print(f"❌ Batch fetch failed or returned errors: {batch_results}")

if __name__ == "__main__":
    asyncio.run(run_verification())
