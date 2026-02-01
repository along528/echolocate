"""
CLAP Canary Test Script
========================
Verifies that the laion/clap-htsat-unfused model correctly maps acoustic
features to abstract text queries. Run on a single known track to confirm
the "Shared Latent Space" is functional before batch processing.

Usage:
    python canary_test_clap.py path/to/test_track.wav
"""

import sys
import torch
import librosa
from transformers import AutoProcessor, ClapModel


def canary_test(audio_path: str):
    """
    Test CLAP model on a single audio file with abstract queries.
    """
    device = "cpu"  # Keep it on CPU for MBP stability during testing
    model_name = "laion/clap-htsat-unfused"
    
    print(f"Loading CLAP model: {model_name}...")
    model = ClapModel.from_pretrained(model_name).to(device)
    processor = AutoProcessor.from_pretrained(model_name)
    model.eval()
    
    print(f"Loading audio: {audio_path}")
    # CLAP requires 48kHz. Load 10s from the middle.
    audio, _ = librosa.load(audio_path, sr=48000, duration=10, offset=30)
    print(f"  Audio shape: {audio.shape}, duration: {len(audio)/48000:.2f}s")
    
    # Process audio
    inputs = processor(audios=audio, sampling_rate=48000, return_tensors="pt").to(device)
    
    with torch.no_grad():
        audio_vec = model.get_audio_features(**inputs)
        audio_vec /= audio_vec.norm(dim=-1, keepdim=True)
    
    print(f"  Audio embedding shape: {audio_vec.shape}")
    
    # Test Queries: The "Alien" Test
    queries = ["an alien singing", "jazz saxophone", "heavy techno", "ambient rain"]
    print(f"\nTesting queries: {queries}")
    
    text_inputs = processor(text=queries, padding=True, return_tensors="pt").to(device)
    
    with torch.no_grad():
        text_vecs = model.get_text_features(**text_inputs)
        text_vecs /= text_vecs.norm(dim=-1, keepdim=True)
    
    # Compute cosine similarity scores
    scores = (audio_vec @ text_vecs.T).squeeze(0)
    
    print("\n" + "=" * 50)
    print("CLAP Similarity Scores")
    print("=" * 50)
    for i, q in enumerate(queries):
        print(f"Query: {q:20} | Score: {scores[i].item():.4f}")
    print("=" * 50)
    
    # Basic sanity check
    print("\n✅ Canary test complete! Review scores above.")
    print("   Higher scores = better semantic match to the audio.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python canary_test_clap.py <audio_path>")
        print("Example: python canary_test_clap.py ../crate/music/test.wav")
        sys.exit(1)
    
    canary_test(sys.argv[1])
