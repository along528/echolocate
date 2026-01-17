
import sys
import os

# Append current directory to path for imports
sys.path.append(os.getcwd())

from backend import local_server

def test_playlist_creation():
    # Use IDs we saw earlier in the crate
    track_ids = ["i.QXkvxtpV370", "i.6JNxBH8vAY1"] 
    playlist_name = "Cloud Crate Verification"
    
    print(f"--- Test 1: Preview Mode (confirm=False) ---")
    result_preview = local_server.create_playlist(playlist_name, track_ids, confirm=False)
    print("Result Preview:")
    print(result_preview)
    
    if "I will create a playlist named" not in result_preview:
        print("\nFAILED: Preview message not found.")
        return
        
    if "ask the user" not in result_preview:
        print("\nFAILED: Instruction to ask user not found.")
        return

    print("\n\n--- Test 2: Creation Mode (confirm=True) ---")
    print("Simulating user confirmation...")
    
    result_creation = local_server.create_playlist(playlist_name, track_ids, confirm=True)
    print("Result Creation:")
    print(result_creation)
    
    if "created/updated" not in result_creation:
        print("\nFAILED: Creation success message not found.")
    else:
        print("\nSUCCESS: Both preview and creation steps verified.")

if __name__ == "__main__":
    test_playlist_creation()
