import sys
import os

# Add the current directory to sys.path to make local_server importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from local_server import get_batch_track_context, get_batch_album_context, load_library, create_albums_df, df, albums_df

def run_verification():
    print("Verifying Batch MCP Functions...")
    
    # Ensure data is loaded (it loads on import in local_server, but good to check)
    if df.empty:
        print("Error: Library not loaded in local_server.")
        return

    print(f"Library loaded with {len(df)} tracks.")

    # 1. Test Batch Track Context
    print("\nTest 1: get_batch_track_context")
    # Get a few real IDs
    sample_ids = df['id'].head(3).tolist()
    # Add a fake one
    sample_ids.append("fake-id-123")
    
    print(f"Requesting context for IDs: {sample_ids}")
    track_result = get_batch_track_context(sample_ids)
    print("Result:")
    print(track_result)
    
    if "fake-id-123: Not found" in track_result and "Title:" in track_result:
        print("✅ Batch Track Context verification passed.")
    else:
        print("❌ Batch Track Context verification failed.")

    # 2. Test Batch Album Context
    print("\nTest 2: get_batch_album_context")
    # Get a few real albums
    if not albums_df.empty:
        sample_albums = albums_df['album_title'].head(2).tolist()
        sample_albums.append("Nonexistent Album")
        
        print(f"Requesting context for Albums: {sample_albums}")
        album_result = get_batch_album_context(sample_albums)
        print("Result:")
        print(album_result)
        
        if "Nonexistent Album': Not found" in album_result and "Album:" in album_result:
            print("✅ Batch Album Context verification passed.")
        else:
             print("❌ Batch Album Context verification failed.")
    else:
        print("Warning: Albums dataframe is empty, skipping album test.")

if __name__ == "__main__":
    run_verification()
