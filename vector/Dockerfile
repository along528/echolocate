# === Stage 1: Export CLAP text encoder to ONNX ===
FROM python:3.11-slim AS exporter

WORKDIR /app

# Install build-time dependencies (torch + transformers + onnx)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Export text encoder to ONNX
COPY export_clap_text.py .
RUN python export_clap_text.py --output-dir /app/clap_text_onnx

# === Stage 2: Lightweight runtime (no torch) ===
FROM python:3.11-slim

WORKDIR /app

# Install runtime-only dependencies
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

# Copy ONNX model + tokenizer from exporter stage
COPY --from=exporter /app/clap_text_onnx /app/clap_text_onnx

# Default to creating a writable directory for DuckDB extensions
# Cloud Run filesystem is read-only except for /tmp (memory) or mounts.
ENV HOME=/tmp

# Copy app code
COPY main.py .

# Expected mount point for the DB
ENV DB_PATH=/data/cloudcrate.duckdb

# Expose port
ENV PORT=8080
EXPOSE 8080

# Run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
