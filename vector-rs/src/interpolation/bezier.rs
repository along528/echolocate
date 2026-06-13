use std::collections::HashSet;

use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
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
        let vec_literal = vec_f32_to_sql_literal(&target_vector, 768);
        let query = format!(
            "SELECT id, source, title, artist, album, relative_path, v_mid, \
             track_url, album_url, artist_url, \
             array_cosine_distance(v_mid, {}) as distance \
             FROM tracks ORDER BY distance ASC LIMIT 20",
            vec_literal
        );

        let mut stmt = conn.prepare(&query)?;
        let mut rows = stmt.query([])?;

        while let Some(row) = rows.next()? {
            let id: String = row.get(0)?;
            if !exclude_ids.contains(&id) {
                let _v_raw: duckdb::types::Value = row.get(6)?;
                let dist: f64 = row.get(10)?;
                exclude_ids.insert(id.clone());
                path.push(SearchResult {
                    id,
                    source: row.get(1)?,
                    title: row.get(2)?,
                    artist: row.get(3)?,
                    album: row.get(4)?,
                    relative_path: row.get(5)?,
                    track_url: row.get(7)?,
                    album_url: row.get(8)?,
                    artist_url: row.get(9)?,
                    similarity: 1.0 - dist,
                    x: None,
                    y: None,
                    duration: None,
                    vibes: None,
                });
                break;
            }
        }
    }

    Ok(path)
}
