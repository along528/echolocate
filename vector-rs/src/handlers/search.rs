use axum::extract::{Query, State};
use axum::Json;
use std::sync::Arc;

use std::sync::atomic::Ordering;

use crate::db::{dist_expr, table_for_source};
use crate::error::AppError;
use crate::models::{SearchRequest, SearchResult, TextSearchQuery, TrackResponse};
use crate::AppState;

pub async fn search_tracks_text(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TextSearchQuery>,
) -> Result<Json<Vec<TrackResponse>>, AppError> {
    // Validate at least one search param
    if params.query.is_none() && params.artist.is_none() && params.album.is_none() && params.title.is_none() {
        return Err(AppError::BadRequest(
            "At least one search parameter required: query, artist, album, or title".into(),
        ));
    }

    let limit = params.limit.unwrap_or(20);
    let source = params.source.unwrap_or_else(|| "library".into());
    let pool = state.db_pool.clone();

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;

        let mut conditions: Vec<String> = Vec::new();
        let mut param_values: Vec<String> = Vec::new();

        if source != "all" {
            conditions.push("source = ?".into());
            param_values.push(source);
        }
        if let Some(ref q) = params.query {
            conditions.push("(title ILIKE ? OR artist ILIKE ? OR album ILIKE ?)".into());
            let term = format!("%{}%", q);
            param_values.push(term.clone());
            param_values.push(term.clone());
            param_values.push(term);
        }
        if let Some(ref a) = params.artist {
            conditions.push("artist ILIKE ?".into());
            param_values.push(format!("%{}%", a));
        }
        if let Some(ref a) = params.album {
            conditions.push("album ILIKE ?".into());
            param_values.push(format!("%{}%", a));
        }
        if let Some(ref t) = params.title {
            conditions.push("title ILIKE ?".into());
            param_values.push(format!("%{}%", t));
        }

        let where_clause = conditions.join(" AND ");

        let sql_with_limit = format!(
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
             FROM tracks WHERE {} LIMIT {}",
            where_clause, limit
        );

        let mut stmt = conn.prepare(&sql_with_limit)?;
        let param_refs: Vec<&dyn duckdb::ToSql> =
            param_values.iter().map(|s| s as &dyn duckdb::ToSql).collect();
        let mut rows = stmt.query(param_refs.as_slice())?;

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
                x: row.get(9)?,
                y: row.get(10)?,
                duration: row.get(11)?,
            });
        }

        drop(rows);
        drop(stmt);
        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

pub async fn vector_search(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SearchRequest>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    if request.vector.len() != 768 {
        return Err(AppError::BadRequest(format!(
            "Vector must be 768 dimensions, got {}",
            request.vector.len()
        )));
    }

    let pool = state.db_pool.clone();
    let limit = request.limit.unwrap_or(10);
    let source = request.source.unwrap_or_else(|| "library".into());
    let vector = request.vector;
    let use_hnsw = state.v_mid_warm.load(Ordering::Relaxed);

    tokio::task::spawn_blocking(move || {
        let query_start = std::time::Instant::now();
        let conn = pool.get()?;
        let vec_literal = vec_f32_to_sql_literal(&vector, 768);

        let results = if source == "all" {
            let mut combined = Vec::new();
            for table in &["tracks_library", "tracks_fma"] {
                let src = if *table == "tracks_library" { "library" } else { "fma" };
                let dist = dist_expr("v_mid", &vec_literal, use_hnsw);
                let q = format!(
                    "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                            {dist} as distance, x, y, duration \
                     FROM {table} \
                     ORDER BY distance ASC \
                     LIMIT {limit}",
                    dist = dist, table = table, limit = limit
                );
                let mut stmt = conn.prepare(&q)?;
                let mut rows = stmt.query([])?;
                while let Some(row) = rows.next()? {
                    let dist: f64 = row.get(8)?;
                    combined.push(SearchResult {
                        id: row.get(0)?,
                        source: Some(src.to_string()),
                        title: row.get(1)?,
                        artist: row.get(2)?,
                        album: row.get(3)?,
                        relative_path: row.get(4)?,
                        track_url: row.get(5)?,
                        album_url: row.get(6)?,
                        artist_url: row.get(7)?,
                        similarity: 1.0 - dist,
                        x: row.get(9)?,
                        y: row.get(10)?,
                        duration: row.get(11)?,
                    });
                }
            }
            combined.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal));
            combined.truncate(limit as usize);
            combined
        } else {
            let table = table_for_source(&source);
            let src_label = source.clone();
            let dist = dist_expr("v_mid", &vec_literal, use_hnsw);
            let q = format!(
                "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                        {dist} as distance, x, y, duration \
                 FROM {table} \
                 ORDER BY distance ASC \
                 LIMIT {limit}",
                dist = dist, table = table, limit = limit
            );
            let mut stmt = conn.prepare(&q)?;
            let mut rows = stmt.query([])?;
            let mut res = Vec::new();
            while let Some(row) = rows.next()? {
                let dist: f64 = row.get(8)?;
                res.push(SearchResult {
                    id: row.get(0)?,
                    source: Some(src_label.clone()),
                    title: row.get(1)?,
                    artist: row.get(2)?,
                    album: row.get(3)?,
                    relative_path: row.get(4)?,
                    track_url: row.get(5)?,
                    album_url: row.get(6)?,
                    artist_url: row.get(7)?,
                    similarity: 1.0 - dist,
                    x: row.get(9)?,
                    y: row.get(10)?,
                    duration: row.get(11)?,
                });
            }
            res
        };

        tracing::info!("vector_search completed in {:.2?} (hnsw={})", query_start.elapsed(), use_hnsw);
        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

/// Format a Vec<f32> as a DuckDB SQL literal: [0.1, 0.2, ...]::FLOAT[N]
/// Used because duckdb-rs doesn't support binding Value::List as a parameter.
pub fn vec_f32_to_sql_literal(v: &[f32], dim: usize) -> String {
    let inner: String = v.iter().map(|f| f.to_string()).collect::<Vec<_>>().join(",");
    format!("[{}]::FLOAT[{}]", inner, dim)
}

/// Format a Vec<String> as a DuckDB list literal for UNNEST: ['a','b',...]
pub fn vec_str_to_sql_literal(v: &[String]) -> String {
    let inner: String = v.iter().map(|s| format!("'{}'", s.replace('\'', "''"))).collect::<Vec<_>>().join(",");
    format!("[{}]", inner)
}
