
import sys
import os
import pandas as pd

# Mocking the MCP server environment to test the logic directly
# We will just import the functions if possible, but they are decorated.
# We can just copy the logic or try to import the file. 
# Since they are decorated, we can still call them if the decorator wrapper allows it, 
# or we can test the dataframe sampling logic with a small snippet.

# Let's try to import the module. FastMCP might attempt to connect or run, but the decorators usually wrap the function.
# The global df load happens on import.

try:
    from local_server import search_library, get_rotation, search_albums, df, albums_df
except Exception as e:
    print(f"Error importing local_server: {e}")
    sys.exit(1)

def test_randomization(func, *args, name=""):
    print(f"Testing {name}...")
    results = set()
    for _ in range(3):
        res = func(*args)
        print(f"  Result length: {len(res.splitlines())}")
        results.add(res)
    
    if len(results) > 1:
        print(f"SUCCESS: {name} returned different results across calls.")
    else:
        # If the result set is small (e.g. only 1 match), it will always be the same.
        # We need to know if it SHOULD have been different.
        print(f"WARNING: {name} returned identical results. Check if total matches > limit.")

print("Library Size:", len(df))
print("Description:", df.describe())

if len(df) > 10:
    # Test search with a broad term if possible
    # We'll use a common letter like 'a' or 'e' to match many things
    test_randomization(search_library, "e", 5, name="search_library('e', limit=5)")
else:
    print("Library too small for effective random test.")

# Test Rotation
# We need to find a category with > 10 items
heavy_count = len(df[df['play_count'] > 20])
gold_count = len(df[df['play_count'] > 50])
unplayed_count = len(df[df['play_count'] == 0])

print(f"Heavy: {heavy_count}, Gold: {gold_count}, Unplayed: {unplayed_count}")

if heavy_count > 10:
    test_randomization(get_rotation, "Heavy", name="get_rotation('Heavy')")
elif gold_count > 10:
    test_randomization(get_rotation, "Gold", name="get_rotation('Gold')")
elif unplayed_count > 10:
    test_randomization(get_rotation, "Unplayed", name="get_rotation('Unplayed')")

