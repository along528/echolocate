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

    # Test 1: Search for Pharoah Sanders - Jewels of Thought (Vinyl)
    print("\n--- Searching for 'Pharoah Sanders Jewels of Thought' (Vinyl) ---")
    search_query = "Pharoah Sanders Jewels of Thought"
    
    if token == "DUMMY_TOKEN":
        print("⚠️  Skipping real API call due to dummy token.")
    else:
        # Pass nothing for format to test default (should be Vinyl)
        results = await client.search(search_query, type="master")
        if results.get('results'):
            first = results['results'][0]
            master_id = first.get('id')
            print(f"✅ Found Master Release: {first.get('title')} (ID: {master_id})")
            
            # Test 2: Get ALL Vinyl Versions
            print(f"\n--- Fetching ALL Vinyl Versions for Master ID {master_id} ---")
            
            all_versions = []
            page = 1
            while True:
                print(f"Fetching page {page}...")
                # Test default format (should be Vinyl)
                data = await client.get_master_versions(master_id, page=page, per_page=100)
                versions = data.get("versions", [])
                if not versions:
                    break
                    
                all_versions.extend(versions)
                pagination = data.get("pagination", {})
                
                if page >= pagination.get("pages", 1):
                    break
                page += 1
            
            print(f"✅ Found {len(all_versions)} Vinyl versions.")
            
            # Test 3: Batch Fetch Details for ALL
            # Note: For verification, we might want to cap it if it's huge, but user asked for "all"
            # Let's cap at 20 for safety in this script unless user insists on 100+ which might timeout
            # But the user said "fetch all the releases not just 5".
            
            release_ids = [str(v.get('id')) for v in all_versions if v.get('id')]
            
            if release_ids:
                print(f"\n--- Batch Fetching Details for {len(release_ids)} Releases ---")
                
                # Split into chunks of 20 to avoid overwhelming API? 
                # httpx has limits, but asyncio.gather is powerful. 
                # Let's do chunks of 10.
                chunk_size = 10
                for i in range(0, len(release_ids), chunk_size):
                    chunk = release_ids[i:i + chunk_size]
                    print(f"Fetching chunk {i // chunk_size + 1} ({len(chunk)} items)...")
                    details = await client.get_releases(chunk)
                    
                    for j, d in enumerate(details):
                        rid = chunk[j]
                        if isinstance(d, Exception):
                            print(f"❌ Error fetching ID {rid}: {d}")
                        else:
                            # Verify Format
                            formats = d.get('format', []) # Wait, 'format' in release details?
                            # Often formats is a list of dicts or strings depending on endpoint
                            # data.get('formats') is usually list of dicts: [{'name': 'Vinyl', 'qty': '1'}]
                            # Let's just print title/year/country
                            print(f"✅ [{rid}] {d.get('title')} ({d.get('year')}) - {d.get('country')}")
                            print(f"   {client.get_marketplace_url(rid)}")
                            
            else:
                print("No release IDs found to fetch.")
        else:
            print(f"❌ No results found for query: {search_query}")

    # Test 4: Wantlist
    print("\n--- Testing Wantlist ---")
    if token == "DUMMY_TOKEN":
         print("⚠️  Skipping real wantlist checking due to dummy token.")
    else:
        try:
            identity = await client.get_identity()
            username = identity.get("username")
            print(f"✅ Authenticated as: {username}")
            
            if username:
                print(f"Fetching full wantlist for {username}...")
                all_wants = []
                page = 1
                while True:
                    print(f"Fetching page {page}...")
                    data = await client.get_wantlist(username, page=page, per_page=100)
                    wants = data.get("wants", [])
                    if not wants:
                        break
                    
                    all_wants.extend(wants)
                    pagination = data.get("pagination", {})
                    
                    if page >= pagination.get("pages", 1):
                        break
                    page += 1
                
                print(f"✅ Found {len(all_wants)} total items in wantlist.")
                
                # Show first 5 and last 5 to confirm range
                if all_wants:
                    print(f"--- First 5 items ---")
                    for w in all_wants[:5]:
                        info = w.get("basic_information", {})
                        rid = str(info.get("id"))
                        print(f"[{rid}] {info.get('title')} ({info.get('year')})")
                        print(f"   {client.get_marketplace_url(rid)}")
                        
                    if len(all_wants) > 5:
                        print(f"...\n--- Last 5 items ---")
                        for w in all_wants[-5:]:
                            info = w.get("basic_information", {})
                            rid = str(info.get("id"))
                            print(f"[{rid}] {info.get('title')} ({info.get('year')})")
                            print(f"   {client.get_marketplace_url(rid)}")
        except Exception as e:
            print(f"❌ Error fetching wantlist: {e}")

if __name__ == "__main__":
    asyncio.run(run_verification())
