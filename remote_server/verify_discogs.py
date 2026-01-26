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

    # Test 1: Search for Pharoah Sanders - Jewels of Thought
    print("\n--- Searching for 'Pharoah Sanders Jewels of Thought' ---")
    search_query = "Pharoah Sanders Jewels of Thought"
    
    if token == "DUMMY_TOKEN":
        print("⚠️  Skipping real API call due to dummy token.")
    else:
        results = await client.search(search_query, type="master")
        if results.get('results'):
            first = results['results'][0]
            master_id = first.get('id')
            print(f"✅ Found Master Release: {first.get('title')} (ID: {master_id})")
            
            # Test 2: Get All Versions
            print(f"\n--- Fetching Versions for Master ID {master_id} ---")
            # Fetch first 5 versions to keep it snappy for the test
            versions_data = await client.get_master_versions(master_id, per_page=5)
            versions = versions_data.get("versions", [])
            print(f"Found {len(versions)} versions (listing top 5).")
            
            # Collect Release IDs
            release_ids = [str(v.get('id')) for v in versions if v.get('id')]
            
            if release_ids:
                # Test 3: Batch Fetch Details
                print(f"\n--- Batch Fetching Details for {len(release_ids)} Releases ---")
                details = await client.get_releases(release_ids)
                
                for i, d in enumerate(details):
                    if isinstance(d, Exception):
                        print(f"❌ Error fetching ID {release_ids[i]}: {d}")
                    else:
                        print(f"✅ [{release_ids[i]}] {d.get('title')} ({d.get('year')}) - {d.get('country')}")
                        print(f"   Marketplace: {client.get_marketplace_url(release_ids[i])}")
            else:
                print("No release IDs found to fetch.")
        else:
            print(f"❌ No results found for query: {search_query}")

if __name__ == "__main__":
    asyncio.run(run_verification())
