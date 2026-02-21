FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set cache directory for model downloads
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

# Pre-download CLAP model during build (avoids HuggingFace rate limits at runtime)
RUN python -c "from transformers import AutoProcessor, ClapModel; \
    ClapModel.from_pretrained('laion/clap-htsat-unfused'); \
    AutoProcessor.from_pretrained('laion/clap-htsat-unfused')"

# --- Final stage ---
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages and cached model from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/.cache /app/.cache

# Set cache directory so transformers finds the pre-cached model
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

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

# Run commands
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
