use axum::extract::{Query, State};
use axum::Json;
use std::collections::HashMap;
use std::sync::Arc;

use crate::error::AppError;
use crate::models::{MapBackdropQuery, MapPoint, SearchResult};
use crate::AppState;

/// Max backdrop sample size, to keep the SVG dot count sane on the client.
const MAX_BACKDROP: i64 = 2000;
const DEFAULT_BACKDROP: i64 = 400;

/// GET /map/backdrop?source=fma&n=400
///
/// Returns a random sample of `{id, x, y}` points for the dimmed context field
/// behind the bright result set on the sonar map. Only tracks that have a
/// precomputed 2D projection are returned.
pub async fn backdrop(
    State(state): State<Arc<AppState>>,
    Query(params): Query<MapBackdropQuery>,
) -> Result<Json<Vec<MapPoint>>, AppError> {
    let pool = state.db_pool.clone();
    let n = params.n.unwrap_or(DEFAULT_BACKDROP).clamp(1, MAX_BACKDROP);
    let source = params.source.unwrap_or_else(|| "fma".into());

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;

        // Sample from a coordinate-bearing subquery. Mirrors the subquery-wrapped
        // USING SAMPLE pattern in tracks::list_tracks.
        let (sql, has_source) = if source == "all" {
            (
                format!(
                    "SELECT id, x, y FROM \
                     (SELECT id, x, y FROM tracks WHERE x IS NOT NULL AND y IS NOT NULL) \
                     USING SAMPLE {n} ROWS"
                ),
                false,
            )
        } else {
            (
                format!(
                    "SELECT id, x, y FROM \
                     (SELECT id, x, y FROM tracks WHERE source = ? AND x IS NOT NULL AND y IS NOT NULL) \
                     USING SAMPLE {n} ROWS"
                ),
                true,
            )
        };

        let mut stmt = conn.prepare(&sql)?;
        let mut rows = if has_source {
            stmt.query([&source])?
        } else {
            stmt.query([])?
        };

        let mut points = Vec::new();
        while let Some(row) = rows.next()? {
            points.push(MapPoint {
                id: row.get(0)?,
                x: row.get(1)?,
                y: row.get(2)?,
            });
        }

        drop(rows);
        drop(stmt);
        pool.put(conn);
        Ok(Json(points))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

/// Fill in `x,y` on results that were produced without coordinates (e.g. the
/// interpolation path), via a single lookup against the `tracks` view. Results
/// whose id has no projection stay `None`.
pub fn backfill_coords(
    conn: &duckdb::Connection,
    results: &mut [SearchResult],
) -> Result<(), AppError> {
    if results.is_empty() {
        return Ok(());
    }

    let ids: Vec<&str> = results.iter().map(|r| r.id.as_str()).collect();
    let placeholders = std::iter::repeat("?")
        .take(ids.len())
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!("SELECT id, x, y FROM tracks WHERE id IN ({placeholders})");

    let mut stmt = conn.prepare(&sql)?;
    let params: Vec<&dyn duckdb::ToSql> = ids.iter().map(|s| s as &dyn duckdb::ToSql).collect();
    let mut rows = stmt.query(params.as_slice())?;

    let mut coords: HashMap<String, (Option<f64>, Option<f64>)> = HashMap::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        coords.insert(id, (row.get(1)?, row.get(2)?));
    }

    for r in results.iter_mut() {
        if let Some((x, y)) = coords.get(&r.id) {
            r.x = *x;
            r.y = *y;
        }
    }

    Ok(())
}
