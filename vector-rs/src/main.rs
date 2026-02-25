mod clap_onnx;
mod config;
mod db;
mod error;
mod gcs;
mod gemini;
mod handlers;
mod interpolation;
mod models;

use axum::routing::{get, post};
use axum::Router;
use std::sync::Arc;
use tower_http::cors::{AllowOrigin, CorsLayer};

use clap_onnx::ClapOnnxModel;
use config::Config;
use db::DbPool;
use gcs::GcsClient;
use gemini::GeminiClient;

pub struct AppState {
    pub config: Arc<Config>,
    pub db_path: String,
    pub db_pool: Arc<DbPool>,
    pub onnx: Arc<ClapOnnxModel>,
    pub gemini: Arc<Option<GeminiClient>>,
    pub gcs: Arc<Option<GcsClient>>,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let config = Config::from_env();
    tracing::info!("Starting cloud-crate-vector (Rust) on port {}", config.port);

    // Run all 4 initializations in parallel
    let pool_size = std::env::var("DB_POOL_SIZE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(4usize);

    let (db_result, onnx_result, gemini, gcs_result) = tokio::join!(
        // 1. DuckDB pool (blocking)
        tokio::task::spawn_blocking({
            let db_path = config.db_path.clone();
            move || DbPool::new(&db_path, pool_size)
        }),
        // 2. ONNX model (blocking)
        tokio::task::spawn_blocking({
            let onnx_dir = config.clap_onnx_dir.clone();
            move || ClapOnnxModel::load(&onnx_dir)
        }),
        // 3. Gemini (async, optional)
        async {
            if let Some(ref project_id) = config.gcp_project_id {
                match GeminiClient::new(project_id, &config.gcp_location).await {
                    Ok(client) => {
                        tracing::info!("Vertex AI Agent initialized: {project_id}");
                        Some(client)
                    }
                    Err(e) => {
                        tracing::warn!("Vertex AI failed to initialize: {e}");
                        None
                    }
                }
            } else {
                tracing::info!("GCP_PROJECT_ID not set. Enhanced search disabled.");
                None
            }
        },
        // 4. GCS (async)
        GcsClient::new(),
    );

    let db_pool = match db_result.expect("DuckDB init task panicked") {
        Ok(pool) => {
            tracing::info!("DuckDB connection pool initialized (size={pool_size}), database: {}", config.db_path);
            pool
        }
        Err(e) => panic!("Failed to initialize DuckDB connection pool: {e}"),
    };

    let onnx = match onnx_result.expect("ONNX init task panicked") {
        Ok(model) => {
            tracing::info!("CLAP ONNX model loaded at startup.");
            model
        }
        Err(e) => panic!("Cannot start without CLAP model: {e}"),
    };

    let gcs = match gcs_result {
        Ok(client) => {
            tracing::info!("GCS client initialized.");
            Some(client)
        }
        Err(e) => {
            tracing::warn!("GCS client not available: {e}. Audio streaming will be disabled.");
            None
        }
    };

    let port = config.port;
    let db_pool = Arc::new(db_pool);
    let onnx = Arc::new(onnx);

    // Warmup: pre-load HNSW indexes so the first real request is fast
    {
        let warmup_start = std::time::Instant::now();
        tracing::info!("Warming up HNSW indexes...");

        let onnx_ref = onnx.clone();
        let pool_ref = db_pool.clone();
        let warmup_result = tokio::task::spawn_blocking(move || -> Result<(), String> {
            let query_vector = onnx_ref
                .encode_text("warmup")
                .map_err(|e| format!("Warmup CLAP encode failed: {e}"))?;

            let vec_literal = handlers::search::vec_f32_to_sql_literal(&query_vector, 512);

            let conn = pool_ref.get().map_err(|e| format!("Warmup DB conn failed: {e}"))?;
            for table in &["tracks_library", "tracks_fma"] {
                let q = format!(
                    "SELECT id FROM {table} ORDER BY array_cosine_distance(v_clap, {vec}) LIMIT 1",
                    table = table,
                    vec = vec_literal,
                );
                let mut stmt = conn.prepare(&q)
                    .map_err(|e| format!("Warmup prepare on {table} failed: {e}"))?;
                let mut rows = stmt.query([])
                    .map_err(|e| format!("Warmup query on {table} failed: {e}"))?;
                // Consume at least one row to force HNSW index load
                let _ = rows.next();
            }
            pool_ref.put(conn);
            Ok(())
        })
        .await
        .map_err(|e| format!("Warmup task panicked: {e}"));

        match warmup_result {
            Ok(Ok(())) => tracing::info!("HNSW warmup complete in {:.2?}", warmup_start.elapsed()),
            Ok(Err(e)) => tracing::warn!("HNSW warmup failed: {e}"),
            Err(e) => tracing::warn!("HNSW warmup failed: {e}"),
        }
    }

    let state = Arc::new(AppState {
        db_path: config.db_path.clone(),
        db_pool,
        config: Arc::new(config.clone()),
        onnx,
        gemini: Arc::new(gemini),
        gcs: Arc::new(gcs),
    });

    // CORS
    let cors = build_cors_layer(&config);

    let app = Router::new()
        .route("/", get(handlers::health::health_check))
        .route("/tracks", get(handlers::tracks::list_tracks))
        .route("/tracks/{track_id}/similar", get(handlers::tracks::find_similar))
        .route("/tracks/{track_id}/dissimilar", get(handlers::tracks::find_dissimilar))
        .route("/search", get(handlers::search::search_tracks_text))
        .route("/vector-search", post(handlers::search::vector_search))
        .route("/semantic-search", post(handlers::semantic::semantic_search))
        .route("/interpolate", post(handlers::interpolate::interpolate_tracks))
        .route("/interpolate/playlist", post(handlers::playlist::interpolate_playlist))
        .route("/stream/{track_id}", get(handlers::stream::stream_audio))
        .layer(cors)
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
        .await
        .expect("Failed to bind");

    tracing::info!("Listening on 0.0.0.0:{port}");
    axum::serve(listener, app).await.expect("Server error");
}

fn build_cors_layer(config: &Config) -> CorsLayer {
    match &config.cors_allow_origins {
        Some(origins_str) => {
            let origins: Vec<&str> = origins_str.split(',').collect();
            if origins.contains(&"*") {
                tracing::info!("CORS Allowed Origins: [*]");
                CorsLayer::permissive()
            } else {
                let parsed: Vec<_> = origins
                    .iter()
                    .filter_map(|o| o.trim().parse().ok())
                    .collect();
                tracing::info!("CORS Allowed Origins: {:?}", origins);
                CorsLayer::new()
                    .allow_origin(AllowOrigin::list(parsed))
                    .allow_methods(tower_http::cors::Any)
                    .allow_headers(tower_http::cors::Any)
            }
        }
        None => {
            tracing::info!("CORS middleware not enabled (CORS_ALLOW_ORIGINS not set)");
            CorsLayer::new()
        }
    }
}
