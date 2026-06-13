use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Clone)]
pub struct TrackResponse {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    pub title: String,
    pub artist: String,
    pub album: String,
    pub relative_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub track_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub album_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artist_url: Option<String>,
    /// 2D embedding-space coordinate (semantic-axis projection), normalized to [0,1].
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y: Option<f64>,
    /// Track length in seconds (NULL until a DB rebuild surfaces it).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<f64>,
    /// CLAP-classified "vibe" tags (NULL until generate_vibes.py runs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vibes: Option<Vec<String>>,
}

#[derive(Debug, Serialize, Clone)]
pub struct SearchResult {
    pub id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    pub title: String,
    pub artist: String,
    pub album: String,
    pub relative_path: String,
    pub similarity: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub track_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub album_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artist_url: Option<String>,
    /// 2D embedding-space coordinate (semantic-axis projection), normalized to [0,1].
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y: Option<f64>,
    /// Track length in seconds (NULL until a DB rebuild surfaces it).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<f64>,
    /// CLAP-classified "vibe" tags (NULL until generate_vibes.py runs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vibes: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
pub struct SearchRequest {
    pub vector: Vec<f32>,
    pub limit: Option<i64>,
    pub source: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct InterpolationRequest {
    pub track_id_1: String,
    pub track_id_2: String,
    pub limit: Option<i64>,
    pub method: Option<String>,
    pub source: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct InterpolationPlaylistRequest {
    pub track_id_1: String,
    pub track_id_2: String,
    pub limit: Option<i64>,
    pub method: Option<String>,
    pub steer_track_ids: Option<Vec<String>>,
    pub source: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SemanticSearchRequest {
    pub query: String,
    pub limit: Option<i64>,
    pub source: Option<String>,
    pub enhance: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct SemanticSearchResponse {
    pub results: Vec<SearchResult>,
    pub original_query: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enhanced_query: Option<String>,
}

/// Query parameters for GET /tracks
#[derive(Debug, Deserialize)]
pub struct TracksQuery {
    pub limit: Option<i64>,
    pub offset: Option<i64>,
    pub random: Option<bool>,
    pub source: Option<String>,
}

/// Query parameters for GET /search
#[derive(Debug, Deserialize)]
pub struct TextSearchQuery {
    pub query: Option<String>,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub title: Option<String>,
    pub limit: Option<i64>,
    pub source: Option<String>,
}

/// Query parameters for GET /tracks/{id}/similar and /dissimilar
#[derive(Debug, Deserialize)]
pub struct SimilarQuery {
    pub limit: Option<i64>,
    pub source: Option<String>,
}

/// Query parameters for GET /map/backdrop
#[derive(Debug, Deserialize)]
pub struct MapBackdropQuery {
    pub n: Option<i64>,
    pub source: Option<String>,
}

/// Query parameters for GET /map/nearest — the globally-nearest track to a
/// clicked map coordinate (both normalized to [0,1]).
#[derive(Debug, Deserialize)]
pub struct MapNearestQuery {
    pub x: f64,
    pub y: f64,
    pub source: Option<String>,
}

/// A minimal map dot: id + 2D coordinate. Used for the dimmed backdrop field.
#[derive(Debug, Serialize, Clone)]
pub struct MapPoint {
    pub id: String,
    pub x: f64,
    pub y: f64,
}
