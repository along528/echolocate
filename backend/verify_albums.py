
import pandas as pd
import sys
import os
import json

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the local_server module
import local_server

def run_verification():
    print("Running Verification for Album and Genre Features...")
    
    # Load test data manually to inject into local_server
    test_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_library.json")
    print(f"Loading test data from {test_file}")
    
    with open(test_file, 'r') as f:
        data = json.load(f)
        
    df = pd.DataFrame(data)
    df['last_played_at'] = pd.to_datetime(df['last_played_at'], utc=True)
    
    # Inject into local_server
    local_server.df = df
    local_server.albums_df = local_server.create_albums_df(df)
    
    print(f"Injected {len(local_server.df)} tracks and {len(local_server.albums_df)} albums.")
    
    # Test 1: Search Albums
    print("\n--- Test 1: Search Albums 'Ambient' ---")
    result = local_server.search_albums("Ambient")
    print(result)
    assert "Ambient 1" in result
    assert "Selected Ambient Works" in result
    
    # Test 2: Get Album Context
    print("\n--- Test 2: Get Album Context 'Head Hunters' ---")
    result = local_server.get_album_context("Head Hunters")
    print(result)
    assert "Herbie Hancock" in result
    assert "Total Plays: 85" in result
    assert "Funk" in result
    
    # Test 3: Search by Genre
    print("\n--- Test 3: Search by Genre 'Techno' ---")
    result = local_server.search_by_genre("Techno")
    print(result)
    assert "Aphex Twin" in result
    
    # Test 4: Similar Artists
    # We need to add another artist to the test data to test similarity effectively?
    # Current test data: 
    # 1. Brian Eno (Ambient, Electronic)
    # 2. Aphex Twin (Ambient, Techno, IDM)
    # 3. Herbie Hancock (Jazz, Funk, Fusion)
    # Eno and Aphex share "Ambient".
    
    print("\n--- Test 4: Similar Artists 'Brian Eno' ---")
    result = local_server.find_similar_artists("Brian Eno")
    print(result)
    assert "Aphex Twin" in result
    assert "Overlap: 1" in result # Shared "Ambient"
    
    print("\nVerification passed!")

if __name__ == "__main__":
    run_verification()
