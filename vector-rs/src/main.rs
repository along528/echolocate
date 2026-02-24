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
use gcs::GcsClient;
use gemini::GeminiClient;

pub struct AppState {
    pub config: Arc<Config>,
    pub db_path: String,
    pub onnx: Arc<ClapOnnxModel>,
    pub gemini: Arc<Option<GeminiClient>>,
    pub gcs: Arc<GcsClient>,
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

    // 1. Pre-install DuckDB VSS extension
    match db::get_connection(&config.db_path) {
        Ok(_) => tracing::info!("DuckDB VSS extension installed, database: {}", config.db_path),
        Err(e) => tracing::warn!("DuckDB VSS pre-install failed: {e}"),
    }

    // 2. Load CLAP ONNX model
    let onnx = match ClapOnnxModel::load(&config.clap_onnx_dir) {
        Ok(model) => {
            tracing::info!("CLAP ONNX model loaded at startup.");
            model
        }
        Err(e) => {
            tracing::warn!("CLAP ONNX model failed to load: {e}");
            // Create a dummy that will fail on use — matches Python's lazy-load fallback
            panic!("Cannot start without CLAP model: {e}");
        }
    };

    // 3. Initialize Gemini client (optional)
    let gemini = if let Some(ref project_id) = config.gcp_project_id {
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
    };

    // 4. Initialize GCS client
    let gcs = match GcsClient::new().await {
        Ok(client) => {
            tracing::info!("GCS client initialized.");
            client
        }
        Err(e) => {
            tracing::warn!("GCS client failed to initialize (streaming disabled): {e}");
            // We'll panic here since the service is somewhat broken without GCS
            // but in reality the Python service also just fails at request time
            panic!("Cannot start without GCS client: {e}");
        }
    };

    let port = config.port;
    let state = Arc::new(AppState {
        db_path: config.db_path.clone(),
        config: Arc::new(config.clone()),
        onnx: Arc::new(onnx),
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
                    .allow_credentials(true)
            }
        }
        None => {
            tracing::info!("CORS middleware not enabled (CORS_ALLOW_ORIGINS not set)");
            CorsLayer::new()
        }
    }
}
