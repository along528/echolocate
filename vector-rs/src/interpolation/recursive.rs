use std::collections::HashSet;

use crate::db::value_to_vec_f32;
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
use crate::interpolation::math::get_midpoint;
use crate::models::SearchResult;

pub fn recursive_interpolation(
    conn: &duckdb::Connection,
    vec_a: &[f32],
    vec_b: &[f32],
    exclude_ids: &mut HashSet<String>,
    exclude_artists: &mut HashSet<String>,
    depth_limit: usize,
    method: &str,
) -> Result<Vec<SearchResult>, AppError> {
    if depth_limit == 0 {
        return Ok(vec![]);
    }

    let midpoint = get_midpoint(vec_a, vec_b, method);

    // Find nearest neighbor to midpoint, fetch top 20 and filter in Rust
    let vec_literal = vec_f32_to_sql_literal(&midpoint, 768);
    let query = format!(
        "SELECT id, title, artist, album, relative_path, v_mid, \
         array_cosine_similarity(v_mid, {}) as similarity \
         FROM tracks ORDER BY similarity DESC LIMIT 20",
        vec_literal
    );

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    let mut best_match: Option<(SearchResult, Vec<f32>)> = None;

    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let artist: String = row.get(2)?;

        if !exclude_ids.contains(&id) && !exclude_artists.contains(&artist) {
            let v_raw: duckdb::types::Value = row.get(5)?;
            let match_vec = value_to_vec_f32(&v_raw);

            let result = SearchResult {
                id: id.clone(),
                source: None,
                title: row.get(1)?,
                artist: artist.clone(),
                album: row.get(3)?,
                relative_path: row.get(4)?,
                similarity: row.get(6)?,
                track_url: None,
                album_url: None,
                artist_url: None,
            };

            exclude_ids.insert(id);
            exclude_artists.insert(artist);
            best_match = Some((result, match_vec));
            break;
        }
    }

    match best_match {
        None => Ok(vec![]),
        Some((match_obj, match_vec)) => {
            // Recurse left (a -> match)
            let left = recursive_interpolation(
                conn,
                vec_a,
                &match_vec,
                exclude_ids,
                exclude_artists,
                depth_limit - 1,
                method,
            )?;

            // Recurse right (match -> b)
            let right = recursive_interpolation(
                conn,
                &match_vec,
                vec_b,
                exclude_ids,
                exclude_artists,
                depth_limit - 1,
                method,
            )?;

            let mut result = left;
            result.push(match_obj);
            result.extend(right);
            Ok(result)
        }
    }
}
