use std::collections::HashSet;

use crate::db::{dist_expr, table_for_source};
use crate::error::AppError;
use crate::handlers::search::{vec_f32_to_sql_literal, vec_str_to_sql_literal};
use crate::models::SearchResult;

pub fn greedy_walk_interpolation(
    conn: &duckdb::Connection,
    start_vec: &[f32],
    end_vec: &[f32],
    start_id: &str,
    end_id: &str,
    start_artist: &str,
    end_artist: &str,
    limit: usize,
    source: &str,
    visited_ids: &mut HashSet<String>,
    visited_artists: &mut HashSet<String>,
    use_hnsw: bool,
) -> Result<Vec<SearchResult>, AppError> {
    // Ensure start/end are in visited sets
    visited_ids.insert(start_id.to_string());
    visited_ids.insert(end_id.to_string());
    visited_artists.insert(start_artist.to_string());
    visited_artists.insert(end_artist.to_string());

    let table = table_for_source(source);

    let end_literal = vec_f32_to_sql_literal(end_vec, 768);
    let mut current_vec = start_vec.to_vec();
    let mut path = Vec::new();

    for _ in 0..limit {
        let current_literal = vec_f32_to_sql_literal(&current_vec, 768);
        let visited_literal: Vec<String> = visited_ids.iter().cloned().collect();
        let visited_sql = vec_str_to_sql_literal(&visited_literal);

        // Use per-source table in the CTE for HNSW acceleration on the
        // neighborhood fetch, then re-rank by target similarity in Rust.
        let dist_current = dist_expr("v_mid", &current_literal, use_hnsw);
        let query = format!(
            "WITH neighborhood AS ( \
                SELECT id, title, artist, album, relative_path, v_mid, \
                       track_url, album_url, artist_url, \
                       {dist_current} as dist_to_current \
                FROM {table} \
                ORDER BY dist_to_current ASC \
                LIMIT 50 \
            ) \
            SELECT id, title, artist, album, relative_path, v_mid, \
                   track_url, album_url, artist_url, \
                   array_cosine_similarity(v_mid, {target}) as sim_to_target \
            FROM neighborhood \
            WHERE id NOT IN (SELECT UNNEST({visited})) \
            ORDER BY sim_to_target DESC",
            dist_current = dist_current,
            target = end_literal,
            table = table,
            visited = visited_sql,
        );

        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query([])?;

        let mut best_next: Option<(SearchResult, Vec<f32>, f64)> = None;

        while let Some(row) = rows.next()? {
            let artist: String = row.get(2)?;

            if visited_artists.contains(&artist) {
                continue;
            }

            let v_raw: duckdb::types::Value = row.get(5)?;
            let v_mid = crate::db::value_to_vec_f32(&v_raw);
            let sim_to_target: f64 = row.get(9)?;

            let src_label = match source {
                "library" => Some("library".to_string()),
                "fma" => Some("fma".to_string()),
                _ => None,
            };

            let result = SearchResult {
                id: row.get(0)?,
                title: row.get(1)?,
                artist: artist.clone(),
                album: row.get(3)?,
                relative_path: row.get(4)?,
                source: src_label,
                track_url: row.get(6)?,
                album_url: row.get(7)?,
                artist_url: row.get(8)?,
                similarity: sim_to_target,
            };

            best_next = Some((result, v_mid, sim_to_target));
            break;
        }

        match best_next {
            Some((result, next_vec, sim)) => {
                visited_ids.insert(result.id.clone());
                visited_artists.insert(result.artist.clone());
                path.push(result);
                current_vec = next_vec;

                if sim > 0.98 {
                    break;
                }
            }
            None => break,
        }
    }

    Ok(path)
}
