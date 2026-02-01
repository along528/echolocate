import os
import asyncio
import json
from record_crate import RecordCrate

def get_secret(secret_name, default=None, force_gsm=False):
    """
    Attempts to fetch a secret from Google Secret Manager.
    """
    if not force_gsm:
        env_val = os.getenv(secret_name)
        if env_val:
            return env_val

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            pass
    return default

DISCOGS_TOKEN = get_secret("DISCOGS_TOKEN")

async def main():
    if not DISCOGS_TOKEN:
        print("❌ Error: Missing DISCOGS_TOKEN")
        return

    print("✅ Credentials Found. Initializing Client...")
    crate = RecordCrate(DISCOGS_TOKEN)

    try:
        # 1. Get Identity
        identity = await crate.get_identity()
        username = identity.get("username")
        print(f"👤 Authenticated as: {username}")
        
        if not username:
             print("❌ Could not determine username.")
             return

        # 2. Find a Release to Add (search for something specific)
        print("🔍 Searching for 'Daft Punk Random Access Memories'...")
        search_res = await crate.search("Daft Punk Random Access Memories", type="master")
        results = search_res.get("results", [])
        if not results:
            print("❌ No results found to test with.")
            return

        master_id = results[0].get("id")
        print(f"   Found Master ID: {master_id}")
        
        # Get a specific release version (Wantlist works on Releases, not Masters usually, though API might support masters, UI usually lists releases)
        # Let's get versions and pick the first one.
        versions_res = await crate.get_master_versions(master_id)
        versions = versions_res.get("versions", [])
        if not versions:
             print("❌ No versions found.")
             return
             
        target_release_id = str(versions[0].get("id"))
        print(f"   Target Release ID: {target_release_id} ({versions[0].get('title')})")

        # 3. Add to Wantlist
        print(f"➕ Adding {target_release_id} to Wantlist...")
        await crate.add_to_wantlist(username, target_release_id, notes="Test Add via MCP", rating=5)
        print("   done.")

        # 4. Verify
        print("📋 Verifying Wantlist...")
        # Give API a moment? usually consistent
        await asyncio.sleep(1) 
        
        wantlist_res = await crate.get_wantlist(username)
        wants = wantlist_res.get("wants", [])
        found = False
        for w in wants:
            rid = str(w.get("basic_information", {}).get("id"))
            if rid == target_release_id:
                print(f"✅ Found {rid} in wantlist! (Notes: {w.get('notes')})")
                found = True
                break
        
        if not found:
            print(f"❌ Failed to find {target_release_id} in wantlist.")

        # 5. Cleanup
        print(f"➖ Removing {target_release_id} from Wantlist...")
        await crate.remove_from_wantlist(username, target_release_id)
        print("   done.")
        
        # 6. Verify Removal
        print("📋 Verifying Removal...")
        await asyncio.sleep(1)
        wantlist_res = await crate.get_wantlist(username)
        wants = wantlist_res.get("wants", [])
        found_again = False
        for w in wants:
            rid = str(w.get("basic_information", {}).get("id"))
            if rid == target_release_id:
                found_again = True
                break
        
        if not found_again:
            print("✅ Verified removal.")
        else:
            print("❌ Item still in wantlist.")

    except Exception as e:
        print(f"❌ Verification failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
