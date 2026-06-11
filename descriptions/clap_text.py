"""
Shared CLAP text encoder for the descriptions pipeline.

Used by generate_tags.py (vocabulary anchors) and evaluate_captions.py
(caption embeddings). Same model and normalization as the audio side
(embeddings/generate_clap.py), so similarities are computed in the space the
v_clap column lives in.
"""

import numpy as np

CLAP_MODEL_NAME = "laion/clap-htsat-unfused"


class ClapTextEncoder:
    """Lazy-loaded CLAP text encoder returning L2-normalized numpy embeddings."""

    def __init__(self, device=None):
        import torch
        from transformers import AutoProcessor, ClapModel

        self.device = torch.device(device or "cpu")
        print(f"Loading CLAP model: {CLAP_MODEL_NAME}...")
        self.model = ClapModel.from_pretrained(CLAP_MODEL_NAME).to(self.device)
        self.processor = AutoProcessor.from_pretrained(CLAP_MODEL_NAME)
        self.model.eval()
        print(f"CLAP model loaded on {self.device}.")

    def encode(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        """Encode texts to a (len(texts), 512) L2-normalized float32 matrix."""
        import torch

        chunks = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            inputs = self.processor(
                text=batch, return_tensors="pt", padding=True
            ).to(self.device)
            with torch.no_grad():
                feats = self.model.get_text_features(**inputs)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            chunks.append(feats.cpu().numpy().astype(np.float32))
        return np.vstack(chunks)
