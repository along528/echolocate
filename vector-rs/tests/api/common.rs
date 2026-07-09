//! Shared fixtures for the API integration tests.
//!
//! One `AppState` (and one DuckDB pool, size 2) is built per test process and
//! shared by every test; `build_router` is cheap, so each test gets a fresh
//! Router over the shared state. When parallel tests drain the pool,
//! `DbPool::get` opens overflow read-only connections — DuckDB allows many
//! concurrent readers, and the vss extension is already installed locally, so
//! the extra `INSTALL vss` per overflow connection never hits the network.

#![allow(dead_code)] // helpers are shared across sibling test modules

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use http_body_util::BodyExt;
use serde_json::Value;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, OnceLock};
use tower::ServiceExt;

use cloud_crate_vector::clap_onnx::ClapOnnxModel;
use cloud_crate_vector::config::Config;
use cloud_crate_vector::db::DbPool;
use cloud_crate_vector::{build_router, AppState};

pub fn sample_db_path() -> String {
    format!("{}/testdata/sample_index.duckdb", env!("CARGO_MANIFEST_DIR"))
}

pub fn clap_onnx_dir() -> String {
    format!("{}/clap_text_onnx", env!("CARGO_MANIFEST_DIR"))
}

pub fn test_config() -> Config {
    Config {
        db_path: sample_db_path(),
        index_db_path: Some(sample_db_path()),
        port: 0,
        gcp_project_id: None,
        gcp_location: "us-central1".into(),
        gemini_model: "gemini-2.5-flash".into(),
        clap_onnx_dir: clap_onnx_dir(),
        cors_allow_origins: None,
        gcs_bucket_name: "test-bucket".into(),
        gcs_audio_prefix: "fma/fma_full/fma_full".into(),
        labels_bucket: "test-bucket".into(),
        index_version: "test".into(),
        model_version: "test".into(),
        git_sha: "test".into(),
    }
}

fn base_state(onnx: Arc<Option<ClapOnnxModel>>) -> Arc<AppState> {
    let shared_pool = app_state_pool();
    Arc::new(AppState {
        config: Arc::new(test_config()),
        db_path: sample_db_path(),
        db_pool: shared_pool,
        onnx,
        gemini: Arc::new(None),
        gcs: Arc::new(None),
        // The sample index ships with HNSW indexes, so warm=true exercises
        // the production dist_expr path.
        v_mid_warm: Arc::new(AtomicBool::new(true)),
        v_clap_warm: Arc::new(AtomicBool::new(true)),
    })
}

fn app_state_pool() -> Arc<DbPool> {
    static POOL: OnceLock<Arc<DbPool>> = OnceLock::new();
    POOL.get_or_init(|| {
        let pool = DbPool::new(&sample_db_path(), 2).unwrap_or_else(|e| {
            panic!(
                "failed to open sample index at {} — run tests from a dev-env shell \
                 (source scripts/dev-env.sh): {e}",
                sample_db_path()
            )
        });
        Arc::new(pool)
    })
    .clone()
}

/// The default test state: no CLAP model, no GCS/Gemini.
pub fn app_state() -> Arc<AppState> {
    static STATE: OnceLock<Arc<AppState>> = OnceLock::new();
    STATE.get_or_init(|| base_state(Arc::new(None))).clone()
}

pub fn app() -> Router {
    build_router(app_state())
}

/// State with the real CLAP ONNX model, or None (test should print a skip
/// notice and return). Loads the model at most once per process; self-heals
/// ORT_DYLIB_PATH when the sandbox dylib exists but the var isn't set (ort's
/// load-dynamic feature reads it lazily at first Session::builder()).
pub fn onnx_state() -> Option<Arc<AppState>> {
    static STATE: OnceLock<Option<Arc<AppState>>> = OnceLock::new();
    STATE
        .get_or_init(|| {
            let dir = clap_onnx_dir();
            let model = std::path::Path::new(&dir).join("clap_text.onnx");
            let tokenizer = std::path::Path::new(&dir).join("tokenizer.json");
            if !model.exists() || !tokenizer.exists() {
                return None;
            }
            if std::env::var("ORT_DYLIB_PATH").is_err() {
                let dylib = "/usr/local/lib/libonnxruntime.so";
                if std::path::Path::new(dylib).exists() {
                    std::env::set_var("ORT_DYLIB_PATH", dylib);
                } else {
                    return None;
                }
            }
            match ClapOnnxModel::load(&dir) {
                Ok(m) => Some(base_state(Arc::new(Some(m)))),
                Err(e) => {
                    eprintln!("SKIPPED: CLAP ONNX model failed to load: {e}");
                    None
                }
            }
        })
        .clone()
}

pub async fn get(app: Router, uri: &str) -> (StatusCode, Value) {
    let response = app
        .oneshot(Request::builder().uri(uri).body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    (status, body_json(response).await)
}

pub async fn post_json(app: Router, uri: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(uri)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    (status, body_json(response).await)
}

async fn body_json(response: axum::response::Response) -> Value {
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).unwrap_or(Value::Null)
    }
}

/// Deterministic track sample (sorted by id) from the fma table.
pub async fn sample_tracks(n: usize) -> Vec<Value> {
    let (status, body) = get(app(), &format!("/tracks?random=false&limit={n}&source=fma")).await;
    assert_eq!(status, StatusCode::OK);
    body.as_array().expect("tracks array").clone()
}

pub async fn sample_ids(n: usize) -> Vec<String> {
    sample_tracks(n)
        .await
        .iter()
        .map(|t| t["id"].as_str().unwrap().to_string())
        .collect()
}

/// Pick `n` tracks with pairwise-distinct artists (the sample index has only
/// ~10 artists, so playlist invariants need seeds that don't collide).
pub async fn distinct_artist_tracks(n: usize) -> Vec<Value> {
    let pool = sample_tracks(150).await;
    let mut seen = std::collections::HashSet::new();
    let picked: Vec<Value> = pool
        .into_iter()
        .filter(|t| seen.insert(t["artist"].as_str().unwrap().to_string()))
        .take(n)
        .collect();
    assert_eq!(picked.len(), n, "sample index has too few distinct artists");
    picked
}

pub fn ids_of(items: &[Value]) -> Vec<String> {
    items
        .iter()
        .map(|t| t["id"].as_str().unwrap().to_string())
        .collect()
}

/// Assert the numeric field is non-increasing across the result list.
pub fn assert_sorted_desc(items: &[Value], field: &str) {
    let vals: Vec<f64> = items.iter().map(|r| r[field].as_f64().unwrap()).collect();
    for pair in vals.windows(2) {
        assert!(
            pair[0] >= pair[1],
            "{field} not sorted descending: {vals:?}"
        );
    }
}
