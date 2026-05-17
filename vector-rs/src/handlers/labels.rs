use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::AppState;

#[derive(Debug, Deserialize)]
pub struct SearchEvent {
    pub search_id: String,
    pub session_id: String,
    pub endpoint: String,
    pub query_kind: String,
    #[serde(default)]
    pub query: Value,
    #[serde(default)]
    pub params: Value,
    #[serde(default)]
    pub results: Vec<Value>,
}

#[derive(Debug, Deserialize)]
pub struct LabelEvent {
    pub label_id: String,
    pub search_id: String,
    pub session_id: String,
    pub track_id: String,
    pub rank: i64,
    pub signal: String,
    #[serde(default)]
    pub note: Option<String>,
}

const MAX_RESULTS: usize = 500;
const MAX_NOTE_LEN: usize = 500;
const MAX_ID_LEN: usize = 128;
const ALLOWED_SIGNALS: &[&str] = &["relevant", "borderline", "wrong", "cleared"];
const ALLOWED_KINDS: &[&str] = &["text", "seed", "pair", "random"];

/// Allowed only: ASCII alphanumerics, dash, underscore. Caps length.
/// Anything used as a GCS object-key segment must pass this.
fn is_safe_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= MAX_ID_LEN
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

pub async fn log_search(
    State(state): State<Arc<AppState>>,
    Json(event): Json<SearchEvent>,
) -> Result<StatusCode, (StatusCode, String)> {
    if !ALLOWED_KINDS.contains(&event.query_kind.as_str()) {
        return Err((StatusCode::BAD_REQUEST, "invalid query_kind".into()));
    }
    if !is_safe_id(&event.search_id) || !is_safe_id(&event.session_id) {
        return Err((StatusCode::BAD_REQUEST, "invalid id".into()));
    }
    if event.results.len() > MAX_RESULTS {
        return Err((StatusCode::BAD_REQUEST, "too many results".into()));
    }

    let now = Utc::now();
    let payload = json!({
        "search_id": event.search_id,
        "session_id": event.session_id,
        "timestamp": now.to_rfc3339(),
        "endpoint": event.endpoint,
        "query_kind": event.query_kind,
        "query": event.query,
        "params": event.params,
        "results": event.results,
        "versions": {
            "index": state.config.index_version,
            "model": state.config.model_version,
            "git_sha": state.config.git_sha,
        },
    });

    let date = now.format("%Y-%m-%d").to_string();
    let object = format!("labels/search_events/{}/{}.json", date, event.search_id);
    upload_async(state, object, payload);
    Ok(StatusCode::NO_CONTENT)
}

pub async fn log_label(
    State(state): State<Arc<AppState>>,
    Json(event): Json<LabelEvent>,
) -> Result<StatusCode, (StatusCode, String)> {
    if !ALLOWED_SIGNALS.contains(&event.signal.as_str()) {
        return Err((StatusCode::BAD_REQUEST, "invalid signal".into()));
    }
    if !is_safe_id(&event.label_id)
        || !is_safe_id(&event.search_id)
        || !is_safe_id(&event.session_id)
    {
        return Err((StatusCode::BAD_REQUEST, "invalid id".into()));
    }
    if event.track_id.is_empty() || event.track_id.len() > MAX_ID_LEN {
        return Err((StatusCode::BAD_REQUEST, "invalid track_id".into()));
    }
    let note = event.note.as_deref().map(|s| {
        if s.len() > MAX_NOTE_LEN {
            &s[..MAX_NOTE_LEN]
        } else {
            s
        }
    });

    let now = Utc::now();
    let payload = json!({
        "label_id": event.label_id,
        "search_id": event.search_id,
        "session_id": event.session_id,
        "timestamp": now.to_rfc3339(),
        "track_id": event.track_id,
        "rank": event.rank,
        "signal": event.signal,
        "note": note,
    });

    let date = now.format("%Y-%m-%d").to_string();
    let object = format!("labels/label_events/{}/{}.json", date, event.label_id);
    upload_async(state, object, payload);
    Ok(StatusCode::NO_CONTENT)
}

fn upload_async(state: Arc<AppState>, object: String, payload: Value) {
    let bytes = match serde_json::to_vec(&payload) {
        Ok(b) => b,
        Err(e) => {
            tracing::warn!("label serialization failed: {e}");
            return;
        }
    };
    let bucket = state.config.labels_bucket.clone();
    let gcs = state.gcs.clone();
    tokio::spawn(async move {
        let Some(gcs) = gcs.as_ref() else {
            tracing::warn!("GCS client unavailable; dropping label object {object}");
            return;
        };
        if let Err(e) = gcs
            .upload_object(&bucket, &object, bytes, "application/json")
            .await
        {
            tracing::warn!("label upload failed ({object}): {e}");
        }
    });
}
