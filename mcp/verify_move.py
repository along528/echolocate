import asyncio
import os
import sys

# Add current directory to path so we can import modules in this folder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from record_crate import RecordCrate
from main import get_secret

# Simple secret fetcher for the script
def get_secret(secret_name):
    return os.getenv(secret_name)

async def main():
    token = get_secret("DISCOGS_TOKEN")
    if not token:
        print("DISCOGS_TOKEN not found in environment.")
        # Try to load from main.py's get_secret if possible, but that imports too much.
        # We'll assume the user runs this with the token env var or we can try to fetch it using gcloud if needed?
        # The main.py does it.
        # Let's just try to import get_secret from main but wrap in try/except to avoid ImportErrors
        try:
            from mcp.main import get_secret as gs
            token = gs("DISCOGS_TOKEN")
        except ImportError:
            pass
            
    if not token:
        print("Could not retrieve DISCOGS_TOKEN.")
        return

    crate = RecordCrate(token)
    try:
        identity = await crate.get_identity()
    except Exception as e:
        print(f"Auth failed: {e}")
        return

    username = identity.get("username")
    print(f"Logged in as: {username}")

    # 1. List Folders
    print("\n--- Folders ---")
    folders_data = await crate.get_collection_folders(username)
    folders = folders_data.get("folders", [])
    for f in folders:
        print(f"ID: {f['id']} | Name: {f['name']} | Count: {f['count']}")
    
    if len(folders) < 2:
        print("Need at least 2 folders (including All) to test move properly.")
        # If user only has All and Uncategorized, that's 2 folders (0 and 1).
        # We need to move from 1 to something else, or create a folder.
        # We don't have create folder tool yet.
        pass

    # 2. Pick a release to move
    # We prefer to find something in 'Uncategorized' (1) and move to another, or vice versa.
    # Let's just pick the first release we find in 'All'
    print("\n--- Picking a release from 'All' ---")
    releases_data = await crate.get_collection_releases(username, folder_id=0, per_page=1)
    releases = releases_data.get("releases", [])
    if not releases:
        print("Collection empty.")
        return

    release = releases[0]
    rid = release['basic_information']['id']
    title = release['basic_information']['title']
    current_folder_id = release['folder_id']
    instance_id = release['instance_id']
    
    print(f"Selected Release: {title} (ID: {rid})")
    print(f"Current Folder: {current_folder_id}")
    print(f"Instance ID: {instance_id}")

    # 3. Determine target folder
    # Find a folder that is NOT 0 and NOT current_folder_id
    target_folder = next((f for f in folders if f['id'] != 0 and f['id'] != current_folder_id), None)
    
    if not target_folder:
        print("No suitable target folder found.")
        # If current is 1, and no other folder exists, we can't move it anywhere (except 0? No you can't move to 0).
        # If current is NOT 1 (e.g. customized), we can move to 1.
        if current_folder_id != 1:
            target_folder = next((f for f in folders if f['id'] == 1), None)
            
    if not target_folder:
         print("Cannot find a destination folder (e.g. Uncategorized or other).")
         return

    print(f"Moving to Folder: {target_folder['name']} (ID: {target_folder['id']})")

    # 4. Verify get_instance_info works
    print("\nTesting get_instance_info...")
    info = await crate.get_instance_info(username, rid)
    if not info:
        print("Error: get_instance_info failed to find release!")
        return
    print(f"Found Info: {info}")
    if info['instance_id'] != instance_id:
        print(f"Warning: Instance ID mismatch! Expected {instance_id}, got {info['instance_id']}")
        instance_id = info['instance_id'] # Update to be safe

    # 5. Move
    print("\nTesting move_release_instance...")
    try:
        await crate.move_release_instance(username, current_folder_id, rid, instance_id, target_folder['id'])
        print("Move command executed.")
    except Exception as e:
        print(f"Move failed: {e}")
        return

    # 6. Verify Move
    print("\nVerifying move...")
    await asyncio.sleep(2) # Wait for eventual consistency if any
    info_after = await crate.get_instance_info(username, rid)
    print(f"New Info: {info_after}")
    
    if info_after and info_after['folder_id'] == target_folder['id']:
        print("PASSED: Release moved successfully!")
        
        # Cleanup: Move back
        print("Moving back to original folder...")
        await crate.move_release_instance(username, target_folder['id'], rid, instance_id, current_folder_id)
        print("Moved back. Done.")
    else:
        print(f"FAILED: Folder ID is {info_after['folder_id'] if info_after else 'None'}, expected {target_folder['id']}")

if __name__ == "__main__":
    asyncio.run(main())
