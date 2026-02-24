use axum::extract::State;
use axum::Json;
use std::sync::Arc;

use crate::db;
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_duckdb_list;
use crate::models::{SearchResult, SemanticSearchRequest, SemanticSearchResponse};
use crate::AppState;

pub async fn semantic_search(
    State(state): State<Arc<AppState>>,
    Json(request): Json<SemanticSearchRequest>,
) -> Result<Json<SemanticSearchResponse>, AppError> {
    let limit = request.limit.unwrap_or(10);
    let source = request.source.unwrap_or_else(|| "library".into());
    let enhance = request.enhance.unwrap_or(false);

    // 1. Agent layer (query expansion via Gemini)
    let mut final_search_text = request.query.clone();
    let mut enhanced_query_text: Option<String> = None;

    if enhance {
        if let Some(ref gemini) = *state.gemini {
            match gemini.enhance_query(&request.query).await {
                Ok(expanded) => {
                    tracing::info!("Agent: '{}' -> '{}'", request.query, expanded);
                    final_search_text = expanded.clone();
                    enhanced_query_text = Some(expanded);
                }
                Err(e) => {
                    tracing::warn!("Agent error: {e}");
                }
            }
        }
    }

    // 2. Vectorization layer (CLAP ONNX)
    let query_vector = state
        .onnx
        .encode_text(&final_search_text)
        .map_err(|e| AppError::Internal(format!("CLAP encoding failed: {e}")))?;

    // 3. Retrieval layer (DuckDB)
    let db_path = state.db_path.clone();

    let results = tokio::task::spawn_blocking(move || {
        let conn = db::get_connection(&db_path)?;

        let source_filter = if source == "all" {
            String::new()
        } else {
            format!("AND source = '{}'", source)
        };

        let query = format!(
            "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
                    array_cosine_similarity(v_clap, ?::FLOAT[512]) as similarity \
             FROM tracks \
             WHERE v_clap IS NOT NULL {} \
             ORDER BY similarity DESC \
             LIMIT ?",
            source_filter
        );

        let vec_value = vec_f32_to_duckdb_list(&query_vector);
        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query(duckdb::params![vec_value, limit])?;

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

        Ok::<_, AppError>(results)
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))??;

    Ok(Json(SemanticSearchResponse {
        results,
        original_query: request.query,
        enhanced_query: enhanced_query_text,
    }))
}
