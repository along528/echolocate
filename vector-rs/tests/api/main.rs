//! Integration tests for the vector-rs HTTP API, run against the committed
//! 600-track synthetic sample index (testdata/sample_index.duckdb) through the
//! real Axum router via tower::ServiceExt::oneshot — no ports, no processes.
//!
//! The sample index has valid structure but RANDOM unit vectors, so tests
//! assert shapes and invariants (counts, sort order, dedup, artist
//! uniqueness), never semantic quality.
//!
//! Everything lives in one test binary so the 501MB CLAP ONNX model — used
//! only by the ONNX-gated tests, which skip when it's absent — is loaded at
//! most once per `cargo test` run.

mod common;
mod interpolate;
mod map;
mod misc;
mod regions;
mod search;
mod tracks;
mod vibes;
