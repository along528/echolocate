import librosa
import numpy as np
import torch
from transformers import Wav2Vec2FeatureExtractor, AutoModel
import json
import os
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

class MusicEncoder:
    def __init__(self, model_name="m-a-p/MERT-v1-95M", device=None):
        if device is None:
            if torch.backends.mps.is_available():
                self.device = torch.device("mps")
            elif torch.cuda.is_available():
                self.device = torch.device("cuda")
            else:
                self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)
            
        print(f"Loading model {model_name} on {self.device}...")
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(model_name, trust_remote_code=True).to(self.device)
        self.sampling_rate = self.processor.sampling_rate # Usually 24000 for MERT
        print(f"Model loaded. Sampling rate: {self.sampling_rate}")

    def get_embedding(self, audio_segment):
        """
        Generates a 768-dim embedding for a given audio segment (array).
        """
        # Prepare input
        inputs = self.processor(audio_segment, sampling_rate=self.sampling_rate, return_tensors="pt", padding=True)
        input_values = inputs.input_values.to(self.device)
        
        with torch.no_grad():
            outputs = self.model(input_values)
            # Take the mean of the last hidden state
            last_hidden_state = outputs.last_hidden_state # [batch, seq_len, hidden_size]
            embedding = last_hidden_state.mean(dim=1).squeeze().cpu().numpy()
            
        return embedding.tolist()

def load_and_segment(file_path, target_sr=24000):
    """
    Loads audio and extracts Intro, Mid, Outro (5s each).
    """
    try:
        # Load audio (mono)
        y, sr = librosa.load(file_path, sr=target_sr, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)
        
        if duration < 15:
            print(f"Skipping {file_path}: Duration too short ({duration:.2f}s)")
            return None
            
        # Define 5s window in samples
        window_samples = 5 * sr
        
        # 1. Intro: 0s to 5s
        intro_seg = y[:window_samples]
        
        # 2. Mid: Duration/2
        mid_start = int(len(y) / 2)
        mid_seg = y[mid_start : mid_start + window_samples]
        
        # 3. Outro: End - 5s
        outro_seg = y[-window_samples:]
        
        # Pad if necessary
        if len(intro_seg) < window_samples: intro_seg = librosa.util.fix_length(intro_seg, size=window_samples)
        if len(mid_seg) < window_samples: mid_seg = librosa.util.fix_length(mid_seg, size=window_samples)
        if len(outro_seg) < window_samples: outro_seg = librosa.util.fix_length(outro_seg, size=window_samples)
        
        return {
            "intro": intro_seg,
            "mid": mid_seg,
            "outro": outro_seg,
            "duration": duration
        }
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None
