FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# wget/curl needed if we were downloading extensions manually, but duckdb client handles it
RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Default to creating a writable directory for DuckDB extensions
# Cloud Run filesystem is read-only except for /tmp (memory) or mounts.
# DuckDB tries to install extensions to ~/.duckdb/
# We set HOME to /tmp so it can "install" them there if needed, 
# though ideally we bake them in. 
# 0.10.0 might bundle some, but vss is usually separate.
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
