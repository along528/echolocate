use axum::extract::{Path, Query, State};
use axum::Json;
use std::sync::Arc;

use crate::db::{self, value_to_vec_f32};
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
use crate::models::{SearchResult, SimilarQuery, TrackResponse, TracksQuery};
use crate::AppState;

pub async fn list_tracks(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TracksQuery>,
) -> Result<Json<Vec<TrackResponse>>, AppError> {
    let db_path = state.db_path.clone();
    let limit = params.limit.unwrap_or(50);
    let offset = params.offset.unwrap_or(0);
    let random = params.random.unwrap_or(true);
    let source = params.source.unwrap_or_else(|| "library".into());

    tokio::task::spawn_blocking(move || {
        let conn = db::get_connection(&db_path)?;

        let results = if random {
            if source == "all" {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url \
                     FROM tracks USING SAMPLE {} ROWS",
                    limit
                );
                query_track_rows(&conn, &query, &[])?
            } else {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url \
                     FROM (SELECT * FROM tracks WHERE source = ?) USING SAMPLE {} ROWS",
                    limit
                );
                query_track_rows(&conn, &query, &[&source])?
            }
        } else {
            if source == "all" {
                let query = "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url \
                             FROM tracks ORDER BY id LIMIT ? OFFSET ?";
                query_track_rows(&conn, query, &[&limit, &offset])?
            } else {
                let query = "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url \
                             FROM tracks WHERE source = ? ORDER BY id LIMIT ? OFFSET ?";
                query_track_rows(&conn, query, &[&source as &dyn duckdb::ToSql, &limit, &offset])?
            }
        };

        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

pub async fn find_similar(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
    Query(params): Query<SimilarQuery>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    find_by_similarity(state, track_id, params, "DESC").await
}

pub async fn find_dissimilar(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
    Query(params): Query<SimilarQuery>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    find_by_similarity(state, track_id, params, "ASC").await
}

async fn find_by_similarity(
    state: Arc<AppState>,
    track_id: String,
    params: SimilarQuery,
    order: &'static str,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    let db_path = state.db_path.clone();
    let limit = params.limit.unwrap_or(10);
    let source = params.source.unwrap_or_else(|| "library".into());

    tokio::task::spawn_blocking(move || {
        let conn = db::get_connection(&db_path)?;

        // 1. Get the vector for the target track
        let mut stmt = conn.prepare("SELECT v_mid FROM tracks WHERE id = ?")?;
        let mut rows = stmt.query([&track_id])?;

        let row = rows.next()?.ok_or_else(|| AppError::NotFound("Track not found".into()))?;
        let raw_vector: duckdb::types::Value = row.get(0)?;
        let target_vec = value_to_vec_f32(&raw_vector);
        let vec_literal = vec_f32_to_sql_literal(&target_vec, 768);

        // 2. Search for similar/dissimilar tracks
        let source_filter = if source == "all" {
            String::new()
        } else {
            format!("AND source = '{}'", source)
        };

        let query = format!(
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
                    array_cosine_similarity(v_mid, {}) as similarity \
             FROM tracks \
             WHERE id != ? {} \
             ORDER BY similarity {} \
             LIMIT ?",
            vec_literal, source_filter, order
        );

        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query(duckdb::params![track_id, limit])?;

        let mut results = Vec::new();
        while let Some(row) = rows.next()? {
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
                similarity: row.get(9)?,
            });
        }

        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

fn query_track_rows(
    conn: &duckdb::Connection,
    query: &str,
    params: &[&dyn duckdb::ToSql],
) -> Result<Vec<TrackResponse>, AppError> {
    let mut stmt = conn.prepare(query)?;
    let mut rows = stmt.query(params)?;
    let mut results = Vec::new();

    while let Some(row) = rows.next()? {
        results.push(TrackResponse {
            id: row.get(0)?,
            source: row.get(1)?,
            title: row.get(2)?,
            artist: row.get(3)?,
            album: row.get(4)?,
            relative_path: row.get(5)?,
            track_url: row.get(6)?,
            album_url: row.get(7)?,
            artist_url: row.get(8)?,
        });
    }

    Ok(results)
}
