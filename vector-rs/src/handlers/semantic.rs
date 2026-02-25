use axum::extract::State;
use axum::Json;
use std::sync::Arc;

use crate::db::table_for_source;
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
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

    // 2. ONNX encoding + DuckDB query in a single blocking task
    let onnx = state.onnx.clone();
    let pool = state.db_pool.clone();
    let search_text = final_search_text.clone();

    let results = tokio::task::spawn_blocking(move || {
        let query_vector = onnx
            .encode_text(&search_text)
            .map_err(|e| AppError::Internal(format!("CLAP encoding failed: {e}")))?;

        let conn = pool.get()?;
        let vec_literal = vec_f32_to_sql_literal(&query_vector, 512);

        let results = if source == "all" {
            // Query both tables with HNSW, merge results
            let mut combined = Vec::new();
            for table in &["tracks_library", "tracks_fma"] {
                let src = if *table == "tracks_library" { "library" } else { "fma" };
                let q = format!(
                    "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                            array_cosine_distance(v_clap, {vec}) as distance \
                     FROM {table} \
                     ORDER BY distance ASC \
                     LIMIT {limit}",
                    vec = vec_literal, table = table, limit = limit
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
                    });
                }
            }
            combined.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal));
            combined.truncate(limit as usize);
            combined
        } else {
            let table = table_for_source(&source);
            let src_label = source.clone();
            let q = format!(
                "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                        array_cosine_distance(v_clap, {vec}) as distance \
                 FROM {table} \
                 ORDER BY distance ASC \
                 LIMIT {limit}",
                vec = vec_literal, table = table, limit = limit
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
                });
            }
            res
        };

        pool.put(conn);
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
