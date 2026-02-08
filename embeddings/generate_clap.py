"""
CLAP Batch Embedding Generator
==============================
Generates CLAP embeddings for the audio library as a sidecar to MERT.
Operates independently with its own output file (clap_embeddings.jsonl).

Usage:
    python generate_clap.py [file_list.txt] [limit]
    python generate_clap.py ../data/library/sample_files.txt 100
"""

import os
import json
import sys
import time
import torch
import librosa
from transformers import AutoProcessor, ClapModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DEFAULT_OUTPUT = os.path.join(BASE_DIR, "../data/library/clap_embeddings.jsonl")
DEFAULT_FILE_LIST = os.path.join(BASE_DIR, "../data/library/sample_files.txt")

# CLAP-specific constants
CLAP_MODEL_NAME = "laion/clap-htsat-unfused"
CLAP_SAMPLE_RATE = 48000  # Non-negotiable for CLAP performance
CLAP_DURATION = 10  # 10 seconds from middle of track
CLAP_OFFSET = 30    # Skip first 30 seconds
BATCH_SIZE = 4       # Batch size for memory efficiency on Intel MBP


class ClapEncoder:
    """CLAP model wrapper for batch audio embedding generation."""
    
    def __init__(self, device=None):
        if device is None:
            # Force CPU for stability on Intel MBP
            self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)
        
        print(f"Loading CLAP model: {CLAP_MODEL_NAME}...")
        self.model = ClapModel.from_pretrained(CLAP_MODEL_NAME).to(self.device)
        self.processor = AutoProcessor.from_pretrained(CLAP_MODEL_NAME)
        self.model.eval()
        print(f"CLAP model loaded on {self.device}.")
    
    def get_embeddings_batch(self, audio_list: list[tuple]) -> list[tuple]:
        """
        Process a batch of audio arrays and return normalized embeddings.
        
        Args:
            audio_list: List of (relative_path, audio_array) tuples
        
        Returns:
            List of (relative_path, embedding_list) tuples
        """
        if not audio_list:
            return []
        
        rel_paths = [item[0] for item in audio_list]
        audios = [item[1] for item in audio_list]
        
        # Process batch
        inputs = self.processor(
            audios=audios, 
            sampling_rate=CLAP_SAMPLE_RATE, 
            return_tensors="pt",
            padding=True
        ).to(self.device)
        
        with torch.no_grad():
            audio_features = self.model.get_audio_features(**inputs)
            # L2 normalize
            audio_features /= audio_features.norm(dim=-1, keepdim=True)
        
        # Convert to list format
        results = []
        for i, rel_path in enumerate(rel_paths):
            embedding = audio_features[i].cpu().numpy().tolist()
            results.append((rel_path, embedding))
        
        return results


def load_audio_for_clap(file_path: str, rel_path: str) -> tuple:
    """
    Load audio file for CLAP processing.
    Returns (audio_array, success, skip_reason) tuple.
    """
    try:
        # Load 10s from middle at 48kHz (CLAP requirement)
        audio, _ = librosa.load(
            file_path, 
            sr=CLAP_SAMPLE_RATE, 
            duration=CLAP_DURATION, 
            offset=CLAP_OFFSET
        )
        
        # Check minimum length (at least 1 second)
        if len(audio) < CLAP_SAMPLE_RATE:
            return None, False, f"Too short after offset ({len(audio)/CLAP_SAMPLE_RATE:.1f}s < 1s)"
        
        return audio, True, None
    except Exception as e:
        return None, False, str(e)


def generate_clap_embeddings(target_input: str, output_file: str = DEFAULT_OUTPUT, limit: int = None):
    """
    Generate CLAP embeddings for audio files.
    
    Args:
        target_input: Path to a .txt file containing relative paths
        output_file: Output JSONL file path
        limit: Optional limit on number of files to process
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
                            pass
            print(f"Found {len(processed_paths)} already processed files.")
        except Exception as e:
            print(f"Error reading existing file: {e}")
    
    # 2. Gather files to process
    files = []
    
    if os.path.isfile(target_input) and target_input.endswith('.txt'):
        print(f"Reading file list from {target_input}...")
        with open(target_input, 'r') as f:
            for line in f:
                rel_path = line.strip()
                if rel_path:
                    abs_path = os.path.join(PROJECT_ROOT, rel_path)
                    if os.path.exists(abs_path):
                        files.append({"path": abs_path, "rel_path": rel_path})
                    else:
                        print(f"Warning: File not found: {abs_path}")
    else:
        print(f"Error: Expected a .txt file list, got: {target_input}")
        return
    
    # Filter out already processed
    files_to_process = [f for f in files if f['rel_path'] not in processed_paths]
    print(f"Found {len(files)} total files. {len(files_to_process)} to process.")
    
    if not files_to_process:
        print("All files already processed.")
        return
    
    # Apply limit
    if limit:
        files_to_process = files_to_process[:limit]
        print(f"Limiting to {limit} files.")
    
    # 3. Initialize encoder
    encoder = ClapEncoder()
    
    processed_count = 0
    error_count = 0
    total_duration = 0
    
    # 4. Process in batches
    with open(output_file, 'a') as out_f:
        batch = []
        
        for i, item in enumerate(files_to_process):
            f_path = item['path']
            rel_path = item['rel_path']
            
            # Load audio
            audio, success, skip_reason = load_audio_for_clap(f_path, rel_path)
            
            if success:
                batch.append((rel_path, audio))
            else:
                error_count += 1
                print(f"  ⚠️  Skipped: {rel_path}")
                print(f"      Reason: {skip_reason}")
            
            # Process batch when full or at end
            if len(batch) >= BATCH_SIZE or (i == len(files_to_process) - 1 and batch):
                start_time = time.time()
                
                print(f"[{processed_count + 1}-{processed_count + len(batch)}/{len(files_to_process)}] Processing batch of {len(batch)}...")
                
                try:
                    results = encoder.get_embeddings_batch(batch)
                    
                    for rel_path, embedding in results:
                        track_data = {
                            "relative_path": rel_path,
                            "v_clap": embedding
                        }
                        out_f.write(json.dumps(track_data) + "\n")
                    
                    out_f.flush()
                    processed_count += len(results)
                    
                    duration = time.time() - start_time
                    total_duration += duration
                    avg_time = total_duration / (processed_count / BATCH_SIZE) if processed_count > 0 else 0
                    
                    remaining_batches = (len(files_to_process) - i - 1) // BATCH_SIZE
                    remaining_time = avg_time * remaining_batches
                    
                    print(f"  > Batch done in {duration:.2f}s. Avg: {avg_time:.2f}s/batch. Est. Remaining: {remaining_time/60:.1f}m")
                    
                except Exception as e:
                    print(f"  Error processing batch: {e}")
                    error_count += len(batch)
                
                batch = []
    
    print(f"\n{'='*50}")
    print(f"✅ CLAP embedding generation complete!")
    print(f"   Processed: {processed_count} files")
    print(f"   Errors: {error_count} files")
    print(f"   Output: {output_file}")


if __name__ == "__main__":
    target = DEFAULT_FILE_LIST
    limit = None
    
    if len(sys.argv) > 1:
        target = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
        except ValueError:
            pass
    
    generate_clap_embeddings(target, limit=limit)
