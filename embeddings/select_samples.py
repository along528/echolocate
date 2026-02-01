import os
import random
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SEARCH_DIR = os.path.join(PROJECT_ROOT, "crate", "Apple")
OUTPUT_FILE = os.path.join(DATA_DIR, "sample_files.txt")

def select_samples(limit=10000):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    print(f"Scanning {SEARCH_DIR}...")
    extensions = ['*.mp3', '*.m4a', '*.wav', '*.flac']
    files = []
    
    # We need to walk the directory
    for root, dirs, filenames in os.walk(SEARCH_DIR):
        for filename in filenames:
            if any(filename.lower().endswith(ext.replace('*', '')) for ext in extensions):
                full_path = os.path.join(root, filename)
                # Store relative path from project root
                rel_path = os.path.relpath(full_path, PROJECT_ROOT)
                files.append(rel_path)

    print(f"Found {len(files)} total audio files.")
    
    if not files:
        print("No audio files found.")
        return

    selected = random.sample(files, min(len(files), limit))
    
    with open(OUTPUT_FILE, 'w') as f:
        for path in selected:
            f.write(path + '\n')
            
    print(f"Selected {len(selected)} files:")
    for path in selected:
        print(f" - {path}")
    print(f"Saved list to {OUTPUT_FILE}")

if __name__ == "__main__":
    import sys
    limit = 10000
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"Invalid limit: {sys.argv[1]}. Using default {limit}.")
    
    select_samples(limit=limit)
