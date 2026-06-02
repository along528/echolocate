use axum::extract::State;
use axum::Json;
use std::collections::HashSet;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use crate::db::value_to_vec_f32;
use crate::error::AppError;
use crate::interpolation::{bezier, greedy_walk, recursive};
use crate::models::{InterpolationPlaylistRequest, SearchResult};
use crate::AppState;

/// Full track row from DB (columns: id, v_mid, title, artist, album, relative_path, source, track_url, album_url, artist_url)
#[derive(Debug, Clone)]
pub struct TrackRow {
    pub id: String,
    pub v_mid: Vec<f32>,
    pub title: String,
    pub artist: String,
    pub album: String,
    pub relative_path: String,
    pub source: Option<String>,
    pub track_url: Option<String>,
    pub album_url: Option<String>,
    pub artist_url: Option<String>,
}

impl TrackRow {
    pub fn to_search_result(&self, similarity: f64) -> SearchResult {
        SearchResult {
            id: self.id.clone(),
            source: self.source.clone(),
            title: self.title.clone(),
            artist: self.artist.clone(),
            album: self.album.clone(),
            relative_path: self.relative_path.clone(),
            similarity,
            track_url: self.track_url.clone(),
            album_url: self.album_url.clone(),
            artist_url: self.artist_url.clone(),
            x: None,
            y: None,
        }
    }
}

pub fn read_track_row(row: &duckdb::Row<'_>) -> Result<TrackRow, duckdb::Error> {
    let v_raw: duckdb::types::Value = row.get(1)?;
    Ok(TrackRow {
        id: row.get(0)?,
        v_mid: value_to_vec_f32(&v_raw),
        title: row.get(2)?,
        artist: row.get(3)?,
        album: row.get(4)?,
        relative_path: row.get(5)?,
        source: row.get(6)?,
        track_url: row.get(7)?,
        album_url: row.get(8)?,
        artist_url: row.get(9)?,
    })
}

pub async fn interpolate_playlist(
    State(state): State<Arc<AppState>>,
    Json(request): Json<InterpolationPlaylistRequest>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    let pool = state.db_pool.clone();
    let limit = request.limit.unwrap_or(10) as usize;
    let method = request.method.unwrap_or_else(|| "greedy_walk".into());
    let source = request.source.unwrap_or_else(|| "all".into());
    let steer_ids = request.steer_track_ids.unwrap_or_default();
    if steer_ids.len() > 50 {
        return Err(AppError::BadRequest("Too many steering tracks (max 50)".into()));
    }

    let use_hnsw = state.v_mid_warm.load(Ordering::Relaxed);

    tokio::task::spawn_blocking(move || {
        let query_start = std::time::Instant::now();
        let conn = pool.get()?;

        // 1. Get start and end tracks
        let track_query = "SELECT id, v_mid, title, artist, album, relative_path, source, \
                           track_url, album_url, artist_url FROM tracks WHERE id IN (?, ?)";
        let mut stmt = conn.prepare(track_query)?;
        let mut rows = stmt.query([&request.track_id_1, &request.track_id_2])?;

        let mut track_map = std::collections::HashMap::new();
        while let Some(row) = rows.next()? {
            let tr = read_track_row(row)?;
            track_map.insert(tr.id.clone(), tr);
        }

        let start_row = track_map
            .get(&request.track_id_1)
            .ok_or_else(|| AppError::NotFound("Could not find both start and end tracks".into()))?
            .clone();
        let end_row = track_map
            .get(&request.track_id_2)
            .ok_or_else(|| AppError::NotFound("Could not find both start and end tracks".into()))?
            .clone();

        // 1.5 Fetch steering tracks if requested
        let mut steer_rows: Vec<TrackRow> = Vec::new();
        if !steer_ids.is_empty() {
            let placeholders: String = steer_ids.iter().map(|_| "?").collect::<Vec<_>>().join(", ");
            let steer_query = format!(
                "SELECT id, v_mid, title, artist, album, relative_path, source, \
                 track_url, album_url, artist_url FROM tracks WHERE id IN ({})",
                placeholders
            );
            let mut stmt = conn.prepare(&steer_query)?;
            let params: Vec<&dyn duckdb::ToSql> =
                steer_ids.iter().map(|s| s as &dyn duckdb::ToSql).collect();
            let mut rows = stmt.query(params.as_slice())?;

            let mut row_by_id = std::collections::HashMap::new();
            while let Some(row) = rows.next()? {
                let tr = read_track_row(row)?;
                row_by_id.insert(tr.id.clone(), tr);
            }

            for sid in &steer_ids {
                let tr = row_by_id.get(sid).ok_or_else(|| {
                    AppError::NotFound(format!("Steering track not found: {}", sid))
                })?;
                steer_rows.push(tr.clone());
            }
        }

        // 2. Generate path
        let path = if method == "greedy_walk" {
            generate_greedy_walk_path(
                &conn,
                &start_row,
                &end_row,
                &steer_rows,
                limit,
                &source,
                use_hnsw,
            )?
        } else {
            generate_geometric_path(
                &conn,
                &start_row,
                &end_row,
                &steer_rows,
                limit,
                &method,
            )?
        };

        // Wrap with start and end
        let start_obj = start_row.to_search_result(1.0);
        let end_obj = end_row.to_search_result(1.0);

        let mut full_playlist = vec![start_obj];
        full_playlist.extend(path);
        full_playlist.push(end_obj);

        // Backfill 2D map coordinates for every track in the playlist (the trail
        // polyline plots each node), in a single lookup.
        crate::handlers::map::backfill_coords(&conn, &mut full_playlist)?;

        tracing::info!("interpolate_playlist completed in {:.2?} (hnsw={})", query_start.elapsed(), use_hnsw);
        pool.put(conn);
        Ok(Json(full_playlist))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

fn generate_greedy_walk_path(
    conn: &duckdb::Connection,
    start_row: &TrackRow,
    end_row: &TrackRow,
    steer_rows: &[TrackRow],
    limit: usize,
    source: &str,
    use_hnsw: bool,
) -> Result<Vec<SearchResult>, AppError> {
    if !steer_rows.is_empty() {
        // Multi-segment walk: Start -> S1 -> S2 -> ... -> SN -> End
        let mut waypoints: Vec<&TrackRow> = vec![start_row];
        for sr in steer_rows {
            waypoints.push(sr);
        }
        waypoints.push(end_row);

        let num_segments = waypoints.len() - 1;
        let base_limit = std::cmp::max(1, limit / num_segments);
        let remainder = limit.saturating_sub(base_limit * num_segments);

        let mut visited_ids: HashSet<String> =
            HashSet::from_iter(vec![start_row.id.clone(), end_row.id.clone()]);
        let mut visited_artists: HashSet<String> =
            HashSet::from_iter(vec![start_row.artist.clone(), end_row.artist.clone()]);
        for sr in steer_rows {
            visited_ids.insert(sr.id.clone());
            visited_artists.insert(sr.artist.clone());
        }

        let mut path = Vec::new();
        for seg_idx in 0..num_segments {
            let seg_limit = base_limit + if seg_idx < remainder { 1 } else { 0 };
            let from = waypoints[seg_idx];
            let to = waypoints[seg_idx + 1];

            let seg_path = greedy_walk::greedy_walk_interpolation(
                conn,
                &from.v_mid,
                &to.v_mid,
                &from.id,
                &to.id,
                &from.artist,
                &to.artist,
                seg_limit,
                source,
                &mut visited_ids,
                &mut visited_artists,
                use_hnsw,
            )?;
            path.extend(seg_path);

            // Insert steering track between segments (not after last)
            if seg_idx < num_segments - 1 {
                path.push(steer_rows[seg_idx].to_search_result(1.0));
            }
        }

        Ok(path)
    } else {
        let walk_limit = std::cmp::max(1, limit.saturating_sub(2));
        let mut visited_ids: HashSet<String> =
            HashSet::from_iter(vec![start_row.id.clone(), end_row.id.clone()]);
        let mut visited_artists: HashSet<String> =
            HashSet::from_iter(vec![start_row.artist.clone(), end_row.artist.clone()]);

        greedy_walk::greedy_walk_interpolation(
            conn,
            &start_row.v_mid,
            &end_row.v_mid,
            &start_row.id,
            &end_row.id,
            &start_row.artist,
            &end_row.artist,
            walk_limit,
            source,
            &mut visited_ids,
            &mut visited_artists,
            use_hnsw,
        )
    }
}

fn generate_geometric_path(
    conn: &duckdb::Connection,
    start_row: &TrackRow,
    end_row: &TrackRow,
    steer_rows: &[TrackRow],
    limit: usize,
    method: &str,
) -> Result<Vec<SearchResult>, AppError> {
    let mut exclude_ids: HashSet<String> =
        HashSet::from_iter(vec![start_row.id.clone(), end_row.id.clone()]);

    let effective_limit = std::cmp::max(1, limit.saturating_sub(2));

    if !steer_rows.is_empty() {
        // Bezier curve interpolation
        for sr in steer_rows {
            exclude_ids.insert(sr.id.clone());
        }
        let vec_controls: Vec<&[f32]> = steer_rows.iter().map(|sr| sr.v_mid.as_slice()).collect();
        bezier::bezier_interpolation(
            conn,
            &start_row.v_mid,
            &vec_controls,
            &end_row.v_mid,
            &mut exclude_ids,
            effective_limit,
        )
    } else {
        // Standard recursive bisection
        let mut exclude_artists: HashSet<String> =
            HashSet::from_iter(vec![start_row.artist.clone(), end_row.artist.clone()]);

        let depth_limit = if limit >= 3 {
            ((limit as f64 - 1.0).log2() as usize).min(6)
        } else {
            0
        };

        recursive::recursive_interpolation(
            conn,
            &start_row.v_mid,
            &end_row.v_mid,
            &mut exclude_ids,
            &mut exclude_artists,
            depth_limit,
            method,
        )
    }
}
