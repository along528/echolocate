import os
import json
import glob
import sys
from embedding_lib import MusicEncoder, load_and_segment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "../data/embeddings.json")
DEFAULT_FILE_LIST = os.path.join(BASE_DIR, "../data/sample_files.txt")

import time

def generate_embeddings(target_input, output_file=DEFAULT_OUTPUT, limit=None):
    """
    Generates embeddings for audio files.
    target_input: Can be a directory path OR a text file containing a list of relative paths.
    """
    # Initialize Encoder
    encoder = MusicEncoder()
    
    results = []
    files = []
    
    # Check if target_input is a list file or a directory
    if os.path.isfile(target_input) and target_input.endswith('.txt'):
        print(f"Reading file list from {target_input}...")
        with open(target_input, 'r') as f:
            lines = f.readlines()
            # Resolve relative paths to absolute
            for line in lines:
                rel_path = line.strip()
                if rel_path:
                    abs_path = os.path.join(PROJECT_ROOT, rel_path)
                    if os.path.exists(abs_path):
                        files.append({"msg": "Found", "path": abs_path, "rel_path": rel_path})
                    else:
                        print(f"Warning: File not found: {abs_path}")
    elif os.path.isdir(target_input):
         # Simple search for common audio formats
        print(f"Scanning directory {target_input}...")
        extensions = ['*.mp3', '*.m4a', '*.wav', '*.flac']
        for ext in extensions:
            for f in glob.glob(os.path.join(target_input, ext)):
                 rel_path = os.path.relpath(f, PROJECT_ROOT)
                 files.append({"msg": "Found", "path": f, "rel_path": rel_path})
    else:
        print(f"Target not found: {target_input}")
        return

    print(f"Found {len(files)} audio files to process.")
    
    processed_count = 0
    total_duration = 0
    
    for item in files:
        if limit and processed_count >= limit:
            break
            
        f = item['path']
        rel_path = item['rel_path']
        
        start_time = time.time()
        print(f"[{processed_count + 1}/{len(files)}] Processing: {rel_path}")
        
        try:
            segments = load_and_segment(f, target_sr=encoder.sampling_rate)
            
            if segments:
                # Generate Embeddings
                # print("  Generating vectors...") # Reduced verbosity
                emb_intro = encoder.get_embedding(segments['intro'])
                emb_mid = encoder.get_embedding(segments['mid'])
                emb_outro = encoder.get_embedding(segments['outro'])
                
                # Extract Metadata from path
                # Expecting: crate/Artist/Album/Title.ext
                parts = rel_path.split(os.sep)
                artist = "Unknown"
                album = "Unknown"
                title = os.path.splitext(os.path.basename(f))[0]
                
                if len(parts) >= 4 and parts[0] == 'crate':
                     # crate/Apple/Artist/Album/Title -> index -3, -2
                     # Actually structure seems to be crate/Source/Artist/Album/Title
                     # Let's try to be flexible.
                     artist = parts[-3]
                     album = parts[-2]
                
                track_data = {
                    "filename": os.path.basename(f),
                    "relative_path": rel_path,
                    "artist": artist,
                    "album": album,
                    "title": title,
                    "duration": segments['duration'],
                    "v_intro": emb_intro,
                    "v_mid": emb_mid,
                    "v_outro": emb_outro
                }
                
                results.append(track_data)
                processed_count += 1
                
                duration = time.time() - start_time
                total_duration += duration
                avg_time = total_duration / processed_count
                
                # Estimate remaining
                remaining_items = limit - processed_count if limit else len(files) - processed_count
                remaining_time = avg_time * remaining_items
                
                print(f"  > Processed in {duration:.2f}s. Avg: {avg_time:.2f}s. Est. Remaining: {remaining_time/60:.2f}m")
                
        except Exception as e:
            print(f"Error processing {f}: {e}")
            
    # Save to JSON
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"Done! Saved {len(results)} embeddings to {output_file}")

if __name__ == "__main__":
    target = "." 
    limit = None
    
    # Priority 1: Argument passed
    if len(sys.argv) > 1:
        target = sys.argv[1]
    # Priority 2: Default file list exists
    elif os.path.exists(DEFAULT_FILE_LIST):
        target = DEFAULT_FILE_LIST
    # Priority 3: 'music' directory
    elif os.path.exists("music"):
        target = "music"
    
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
        except ValueError:
            pass

    generate_embeddings(target, limit=limit)
