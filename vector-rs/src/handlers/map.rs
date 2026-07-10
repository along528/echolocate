use axum::extract::{Query, State};
use axum::Json;
use std::collections::HashMap;
use std::sync::Arc;

use crate::db::value_to_vec_f32;
use crate::error::AppError;
use crate::handlers::tracks::{query_track_rows, TRACK_COLUMNS};
use crate::models::{
    MapBackdropQuery, MapNearestQuery, MapPoint, MapRegionsQuery, MapRegionsResponse,
    SearchResult, TrackResponse,
};
use crate::regions::{self, RegionPoint};
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

/// Fill in `x,y` (and `duration`) on results that were produced without them
/// (e.g. the interpolation path), via a single lookup against the `tracks`
/// view. Results whose id has no projection stay `None`.
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
    let sql = format!("SELECT id, x, y, duration FROM tracks WHERE id IN ({placeholders})");

    let mut stmt = conn.prepare(&sql)?;
    let params: Vec<&dyn duckdb::ToSql> = ids.iter().map(|s| s as &dyn duckdb::ToSql).collect();
    let mut rows = stmt.query(params.as_slice())?;

    type Meta = (Option<f64>, Option<f64>, Option<f64>);
    let mut coords: HashMap<String, Meta> = HashMap::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        coords.insert(id, (row.get(1)?, row.get(2)?, row.get(3)?));
    }

    for r in results.iter_mut() {
        if let Some((x, y, duration)) = coords.get(&r.id) {
            r.x = *x;
            r.y = *y;
            r.duration = *duration;
        }
    }

    Ok(())
}

/// GET /map/regions?source=fma&k=6&n=1500
///
/// "Constellations": named neighborhoods of the sonar map. K-means clusters a
/// sample of the projected corpus and labels each cluster with its
/// best-matching vibe-anchor term (see `regions.rs`). Results are cached per
/// (source, k, n) for the process lifetime so every client sees the same
/// place names. Mirrors the vibes contract while anchors warm up:
/// `ready:false` with no regions, never an error.
pub async fn map_regions(
    State(state): State<Arc<AppState>>,
    Query(params): Query<MapRegionsQuery>,
) -> Result<Json<MapRegionsResponse>, AppError> {
    let source = params.source.unwrap_or_else(|| "fma".into());
    let k = params.k.unwrap_or(regions::DEFAULT_K).clamp(2, regions::MAX_K);
    let n = params.n.unwrap_or(regions::DEFAULT_SAMPLE).clamp(100, regions::MAX_SAMPLE);

    if state.vibes.get().is_none() {
        return Ok(Json(MapRegionsResponse {
            ready: false,
            source,
            k,
            regions: Vec::new(),
        }));
    }

    let cache_key = (source.clone(), k, n);
    if let Some(cached) = state.regions_cache.lock().unwrap().get(&cache_key) {
        return Ok(Json(cached.clone()));
    }

    let pool = state.db_pool.clone();
    let vibes_lock = state.vibes.clone();
    let regions_cache = state.regions_cache.clone();

    tokio::task::spawn_blocking(move || {
        let anchors = vibes_lock.get().expect("checked above; OnceLock never unsets");
        let conn = pool.get()?;

        // Sample coordinate-bearing rows with their CLAP embedding. Same
        // subquery-wrapped USING SAMPLE pattern as /map/backdrop.
        let (sql, has_source) = if source == "all" {
            (
                format!(
                    "SELECT x, y, v_clap FROM \
                     (SELECT x, y, v_clap FROM tracks WHERE x IS NOT NULL AND y IS NOT NULL) \
                     USING SAMPLE {n} ROWS"
                ),
                false,
            )
        } else {
            (
                format!(
                    "SELECT x, y, v_clap FROM \
                     (SELECT x, y, v_clap FROM tracks WHERE source = ? AND x IS NOT NULL AND y IS NOT NULL) \
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
            let raw: duckdb::types::Value = row.get(2)?;
            points.push(RegionPoint {
                x: row.get(0)?,
                y: row.get(1)?,
                v_clap: value_to_vec_f32(&raw),
            });
        }
        drop(rows);
        drop(stmt);
        pool.put(conn);

        let start = std::time::Instant::now();
        let clusters = regions::cluster(&points, k);
        let named = regions::label_clusters(anchors, &clusters);
        tracing::info!(
            "Map regions computed: {} regions from {} points (source={source}, k={k}) in {:.2?}",
            named.len(),
            points.len(),
            start.elapsed()
        );

        let response = MapRegionsResponse {
            ready: true,
            source,
            k,
            regions: named,
        };
        regions_cache
            .lock()
            .unwrap()
            .insert(cache_key, response.clone());
        Ok(Json(response))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

/// GET /map/nearest?x=&y=&source=fma
///
/// Returns the single globally-nearest track to a clicked map coordinate
/// (Euclidean distance in the normalized [0,1] projection space). This is the
/// exact "click-to-probe across the whole corpus" lookup — unlike the client's
/// approximate nearest-among-loaded-points fallback. 404 if no projected track
/// exists for the requested source.
pub async fn nearest(
    State(state): State<Arc<AppState>>,
    Query(params): Query<MapNearestQuery>,
) -> Result<Json<TrackResponse>, AppError> {
    let pool = state.db_pool.clone();
    let source = params.source.unwrap_or_else(|| "fma".into());
    let (x, y) = (params.x, params.y);

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;

        // Order by squared Euclidean distance to the clicked point; only consider
        // projected tracks. The subquery mirrors the source-filtering pattern used
        // by /map/backdrop and tracks::list_tracks.
        let order_by = "((x - ?) * (x - ?) + (y - ?) * (y - ?)) ASC";
        let (sql, has_source) = if source == "all" {
            (
                format!(
                    "SELECT {cols} FROM \
                     (SELECT * FROM tracks WHERE x IS NOT NULL AND y IS NOT NULL) \
                     ORDER BY {order_by} LIMIT 1",
                    cols = TRACK_COLUMNS, order_by = order_by
                ),
                false,
            )
        } else {
            (
                format!(
                    "SELECT {cols} FROM \
                     (SELECT * FROM tracks WHERE source = ? AND x IS NOT NULL AND y IS NOT NULL) \
                     ORDER BY {order_by} LIMIT 1",
                    cols = TRACK_COLUMNS, order_by = order_by
                ),
                true,
            )
        };

        // Param order matches the `?` placeholders: [source?], x, x, y, y.
        let mut params: Vec<&dyn duckdb::ToSql> = Vec::with_capacity(5);
        if has_source {
            params.push(&source);
        }
        params.push(&x);
        params.push(&x);
        params.push(&y);
        params.push(&y);

        let results = query_track_rows(&conn, &sql, &params)?;
        pool.put(conn);

        results
            .into_iter()
            .next()
            .map(Json)
            .ok_or_else(|| AppError::NotFound("No projected track found".into()))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}
