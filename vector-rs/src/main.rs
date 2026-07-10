use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};

use cloud_crate_vector::clap_onnx::ClapOnnxModel;
use cloud_crate_vector::config::Config;
use cloud_crate_vector::db::DbPool;
use cloud_crate_vector::gcs::GcsClient;
use cloud_crate_vector::gemini::GeminiClient;
use cloud_crate_vector::{build_router, db, handlers, vibes, AppState};

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

    // Use baked index DB if available, otherwise fall back to DB_PATH (GCS mount)
    let effective_db_path = config
        .index_db_path
        .clone()
        .unwrap_or_else(|| config.db_path.clone());

    let v_mid_warm = Arc::new(AtomicBool::new(false));
    let v_clap_warm = Arc::new(AtomicBool::new(false));

    // Preload index file into OS page cache (sequential read is much faster
    // than DuckDB's random page access on Cloud Run's streamed container images)
    let preload_path = effective_db_path.clone();
    tokio::task::spawn_blocking(move || {
        let start = std::time::Instant::now();
        tracing::info!("Preloading index file into page cache: {preload_path}");
        match std::fs::read(&preload_path) {
            Ok(bytes) => {
                tracing::info!(
                    "Index preload complete: {:.1} MB in {:.2?}",
                    bytes.len() as f64 / 1_048_576.0,
                    start.elapsed()
                );
            }
            Err(e) => {
                tracing::warn!("Index preload failed (non-fatal): {e}");
            }
        }
    })
    .await
    .expect("Preload task panicked");

    // Fire HNSW warmup immediately — dedicated connections, no pool needed.
    // These run in parallel with all other init (pool, ONNX, Gemini, GCS).
    for (col, dim, flag) in [
        ("v_mid", 768usize, v_mid_warm.clone()),
        ("v_clap", 512usize, v_clap_warm.clone()),
    ] {
        let warmup_db_path = effective_db_path.clone();
        tokio::task::spawn(async move {
            let start = std::time::Instant::now();
            tracing::info!("Background warmup: {col} starting (dedicated connection)...");
            let result = tokio::task::spawn_blocking(move || -> Result<(), String> {
                let zero_vec = vec![0.0f32; dim];
                let vec_literal = handlers::search::vec_f32_to_sql_literal(&zero_vec, dim);
                let conn = db::get_connection(&warmup_db_path)
                    .map_err(|e| format!("Warmup DB conn failed: {e}"))?;
                let q = format!(
                    "SELECT id FROM tracks_fma ORDER BY array_cosine_distance({col}, {vec}) LIMIT 1",
                    col = col, vec = vec_literal,
                );
                let mut stmt = conn.prepare(&q).map_err(|e| format!("{col} warmup prepare: {e}"))?;
                let mut rows = stmt.query([]).map_err(|e| format!("{col} warmup query: {e}"))?;
                let _ = rows.next();
                Ok(())
            }).await.map_err(|e| format!("{col} warmup panicked: {e}"));
            match result {
                Ok(Ok(())) => {
                    flag.store(true, Ordering::Release);
                    tracing::info!("Background warmup: {col} complete in {:.2?}", start.elapsed());
                }
                Ok(Err(e)) => tracing::warn!("Background warmup: {col} failed: {e}"),
                Err(e) => tracing::warn!("Background warmup: {col} failed: {e}"),
            }
        });
    }

    // Init pool, ONNX, Gemini, GCS in parallel (warmup already running above)
    let (db_result, onnx_result, gemini, gcs_result) = tokio::join!(
        tokio::task::spawn_blocking({
            let db_path = effective_db_path.clone();
            move || DbPool::new(&db_path, pool_size)
        }),
        tokio::task::spawn_blocking({
            let onnx_dir = config.clap_onnx_dir.clone();
            move || ClapOnnxModel::load(&onnx_dir)
        }),
        async {
            if let Some(ref project_id) = config.gcp_project_id {
                match GeminiClient::new(project_id, &config.gcp_location, &config.gemini_model).await {
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
        GcsClient::new(),
    );

    let db_pool = match db_result.expect("DuckDB init task panicked") {
        Ok(pool) => {
            tracing::info!("DuckDB connection pool initialized (size={pool_size}), database: {effective_db_path}");
            pool
        }
        Err(e) => panic!("Failed to initialize DuckDB connection pool: {e}"),
    };
    let db_pool = Arc::new(db_pool);

    let onnx = match onnx_result.expect("ONNX init task panicked") {
        Ok(model) => {
            tracing::info!("CLAP ONNX model loaded at startup.");
            Arc::new(Some(model))
        }
        Err(e) => panic!("Cannot start without CLAP model: {e}"),
    };

    // Embed the vibe vocabulary in the background (mirrors the HNSW warmup:
    // never blocks serving; endpoints report ready:false until this lands).
    let vibe_anchors: Arc<OnceLock<vibes::VibeAnchors>> = Arc::new(OnceLock::new());
    {
        let (vibe_anchors, onnx) = (vibe_anchors.clone(), onnx.clone());
        tokio::task::spawn_blocking(move || {
            if let Some(model) = onnx.as_ref() {
                let start = std::time::Instant::now();
                match vibes::compute_anchors(model, &vibes::default_vocab()) {
                    Ok(anchors) => {
                        let n = anchors.vocab.len();
                        let _ = vibe_anchors.set(anchors);
                        tracing::info!("Vibe anchors ready: {n} terms in {:.2?}", start.elapsed());
                    }
                    Err(e) => tracing::warn!("Vibe anchor warmup failed: {e}"),
                }
            }
        });
    }

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

    let state = Arc::new(AppState {
        db_path: config.db_path.clone(),
        db_pool: db_pool.clone(),
        config: Arc::new(config.clone()),
        onnx,
        gemini: Arc::new(gemini),
        gcs: Arc::new(gcs),
        v_mid_warm: v_mid_warm.clone(),
        v_clap_warm: v_clap_warm.clone(),
        vibes: vibe_anchors,
        regions_cache: Arc::new(std::sync::Mutex::new(std::collections::HashMap::new())),
    });

    let app = build_router(state);

    let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
        .await
        .expect("Failed to bind");

    tracing::info!("Listening on 0.0.0.0:{port}");

    axum::serve(listener, app).await.expect("Server error");
}
