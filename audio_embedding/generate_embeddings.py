import os
import json
import glob
import sys
from embedding_lib import MusicEncoder, load_and_segment
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "../data/embeddings.jsonl")
DEFAULT_FILE_LIST = os.path.join(BASE_DIR, "../data/sample_files.txt")

def generate_embeddings(target_input, output_file=DEFAULT_OUTPUT, limit=None):
    """
    Generates embeddings for audio files.
    target_input: Can be a directory path OR a text file containing a list of relative paths.
    """
    
    # 1. Load already processed files (Resume Capability)
    processed_paths = set()
    if os.path.exists(output_file):
        print(f"Checking existing output file {output_file} for resume...")
        try:
            with open(output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if 'relative_path' in data:
                                processed_paths.add(data['relative_path'])
                        except json.JSONDecodeError:
                            pass # Skip invalid lines
            print(f"Found {len(processed_paths)} already processed files.")
        except Exception as e:
            print(f"Error reading existing file: {e}")

    # 2. Gather Files
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

    # Filter out processed files
    files_to_process = [f for f in files if f['rel_path'] not in processed_paths]
    print(f"Found {len(files)} total files. {len(files_to_process)} to process.")
    
    if not files_to_process:
        print("All files processed.")
        return

    # Initialize Encoder (only if needed)
    encoder = MusicEncoder()

    processed_count = 0
    total_duration = 0
    
    # Open file in append mode for eager writing
    with open(output_file, 'a') as out_f:
        for item in files_to_process:
            if limit and processed_count >= limit:
                break
                
            f_path = item['path']
            rel_path = item['rel_path']
            
            start_time = time.time()
            print(f"[{processed_count + 1}/{len(files_to_process)}] Processing: {rel_path}")
            
            try:
                segments = load_and_segment(f_path, target_sr=encoder.sampling_rate)
                
                if segments:
                    # Generate Embeddings
                    emb_intro = encoder.get_embedding(segments['intro'])
                    emb_mid = encoder.get_embedding(segments['mid'])
                    emb_outro = encoder.get_embedding(segments['outro'])
                    
                    # Extract Metadata from path
                    parts = rel_path.split(os.sep)
                    artist = "Unknown"
                    album = "Unknown"
                    title = os.path.splitext(os.path.basename(f_path))[0]
                    
                    if len(parts) >= 4 and parts[0] == 'crate':
                         # Structure: crate/Source/Artist/Album/Title
                         artist = parts[-3]
                         album = parts[-2]
                    
                    track_data = {
                        "filename": os.path.basename(f_path),
                        "relative_path": rel_path,
                        "artist": artist,
                        "album": album,
                        "title": title,
                        "duration": segments['duration'],
                        "v_intro": emb_intro,
                        "v_mid": emb_mid,
                        "v_outro": emb_outro
                    }
                    
                    # Write to file immediately (JSONL)
                    out_f.write(json.dumps(track_data) + "\n")
                    out_f.flush()
                    
                    processed_count += 1
                    
                    duration = time.time() - start_time
                    total_duration += duration
                    avg_time = total_duration / processed_count
                    
                    # Estimate remaining
                    remaining_items = limit - processed_count if limit else len(files_to_process) - processed_count
                    remaining_time = avg_time * remaining_items
                    
                    print(f"  > Processed in {duration:.2f}s. Avg: {avg_time:.2f}s. Est. Remaining: {remaining_time/60:.2f}m")
                    
            except Exception as e:
                print(f"Error processing {f_path}: {e}")
            
    print(f"Done! Processed {processed_count} new files.")

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
