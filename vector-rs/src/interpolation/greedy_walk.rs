use std::collections::HashSet;

use crate::error::AppError;
use crate::handlers::search::vec_f32_to_duckdb_list;
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
) -> Result<Vec<SearchResult>, AppError> {
    // Ensure start/end are in visited sets
    visited_ids.insert(start_id.to_string());
    visited_ids.insert(end_id.to_string());
    visited_artists.insert(start_artist.to_string());
    visited_artists.insert(end_artist.to_string());

    let source_filter = if source == "all" {
        String::new()
    } else {
        format!("AND source = '{}'", source)
    };

    let mut current_vec = start_vec.to_vec();
    let mut path = Vec::new();

    for _ in 0..limit {
        // Two-step query: find neighborhood (top 50 closest to current),
        // then rank by similarity to target, excluding visited IDs.
        let query = format!(
            "WITH neighborhood AS ( \
                SELECT id, title, artist, album, relative_path, v_mid, source, \
                       track_url, album_url, artist_url, \
                       array_cosine_similarity(v_mid, ?::FLOAT[768]) as sim_to_current \
                FROM tracks \
                WHERE 1=1 {} \
                ORDER BY sim_to_current DESC \
                LIMIT 50 \
            ) \
            SELECT id, title, artist, album, relative_path, v_mid, source, \
                   track_url, album_url, artist_url, \
                   array_cosine_similarity(v_mid, ?::FLOAT[768]) as sim_to_target \
            FROM neighborhood \
            WHERE id NOT IN (SELECT UNNEST(?)) \
            ORDER BY sim_to_target DESC",
            source_filter
        );

        let current_value = vec_f32_to_duckdb_list(&current_vec);
        let end_value = vec_f32_to_duckdb_list(end_vec);
        let visited_list: Vec<duckdb::types::Value> = visited_ids
            .iter()
            .map(|s| duckdb::types::Value::Text(s.clone()))
            .collect();
        let visited_value = duckdb::types::Value::List(visited_list);

        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query(duckdb::params![current_value, end_value, visited_value])?;

        let mut best_next: Option<(SearchResult, Vec<f32>, f64)> = None;

        while let Some(row) = rows.next()? {
            let artist: String = row.get(2)?;

            // Check artist uniqueness
            if visited_artists.contains(&artist) {
                continue;
            }

            let v_raw: duckdb::types::Value = row.get(5)?;
            let v_mid = crate::db::value_to_vec_f32(&v_raw);
            let sim_to_target: f64 = row.get(10)?;

            let result = SearchResult {
                id: row.get(0)?,
                title: row.get(1)?,
                artist: artist.clone(),
                album: row.get(3)?,
                relative_path: row.get(4)?,
                source: row.get(6)?,
                track_url: row.get(7)?,
                album_url: row.get(8)?,
                artist_url: row.get(9)?,
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

                // Early exit if very close to target
                if sim > 0.98 {
                    break;
                }
            }
            None => break, // Dead end
        }
    }

    Ok(path)
}
