use axum::extract::{Path, State};
use axum::http::header;
use axum::response::IntoResponse;
use std::sync::Arc;

use crate::error::AppError;
use crate::AppState;

pub async fn stream_audio(
    State(state): State<Arc<AppState>>,
    Path(track_id): Path<String>,
) -> Result<impl IntoResponse, AppError> {
    // Extract numeric ID: fma_50833 -> 50833
    let num_id = track_id.replace("fma_", "");
    let padded = format!("{:0>6}", num_id);
    let prefix = &padded[..3];

    let gcs = state.gcs.as_ref().as_ref().ok_or_else(|| {
        AppError::ServiceUnavailable("Audio streaming is not available (GCS not configured)".into())
    })?;

    let blob_path = format!("{}/{}/{}.mp3", state.config.gcs_audio_prefix, prefix, padded);

    let bytes = gcs
        .download_blob(&state.config.gcs_bucket_name, &blob_path)
        .await
        .map_err(|e| {
            if e.to_string().contains("404") || e.to_string().contains("not found") {
                AppError::NotFound(format!("Audio file not found: {}", blob_path))
            } else {
                AppError::Internal(e.to_string())
            }
        })?;

    let content_length = bytes.len();

    Ok((
        [
            (header::CONTENT_TYPE, "audio/mpeg".to_string()),
            (header::ACCEPT_RANGES, "bytes".to_string()),
            (header::CONTENT_LENGTH, content_length.to_string()),
        ],
        bytes,
    ))
}
