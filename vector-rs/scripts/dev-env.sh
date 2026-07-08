# Source this to get the env vars vector-rs needs to build and run natively.
#   source vector-rs/scripts/dev-env.sh
#
# setup-dev.sh installs the native libs to /usr/local and wires ~/.bashrc to
# source this file, so interactive shells pick it up automatically.

# duckdb-sys (the `duckdb` crate) links against the system libduckdb; its
# build script reads these to find the prebuilt lib + headers.
export DUCKDB_LIB_DIR="${DUCKDB_LIB_DIR:-/usr/local/lib}"
export DUCKDB_INCLUDE_DIR="${DUCKDB_INCLUDE_DIR:-/usr/local/include}"

# Runtime lookup for libduckdb.so and libonnxruntime.so.
export LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH:-}"

# The `ort` crate uses the load-dynamic feature: it dlopen()s onnxruntime at
# runtime from this path (not linked at build time).
export ORT_DYLIB_PATH="${ORT_DYLIB_PATH:-/usr/local/lib/libonnxruntime.so}"

# Defaults for `cargo run` against the committed sample index. Override freely.
export INDEX_DB_PATH="${INDEX_DB_PATH:-testdata/sample_index.duckdb}"
export CLAP_ONNX_DIR="${CLAP_ONNX_DIR:-clap_text_onnx}"
export PORT="${PORT:-8000}"
