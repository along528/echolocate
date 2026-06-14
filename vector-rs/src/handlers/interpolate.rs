use axum::extract::State;
use axum::Json;
use std::sync::Arc;

use crate::db::value_to_vec_f32;
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
use crate::interpolation::math::get_midpoint;
use crate::models::{InterpolationRequest, SearchResult};
use crate::AppState;

pub async fn interpolate_tracks(
    State(state): State<Arc<AppState>>,
    Json(request): Json<InterpolationRequest>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    let pool = state.db_pool.clone();
    let limit = request.limit.unwrap_or(10);
    let method = request.method.unwrap_or_else(|| "greedy_walk".into());
    // Constrain candidates to the requested source (e.g. "fma") so interpolation
    // doesn't surface tracks from other catalogs. "all" (or unset) = no filter.
    let source = request.source.unwrap_or_else(|| "all".into());

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;

        // 1. Get vectors for both tracks
        let mut stmt = conn.prepare("SELECT id, v_mid FROM tracks WHERE id IN (?, ?)")?;
        let mut rows = stmt.query([&request.track_id_1, &request.track_id_2])?;

        let mut track_vecs: Vec<(String, Vec<f32>)> = Vec::new();
        while let Some(row) = rows.next()? {
            let id: String = row.get(0)?;
            let v: duckdb::types::Value = row.get(1)?;
            track_vecs.push((id, value_to_vec_f32(&v)));
        }

        if track_vecs.len() != 2 {
            let found_ids: Vec<&str> = track_vecs.iter().map(|(id, _)| id.as_str()).collect();
            return Err(AppError::NotFound(format!(
                "Could not find both tracks. Found: {:?}",
                found_ids
            )));
        }

        let vec1 = &track_vecs[0].1;
        let vec2 = &track_vecs[1].1;

        // 2. Compute midpoint
        let midpoint = get_midpoint(vec1, vec2, &method);

        // 3. Search for nearest neighbors to the midpoint
        //    Use the view (HNSW won't kick in) but filter by source so candidates
        //    stay within the requested catalog. interpolate is low-frequency, so
        //    a brute-force scan is fine here.
        let vec_literal = vec_f32_to_sql_literal(&midpoint, 768);
        let source_filter = if source != "all" { " AND source = ?" } else { "" };
        let query = format!(
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
             array_cosine_distance(v_mid, {}) as distance \
             FROM tracks WHERE id NOT IN (?, ?){} \
             ORDER BY distance ASC LIMIT ?",
            vec_literal, source_filter
        );

        let mut stmt = conn.prepare(&query)?;
        let mut rows = if source != "all" {
            stmt.query(duckdb::params![
                request.track_id_1,
                request.track_id_2,
                source,
                limit
            ])?
        } else {
            stmt.query(duckdb::params![
                request.track_id_1,
                request.track_id_2,
                limit
            ])?
        };

        let mut results = Vec::new();
        while let Some(row) = rows.next()? {
            let dist: f64 = row.get(9)?;
            results.push(SearchResult {
                id: row.get(0)?,
                source: row.get(1)?,
                title: row.get(2)?,
                artist: row.get(3)?,
                album: row.get(4)?,
                relative_path: row.get(5)?,
                track_url: row.get(6)?,
                album_url: row.get(7)?,
                artist_url: row.get(8)?,
                similarity: 1.0 - dist,
                x: None,
                y: None,
                duration: None,
            });
        }

        drop(rows);
        drop(stmt);

        crate::handlers::map::backfill_coords(&conn, &mut results)?;

        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}
