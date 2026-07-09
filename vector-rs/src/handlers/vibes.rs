use axum::extract::{Path, Query, State};
use axum::Json;
use std::sync::Arc;

use crate::db::value_to_vec_f32;
use crate::error::AppError;
use crate::models::{TrackVibesQuery, TrackVibesResponse};
use crate::vibes::{self, DEFAULT_MIN_SCORE, DEFAULT_TOP_K};
use crate::AppState;

pub async fn get_track_vibes(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
    Query(params): Query<TrackVibesQuery>,
) -> Result<Json<TrackVibesResponse>, AppError> {
    // Anchors warm up in the background at startup; until then vibes are
    // simply "not ready" — 200 with an empty list, never a retryable error.
    if state.vibes.get().is_none() {
        return Ok(Json(TrackVibesResponse {
            track_id,
            ready: false,
            vibes: Vec::new(),
        }));
    }

    let pool = state.db_pool.clone();
    let vibes_lock = state.vibes.clone();
    let k = params.k.unwrap_or(DEFAULT_TOP_K);
    let min_score = params.min_score.unwrap_or(DEFAULT_MIN_SCORE);

    tokio::task::spawn_blocking(move || {
        let anchors = vibes_lock.get().expect("checked above; OnceLock never unsets");
        let conn = pool.get()?;

        let mut stmt = conn.prepare("SELECT v_clap FROM tracks WHERE id = ?")?;
        let mut rows = stmt.query([&track_id])?;
        let row = rows
            .next()?
            .ok_or_else(|| AppError::NotFound("Track not found".into()))?;
        let raw: duckdb::types::Value = row.get(0)?;
        let v_clap = value_to_vec_f32(&raw);

        drop(rows);
        drop(stmt);
        pool.put(conn);

        Ok(Json(TrackVibesResponse {
            track_id,
            ready: true,
            vibes: vibes::top_vibes(anchors, &v_clap, k, min_score),
        }))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}
