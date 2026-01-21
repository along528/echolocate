import sys
import os
import json
import time

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import local_server

def run_verification():
    print("Running Record Label Verification...")
    
    # 1. Search Album Tracks (should now include Label)
    # Using "Thriller" as a reliable test case (Epic/Sony)
    album_name = "Thriller"
    print(f"\n--- Test 1: Searching Album Tracks for '{album_name}' ---")
    try:
        result = local_server.search_album_tracks(album_name, "Michael Jackson")
        print("Result Preview:")
        print(result[:500] + "..." if len(result) > 500 else result)
        
        if "Record Label:" in result:
            print("\n✅ SUCCESS: Record Label found in search_album_tracks output.")
        else:
            print("\n❌ FAILURE: Record Label NOT found in search_album_tracks output.")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        
    # 2. Get Album Details directly
    print(f"\n--- Test 2: Fetching Album Details for '{album_name}' ---")
    
    try:
        # Get ID via raw invocation
        print("Finding Album ID...")
        search_out = local_server.invoke_edge("search-catalog", ["--query", "Thriller", "--limit", "1", "--types", "albums"])
        search_res = json.loads(search_out)
        
        if search_res:
            album_id = search_res[0]['id']
            print(f"Found Album ID: {album_id}")
            
            details = local_server.get_album_details(album_id)
            print("Details Output:")
            print(details)
            
            if "Record Label:" in details and "catalog:" in details:
                 print("\n✅ SUCCESS: Record Label found in get_album_details.")
            else:
                 print("\n❌ FAILURE: Record Label missing or unexpected.")
                 
            # 3. Test Get Record Label Releases (using the ID we found)
            if "ID: catalog:" in details:
                # Extract label ID
                import re
                match = re.search(r"ID: catalog:([0-9]+)", details)
                if match:
                    label_id = match.group(1) # We use raw ID for edge call usually, or does it handle prefix? 
                    # get_record_label_releases takes name usually? 
                    # local_server.get_record_label_releases(label_name) -> calls search-catalog types=labels
                    
                    # But we want to test fetching releases if we have the ID?
                    # The tool `get_record_label_releases` takes a NAME and searches for it.
                    # It doesn't take an ID directly.
                    # But we can verify `search_record_label` works.
                    pass
        else:
            print("❌ FAILURE: Could not find album 'Thriller'.")
            
    except Exception as e:
        print(f"❌ Error during verification: {e}")

if __name__ == "__main__":
    run_verification()
