# === Stage 1: Export CLAP text encoder to ONNX ===
FROM python:3.11-slim AS exporter

WORKDIR /app

# Copy Python export dependencies
COPY vector-rs/scripts/export_requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Export text encoder to ONNX
COPY vector-rs/scripts/export_clap_text.py .
RUN python export_clap_text.py --output-dir /app/clap_text_onnx

# === Stage 2: Build Rust binary ===
FROM rust:1.93-slim-bookworm AS builder

RUN apt-get update && apt-get install -y pkg-config libssl-dev cmake g++ curl unzip wget && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Download pre-built libduckdb (avoids compiling DuckDB C++ from source)
# TARGETARCH is only auto-populated by BuildKit; Cloud Build uses the legacy
# docker builder, where it expands to empty — fall back to the image's own
# Debian arch, which uses the same amd64/arm64 names.
ARG TARGETARCH
ENV DUCKDB_VERSION=1.2.2
RUN ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    case "$ARCH" in \
      amd64) DUCKDB_ARCH=amd64 ;; \
      arm64) DUCKDB_ARCH=aarch64 ;; \
      *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl -L "https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_VERSION}/libduckdb-linux-${DUCKDB_ARCH}.zip" -o /tmp/libduckdb.zip && \
    unzip /tmp/libduckdb.zip -d /tmp/libduckdb && \
    cp /tmp/libduckdb/libduckdb.so /usr/local/lib/ && \
    cp /tmp/libduckdb/duckdb.h /usr/local/include/ && \
    cp /tmp/libduckdb/duckdb.hpp /usr/local/include/ && \
    ldconfig && \
    rm -rf /tmp/libduckdb*
ENV DUCKDB_LIB_DIR=/usr/local/lib
ENV DUCKDB_INCLUDE_DIR=/usr/local/include

# Cache dependencies with cargo-chef
RUN cargo install cargo-chef --locked

# Step 1: Prepare recipe (dependency manifest)
COPY vector-rs/Cargo.toml vector-rs/Cargo.lock* ./
COPY vector-rs/src/ src/
RUN cargo chef prepare --recipe-path recipe.json

# Step 2: Cook dependencies (cached layer)
RUN cargo chef cook --release --recipe-path recipe.json

# Step 3: Build the actual binary
COPY vector-rs/ .
RUN cargo build --release

# Download ONNX Runtime shared library for the runtime stage
RUN ORT_VERSION="1.23.0" && \
    ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    case "$ARCH" in \
      amd64) ORT_ARCH=x64 ;; \
      arm64) ORT_ARCH=aarch64 ;; \
      *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
    esac && \
    apt-get update && apt-get install -y curl && \
    curl -L "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}.tgz" \
    | tar xz -C /tmp && \
    mkdir -p /app/ort_lib && \
    cp /tmp/onnxruntime-linux-${ORT_ARCH}-${ORT_VERSION}/lib/libonnxruntime.so* /app/ort_lib/

# Pre-install DuckDB VSS extension
RUN ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" && \
    case "$ARCH" in \
      amd64) CLI_ARCH=amd64 ;; \
      arm64) CLI_ARCH=aarch64 ;; \
      *) echo "unsupported arch: $ARCH" >&2; exit 1 ;; \
    esac && \
    apt-get install -y unzip wget && \
    wget -q "https://github.com/duckdb/duckdb/releases/download/v1.2.0/duckdb_cli-linux-${CLI_ARCH}.zip" -O /tmp/duckdb.zip && \
    unzip /tmp/duckdb.zip -d /tmp && \
    /tmp/duckdb -c "INSTALL vss;" && \
    mkdir -p /app/duckdb_extensions && \
    (cp -r /tmp/.duckdb/extensions/* /app/duckdb_extensions/ 2>/dev/null || \
     cp -r ${HOME}/.duckdb/extensions/* /app/duckdb_extensions/ 2>/dev/null || true)

# === Stage 3: Minimal runtime ===
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy ONNX model + tokenizer from exporter stage
COPY --from=exporter /app/clap_text_onnx /app/clap_text_onnx

# Copy ONNX Runtime shared library
COPY --from=builder /app/ort_lib/ /usr/local/lib/
RUN ldconfig

# Copy DuckDB extensions
COPY --from=builder /app/duckdb_extensions/ /tmp/.duckdb/extensions/

# Copy baked search index (~4GB, rarely changes — its own layer for caching).
# INDEX_SRC defaults to the full baked index (deploy.sh / run-local.sh). PR
# previews and dev images override it with the small committed sample:
#   --build-arg INDEX_SRC=vector-rs/testdata/sample_index.duckdb
ARG INDEX_SRC=data/index.duckdb
COPY ${INDEX_SRC} /app/index.duckdb

# Copy the Rust binary and libduckdb
COPY --from=builder /app/target/release/cloud-crate-vector /app/cloud-crate-vector
COPY --from=builder /usr/local/lib/libduckdb.so /usr/local/lib/libduckdb.so
RUN ldconfig

# Environment
ENV INDEX_DB_PATH=/app/index.duckdb
ENV CLAP_ONNX_DIR=/app/clap_text_onnx
ENV HOME=/tmp
ENV PORT=8080
ENV ORT_DYLIB_PATH=/usr/local/lib/libonnxruntime.so

EXPOSE 8080

CMD ["/app/cloud-crate-vector"]
