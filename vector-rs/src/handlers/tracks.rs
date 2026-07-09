use axum::extract::{Path, Query, State};
use axum::Json;
use serde::Deserialize;
use std::sync::Arc;

use std::sync::atomic::Ordering;

use crate::db::{dist_expr, table_for_source, value_to_vec_f32};
use crate::error::AppError;
use crate::handlers::search::vec_f32_to_sql_literal;
use crate::models::{SearchResult, SimilarQuery, TrackResponse, TracksQuery};
use crate::AppState;

pub async fn list_tracks(
    State(state): State<Arc<AppState>>,
    Query(params): Query<TracksQuery>,
) -> Result<Json<Vec<TrackResponse>>, AppError> {
    let pool = state.db_pool.clone();
    let limit = params.limit.unwrap_or(50);
    let offset = params.offset.unwrap_or(0);
    let random = params.random.unwrap_or(true);
    let source = params.source.unwrap_or_else(|| "library".into());

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;

        let results = if random {
            if source == "all" {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                     FROM tracks USING SAMPLE {} ROWS",
                    limit
                );
                query_track_rows(&conn, &query, &[])?
            } else {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                     FROM (SELECT * FROM tracks WHERE source = ?) USING SAMPLE {} ROWS",
                    limit
                );
                query_track_rows(&conn, &query, &[&source])?
            }
        } else {
            if source == "all" {
                let query = "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                             FROM tracks ORDER BY id LIMIT ? OFFSET ?";
                query_track_rows(&conn, query, &[&limit, &offset])?
            } else {
                let query = "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                             FROM tracks WHERE source = ? ORDER BY id LIMIT ? OFFSET ?";
                query_track_rows(&conn, query, &[&source as &dyn duckdb::ToSql, &limit, &offset])?
            }
        };

        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

pub async fn find_similar(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
    Query(params): Query<SimilarQuery>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    find_by_similarity(state, track_id, params, "DESC").await
}

pub async fn find_dissimilar(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
    Query(params): Query<SimilarQuery>,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    find_by_similarity(state, track_id, params, "ASC").await
}

async fn find_by_similarity(
    state: Arc<AppState>,
    track_id: String,
    params: SimilarQuery,
    order: &'static str,
) -> Result<Json<Vec<SearchResult>>, AppError> {
    let pool = state.db_pool.clone();
    let limit = params.limit.unwrap_or(10);
    let source = params.source.unwrap_or_else(|| "library".into());
    let use_hnsw = state.v_mid_warm.load(Ordering::Relaxed);

    tokio::task::spawn_blocking(move || {
        let query_start = std::time::Instant::now();
        let conn = pool.get()?;

        // 1. Get the vector for the target track
        let mut stmt = conn.prepare("SELECT v_mid FROM tracks WHERE id = ?")?;
        let mut rows = stmt.query([&track_id])?;

        let row = rows.next()?.ok_or_else(|| AppError::NotFound("Track not found".into()))?;
        let raw_vector: duckdb::types::Value = row.get(0)?;
        let target_vec = value_to_vec_f32(&raw_vector);
        let vec_literal = vec_f32_to_sql_literal(&target_vec, 768);

        // 2. Search for similar/dissimilar tracks
        // "DESC" (similar) can use HNSW via distance ASC; "ASC" (dissimilar) stays brute-force
        let is_similar = order == "DESC";

        let results = if is_similar {
            // Use HNSW-compatible query: distance ASC, request extra to filter out self
            if source == "all" {
                let mut combined = Vec::new();
                for table in &["tracks_library", "tracks_fma"] {
                    let src = if *table == "tracks_library" { "library" } else { "fma" };
                    let dist = dist_expr("v_mid", &vec_literal, use_hnsw);
                    let q = format!(
                        "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                                {dist} as distance, x, y, duration \
                         FROM {table} \
                         ORDER BY distance ASC \
                         LIMIT {lim}",
                        dist = dist, table = table, lim = limit + 1
                    );
                    let mut stmt = conn.prepare(&q)?;
                    let mut rows = stmt.query([])?;
                    while let Some(row) = rows.next()? {
                        let id: String = row.get(0)?;
                        if id == track_id { continue; }
                        let dist: f64 = row.get(8)?;
                        combined.push(SearchResult {
                            id,
                            source: Some(src.to_string()),
                            title: row.get(1)?,
                            artist: row.get(2)?,
                            album: row.get(3)?,
                            relative_path: row.get(4)?,
                            track_url: row.get(5)?,
                            album_url: row.get(6)?,
                            artist_url: row.get(7)?,
                            similarity: 1.0 - dist,
                            x: row.get(9)?,
                            y: row.get(10)?,
                            duration: row.get(11)?,
                        });
                    }
                }
                combined.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap_or(std::cmp::Ordering::Equal));
                combined.truncate(limit as usize);
                combined
            } else {
                let table = table_for_source(&source);
                let src_label = source.clone();
                let dist = dist_expr("v_mid", &vec_literal, use_hnsw);
                let q = format!(
                    "SELECT id, title, artist, album, relative_path, track_url, album_url, artist_url, \
                            {dist} as distance, x, y, duration \
                     FROM {table} \
                     ORDER BY distance ASC \
                     LIMIT {lim}",
                    dist = dist, table = table, lim = limit + 1
                );
                let mut stmt = conn.prepare(&q)?;
                let mut rows = stmt.query([])?;
                let mut res = Vec::new();
                while let Some(row) = rows.next()? {
                    let id: String = row.get(0)?;
                    if id == track_id { continue; }
                    if res.len() >= limit as usize { break; }
                    let dist: f64 = row.get(8)?;
                    res.push(SearchResult {
                        id,
                        source: Some(src_label.clone()),
                        title: row.get(1)?,
                        artist: row.get(2)?,
                        album: row.get(3)?,
                        relative_path: row.get(4)?,
                        track_url: row.get(5)?,
                        album_url: row.get(6)?,
                        artist_url: row.get(7)?,
                        similarity: 1.0 - dist,
                        x: row.get(9)?,
                        y: row.get(10)?,
                        duration: row.get(11)?,
                    });
                }
                res
            }
        } else {
            // Dissimilar: brute-force on view (rare query, no HNSW needed)
            let mut res = Vec::new();
            if source == "all" {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
                            array_cosine_similarity(v_mid, {}) as similarity, x, y, duration \
                     FROM tracks \
                     WHERE id != ? \
                     ORDER BY similarity ASC \
                     LIMIT ?",
                    vec_literal
                );
                let mut stmt = conn.prepare(&query)?;
                let mut rows = stmt.query(duckdb::params![track_id, limit])?;
                while let Some(row) = rows.next()? {
                    res.push(SearchResult {
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
                        x: row.get(10)?,
                        y: row.get(11)?,
                        duration: row.get(12)?,
                    });
                }
            } else {
                let query = format!(
                    "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, \
                            array_cosine_similarity(v_mid, {}) as similarity, x, y, duration \
                     FROM tracks \
                     WHERE id != ? AND source = ? \
                     ORDER BY similarity ASC \
                     LIMIT ?",
                    vec_literal
                );
                let mut stmt = conn.prepare(&query)?;
                let mut rows = stmt.query(duckdb::params![track_id, source, limit])?;
                while let Some(row) = rows.next()? {
                    res.push(SearchResult {
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
                        x: row.get(10)?,
                        y: row.get(11)?,
                        duration: row.get(12)?,
                    });
                }
            }
            res
        };

        tracing::info!("find_by_similarity completed in {:.2?} (hnsw={})", query_start.elapsed(), use_hnsw);
        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

#[derive(Debug, Deserialize)]
pub struct TracksByIdsRequest {
    pub ids: Vec<String>,
    pub source: Option<String>,
    /// Attach live vibe chips to each track (no-op while anchors are warming).
    #[serde(default)]
    pub include_vibes: bool,
    /// Optional overrides for the attached vibes (defaults: k=3, min_score=0.25).
    /// A permissive min_score (e.g. -1) is how previews show chips against the
    /// synthetic sample index, whose random vectors score near 0.
    pub vibes_k: Option<usize>,
    pub vibes_min_score: Option<f32>,
}

const MAX_IDS_PER_CALL: usize = 500;

pub async fn tracks_by_ids(
    State(state): State<Arc<AppState>>,
    Json(body): Json<TracksByIdsRequest>,
) -> Result<Json<Vec<TrackResponse>>, AppError> {
    if body.ids.is_empty() {
        return Ok(Json(Vec::new()));
    }
    if body.ids.len() > MAX_IDS_PER_CALL {
        return Err(AppError::BadRequest(format!(
            "too many ids; max {MAX_IDS_PER_CALL}"
        )));
    }
    let pool = state.db_pool.clone();
    let vibes_lock = state.vibes.clone();
    let ids = body.ids;
    let source = body.source;
    let include_vibes = body.include_vibes;
    let vibes_k = body.vibes_k.unwrap_or(crate::vibes::DEFAULT_TOP_K);
    let vibes_min_score = body.vibes_min_score.unwrap_or(crate::vibes::DEFAULT_MIN_SCORE);

    tokio::task::spawn_blocking(move || {
        let conn = pool.get()?;
        let placeholders = std::iter::repeat("?")
            .take(ids.len())
            .collect::<Vec<_>>()
            .join(",");
        let query = match &source {
            Some(s) if s != "all" => format!(
                "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                 FROM tracks WHERE source = ? AND id IN ({placeholders})"
            ),
            _ => format!(
                "SELECT id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration \
                 FROM tracks WHERE id IN ({placeholders})"
            ),
        };
        let mut params: Vec<&dyn duckdb::ToSql> = Vec::with_capacity(ids.len() + 1);
        if let Some(s) = &source {
            if s != "all" {
                params.push(s as &dyn duckdb::ToSql);
            }
        }
        for id in &ids {
            params.push(id as &dyn duckdb::ToSql);
        }
        let mut results = query_track_rows(&conn, &query, &params)?;

        // Vibes are decoration: silently absent while anchors are still warming.
        if include_vibes {
            if let Some(anchors) = vibes_lock.get() {
                let vibe_query = format!("SELECT id, v_clap FROM tracks WHERE id IN ({placeholders})");
                let id_params: Vec<&dyn duckdb::ToSql> =
                    ids.iter().map(|id| id as &dyn duckdb::ToSql).collect();
                let mut stmt = conn.prepare(&vibe_query)?;
                let mut rows = stmt.query(id_params.as_slice())?;
                let mut clap_by_id: std::collections::HashMap<String, Vec<f32>> =
                    std::collections::HashMap::new();
                while let Some(row) = rows.next()? {
                    let id: String = row.get(0)?;
                    let raw: duckdb::types::Value = row.get(1)?;
                    clap_by_id.insert(id, crate::db::value_to_vec_f32(&raw));
                }
                for track in results.iter_mut() {
                    if let Some(v_clap) = clap_by_id.get(&track.id) {
                        track.vibes = Some(crate::vibes::top_vibes(
                            anchors,
                            v_clap,
                            vibes_k,
                            vibes_min_score,
                        ));
                    }
                }
            }
        }

        pool.put(conn);
        Ok(Json(results))
    })
    .await
    .map_err(|e| AppError::Internal(e.to_string()))?
}

/// Column list shared by every TrackResponse query. Must match the field order
/// read in `query_track_rows` below. `duration` is NULL until a DB rebuild
/// populates it.
pub(crate) const TRACK_COLUMNS: &str =
    "id, source, title, artist, album, relative_path, track_url, album_url, artist_url, x, y, duration";

pub(crate) fn query_track_rows(
    conn: &duckdb::Connection,
    query: &str,
    params: &[&dyn duckdb::ToSql],
) -> Result<Vec<TrackResponse>, AppError> {
    let mut stmt = conn.prepare(query)?;
    let mut rows = stmt.query(params)?;
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
            x: row.get(9)?,
            y: row.get(10)?,
            duration: row.get(11)?,
            vibes: None,
        });
    }

    Ok(results)
}
