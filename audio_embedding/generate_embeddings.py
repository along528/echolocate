import os
import json
import glob
from embedding_lib import MusicEncoder, load_and_segment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "../data/embeddings_sample.json")

def generate_embeddings(directory, output_file=DEFAULT_OUTPUT, limit=5):
    """
    Scans directory for audio files, generates embeddings, and saves to JSON.
    """
    # Initialize Encoder
    encoder = MusicEncoder()
    
    results = []
    
    # Simple search for common audio formats
    extensions = ['*.mp3', '*.m4a', '*.wav', '*.flac']
    files = []
    # Check if directory exists
    if not os.path.isdir(directory):
        print(f"Directory not found: {directory}")
        return

    for ext in extensions:
        files.extend(glob.glob(os.path.join(directory, ext)))
        
    print(f"Found {len(files)} audio files in {directory}.")
    
    processed_count = 0
    
    for f in files:
        if processed_count >= limit:
            break
            
        print(f"Processing: {os.path.basename(f)}")
        segments = load_and_segment(f, target_sr=encoder.sampling_rate)
        
        if segments:
            # Generate Embeddings
            print("  Generating vectors...")
            emb_intro = encoder.get_embedding(segments['intro'])
            emb_mid = encoder.get_embedding(segments['mid'])
            emb_outro = encoder.get_embedding(segments['outro'])
            
            track_data = {
                "filename": os.path.basename(f),
                "path": f,
                "duration": segments['duration'],
                "v_intro": emb_intro,
                "v_mid": emb_mid,
                "v_outro": emb_outro
            }
            
            results.append(track_data)
            processed_count += 1
            
    # Save to JSON
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"Done! Saved {len(results)} embeddings to {output_file}")

if __name__ == "__main__":
    import sys
    # USER: Point this to a directory with a few music files
    # Defaulting to current dir or a 'music' subdir if it exists
    target_dir = "." # Scan current directory by default
    
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    elif os.path.exists("music"):
        target_dir = "music"
    
    limit = 5
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
        except ValueError:
            print("Invalid limit provided, using default.")

    generate_embeddings(target_dir, limit=limit)
