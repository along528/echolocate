use std::sync::Arc;

use axum::extract::State;
use axum::Json;
use serde_json::{json, Value};

use crate::AppState;

pub async fn get_version(State(state): State<Arc<AppState>>) -> Json<Value> {
    Json(json!({
        "index": state.config.index_version,
        "model": state.config.model_version,
        "git_sha": state.config.git_sha,
    }))
}
