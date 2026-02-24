use std::collections::HashSet;

use crate::error::AppError;
use crate::handlers::search::vec_f32_to_duckdb_list;
use crate::interpolation::math::de_casteljau_slerp;
use crate::models::SearchResult;

pub fn bezier_interpolation(
    conn: &duckdb::Connection,
    vec_start: &[f32],
    vec_controls: &[&[f32]],
    vec_end: &[f32],
    exclude_ids: &mut HashSet<String>,
    limit: usize,
) -> Result<Vec<SearchResult>, AppError> {
    let mut control_points: Vec<Vec<f32>> = vec![vec_start.to_vec()];
    for vc in vec_controls {
        control_points.push(vc.to_vec());
    }
    control_points.push(vec_end.to_vec());

    let steps = limit + 1;
    let mut path = Vec::new();

    for i in 1..steps {
        let t = i as f32 / steps as f32;

        let target_vector = de_casteljau_slerp(&control_points, t);

        // Find nearest real song to this theoretical point
        let query = "SELECT id, title, artist, album, relative_path, v_mid, \
                     array_cosine_similarity(v_mid, ?::FLOAT[768]) as similarity \
                     FROM tracks ORDER BY similarity DESC LIMIT 20";

        let vec_value = vec_f32_to_duckdb_list(&target_vector);
        let mut stmt = conn.prepare(query)?;
        let mut rows = stmt.query(duckdb::params![vec_value])?;

        while let Some(row) = rows.next()? {
            let id: String = row.get(0)?;
            if !exclude_ids.contains(&id) {
                let _v_raw: duckdb::types::Value = row.get(5)?;
                exclude_ids.insert(id.clone());
                path.push(SearchResult {
                    id,
                    source: None,
                    title: row.get(1)?,
                    artist: row.get(2)?,
                    album: row.get(3)?,
                    relative_path: row.get(4)?,
                    similarity: row.get(6)?,
                    track_url: None,
                    album_url: None,
                    artist_url: None,
                });
                break;
            }
        }
    }

    Ok(path)
}
