"""
Build-time script: Export CLAP text encoder to ONNX format.

Loads the full ClapModel, wraps text_model + text_projection into a single
Module, and exports to ONNX with dynamic batch/sequence axes.

Usage (run during Docker build):
    python export_clap_text.py [--output-dir /app/clap_text_onnx]
"""

import argparse
import os

import torch
import torch.nn as nn
from transformers import ClapModel, AutoTokenizer


class ClapTextEncoder(nn.Module):
    """Wraps text_model + text_projection to replicate get_text_features()."""

    def __init__(self, clap_model: ClapModel):
        super().__init__()
        self.text_model = clap_model.text_model
        self.text_projection = clap_model.text_projection

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        text_outputs = self.text_model(input_ids=input_ids, attention_mask=attention_mask)
        pooled = text_outputs[1]  # pooler_output
        projected = self.text_projection(pooled)
        # L2 normalize (same as ClapModel.get_text_features)
        projected = projected / projected.norm(dim=-1, keepdim=True)
        return projected


def export(output_dir: str, model_name: str = "laion/clap-htsat-unfused"):
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading full CLAP model: {model_name}")
    full_model = ClapModel.from_pretrained(model_name)
    full_model.eval()

    encoder = ClapTextEncoder(full_model)
    encoder.eval()

    # Save tokenizer (RobertaTokenizerFast) for runtime use
    print("Saving tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.save_pretrained(output_dir)

    # Create dummy inputs
    dummy_input_ids = torch.zeros(1, 16, dtype=torch.long)
    dummy_attention_mask = torch.ones(1, 16, dtype=torch.long)

    onnx_path = os.path.join(output_dir, "clap_text.onnx")
    print(f"Exporting ONNX to {onnx_path}...")

    torch.onnx.export(
        encoder,
        (dummy_input_ids, dummy_attention_mask),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["text_features"],
        dynamic_axes={
            "input_ids": {0: "batch_size", 1: "sequence_length"},
            "attention_mask": {0: "batch_size", 1: "sequence_length"},
            "text_features": {0: "batch_size"},
        },
        opset_version=17,
        do_constant_folding=True,
    )

    # Quick sanity check: file size should be ~30-50MB (text encoder only)
    size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
    print(f"ONNX model exported: {size_mb:.1f} MB")

    # Verify with onnxruntime
    import onnxruntime as ort
    import numpy as np

    session = ort.InferenceSession(onnx_path)
    ort_out = session.run(
        None,
        {
            "input_ids": dummy_input_ids.numpy(),
            "attention_mask": dummy_attention_mask.numpy(),
        },
    )

    with torch.no_grad():
        pt_out = encoder(dummy_input_ids, dummy_attention_mask).numpy()

    diff = np.abs(pt_out - ort_out[0]).max()
    print(f"Max abs diff (PyTorch vs ONNX): {diff:.6e}")
    assert diff < 1e-4, f"ONNX output diverges from PyTorch: max diff {diff}"
    print("Export verified successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="/app/clap_text_onnx")
    parser.add_argument("--model-name", default="laion/clap-htsat-unfused")
    args = parser.parse_args()
    export(args.output_dir, args.model_name)
