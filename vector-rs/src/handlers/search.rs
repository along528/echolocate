use axum::extract::{Query, State};
use axum::Json;
use std::sync::Arc;

use crate::db;
use crate::error::AppError;
use crate::models::{SearchRequest, SearchResult, TextSearchQuery, TrackResponse};
use crate::AppState;

pub async fn search_tracks_text(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TextSearchQuery>,
) -> Result<Json<Vec<TrackResponse>>, AppError> {
    let db_path = state.db_path.clone();

    // Validate at least one search param
    if params.query.is_none() && params.artist.is_none() && params.album.is_none() && params.title.is_none() {
        return Err(AppError::BadRequest(
            "At least one search parameter required: query, artist, album, or title".into(),
        ));
    }

    let limit = params.limit.unwrap_or(20);
    let source = params.source.unwrap_or_else(|| "library".into());

    tokio::task::spawn_blocking(move || {
        let conn = db::get_connection(&db_path)?;

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
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url \
             FROM tracks WHERE {} LIMIT {}",
            where_clause, limit
        );

        // Remove the limit from param_values (we inlined it)
        param_values.pop();

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
            });
        }

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

    let db_path = state.db_path.clone();
    let limit = request.limit.unwrap_or(10);
    let source = request.source.unwrap_or_else(|| "library".into());
    let vector = request.vector;

    tokio::task::spawn_blocking(move || {
        let conn = db::get_connection(&db_path)?;

        let source_filter = if source == "all" {
            String::new()
        } else {
            format!("WHERE source = '{}'", source)
        };

        let vec_literal = vec_f32_to_sql_literal(&vector, 768);
        let query = format!(
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
                    array_cosine_similarity(v_mid, {}) as similarity \
             FROM tracks {} \
             ORDER BY similarity DESC \
             LIMIT ?",
            vec_literal, source_filter
        );

        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query(duckdb::params![limit])?;

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
