pub mod clap_onnx;
pub mod config;
pub mod db;
pub mod error;
pub mod gcs;
pub mod gemini;
pub mod handlers;
pub mod interpolation;
pub mod models;
pub mod vibes;

use axum::extract::DefaultBodyLimit;
use axum::routing::{get, post};
use axum::Router;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, OnceLock};
use tower_http::cors::{AllowOrigin, CorsLayer};
use tower_http::trace::{DefaultOnResponse, TraceLayer};
use tracing::Level;

use clap_onnx::ClapOnnxModel;
use config::Config;
use db::DbPool;
use gcs::GcsClient;
use gemini::GeminiClient;

pub struct AppState {
    pub config: Arc<Config>,
    pub db_path: String,
    pub db_pool: Arc<DbPool>,
    /// None only when the CLAP model isn't loaded (tests / degraded envs);
    /// production startup still panics without it.
    pub onnx: Arc<Option<ClapOnnxModel>>,
    pub gemini: Arc<Option<GeminiClient>>,
    pub gcs: Arc<Option<GcsClient>>,
    pub v_mid_warm: Arc<AtomicBool>,
    pub v_clap_warm: Arc<AtomicBool>,
    /// Vibe anchor embeddings, set once by the background warmup task.
    /// Empty until warm (or forever, without the CLAP model).
    pub vibes: Arc<OnceLock<vibes::VibeAnchors>>,
}

pub fn build_router(state: Arc<AppState>) -> Router {
    let cors = build_cors_layer(&state.config);

    Router::new()
        .route("/", get(handlers::health::health_check))
        .route("/tracks", get(handlers::tracks::list_tracks))
        .route("/tracks/by-ids", post(handlers::tracks::tracks_by_ids).layer(DefaultBodyLimit::max(32 * 1024)))
        .route("/tracks/{track_id}/similar", get(handlers::tracks::find_similar))
        .route("/tracks/{track_id}/dissimilar", get(handlers::tracks::find_dissimilar))
        .route("/tracks/{track_id}/vibes", get(handlers::vibes::get_track_vibes))
        .route("/search", get(handlers::search::search_tracks_text))
        .route("/vector-search", post(handlers::search::vector_search))
        .route("/semantic-search", post(handlers::semantic::semantic_search))
        .route("/interpolate", post(handlers::interpolate::interpolate_tracks))
        .route("/interpolate/playlist", post(handlers::playlist::interpolate_playlist))
        .route("/map/backdrop", get(handlers::map::backdrop))
        .route("/map/nearest", get(handlers::map::nearest))
        .route("/stream/{track_id}", get(handlers::stream::stream_audio))
        .route("/version", get(handlers::version::get_version))
        .route(
            "/labels/search",
            post(handlers::labels::log_search).layer(DefaultBodyLimit::max(64 * 1024)),
        )
        .route(
            "/labels/result",
            post(handlers::labels::log_label).layer(DefaultBodyLimit::max(16 * 1024)),
        )
        .route("/labels/events", get(handlers::labels_read::list_events))
        .layer(cors)
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(|request: &axum::http::Request<_>| {
                    tracing::info_span!(
                        "request",
                        method = %request.method(),
                        uri = %request.uri(),
                    )
                })
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        )
        .with_state(state)
}

pub fn build_cors_layer(config: &Config) -> CorsLayer {
    match &config.cors_allow_origins {
        Some(origins_str) => {
            let origins: Vec<&str> = origins_str.split(',').collect();
            if origins.contains(&"*") {
                panic!("CORS_ALLOW_ORIGINS=* is not allowed in production; specify explicit origins");
            } else {
                let exact: Vec<String> =
                    origins.iter().map(|o| o.trim().to_string()).collect();
                tracing::info!("CORS Allowed Origins: {:?} (+ sonar PR previews)", exact);
                CorsLayer::new()
                    .allow_origin(AllowOrigin::predicate(move |origin, _parts| {
                        let Ok(origin) = origin.to_str() else {
                            return false;
                        };
                        // Exact match against the configured allowlist (prod domains).
                        if exact.iter().any(|o| o == origin) {
                            return true;
                        }
                        // Sonar PR-preview revisions get ephemeral Cloud Run tag URLs like
                        // https://pr123---cloud-crate-sonar-<hash>.<region>.run.app that can't
                        // be listed ahead of time. Scoped to the sonar service so this does
                        // NOT open CORS to arbitrary *.run.app apps.
                        origin.starts_with("https://")
                            && origin.ends_with(".run.app")
                            && origin.contains("---cloud-crate-sonar-")
                    }))
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
