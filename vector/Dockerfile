FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set cache directory that persists across build and runtime
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

# Pre-download CLAP model during build (avoids HuggingFace rate limits at runtime)
RUN python -c "from transformers import AutoProcessor, ClapModel; \
    ClapModel.from_pretrained('laion/clap-htsat-unfused'); \
    AutoProcessor.from_pretrained('laion/clap-htsat-unfused')"

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
