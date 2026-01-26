import asyncio
import os
from discogs import DiscogsClient

async def run_verification():
    token = os.getenv("DISCOGS_TOKEN")
    if not token:
        print("❌ DISCOGS_TOKEN not found. Using a dummy token for loose verification...")
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

if __name__ == "__main__":
    asyncio.run(run_verification())
