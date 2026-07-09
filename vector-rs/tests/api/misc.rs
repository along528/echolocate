use axum::http::StatusCode;
use serde_json::json;

use crate::common::*;

#[tokio::test]
async fn health_check() {
    let (status, body) = get(app(), "/").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!({ "status": "ok", "service": "cloudcrate-vector" }));
}

#[tokio::test]
async fn version_reports_configured_values() {
    let (status, body) = get(app(), "/version").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["index"], "test");
    assert_eq!(body["model"], "test");
    assert_eq!(body["git_sha"], "test");
}

#[tokio::test]
async fn unknown_route_404() {
    let (status, _) = get(app(), "/definitely-not-a-route").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn stream_rejects_malformed_id() {
    // Format validation runs before the GCS check.
    let (status, body) = get(app(), "/stream/notdigits").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body["detail"], "Invalid track ID format");
}

#[tokio::test]
async fn stream_503_without_gcs() {
    let (status, body) = get(app(), "/stream/fma_12345").await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(body["detail"].as_str().unwrap().contains("not available"));
}

#[tokio::test]
async fn labels_search_rejects_bad_kind() {
    let (status, _) = post_json(
        app(),
        "/labels/search",
        json!({
            "search_id": "s1", "session_id": "sess1",
            "endpoint": "/semantic-search", "query_kind": "invalid-kind",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn labels_search_accepts_valid_event() {
    // Without GCS the upload is dropped with a warning, but the API contract
    // (204 fire-and-forget) holds.
    let (status, _) = post_json(
        app(),
        "/labels/search",
        json!({
            "search_id": "test-search-1", "session_id": "test-sess-1",
            "endpoint": "/semantic-search", "query_kind": "text",
            "query": {"text": "dreamy"}, "results": [],
        }),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
}

#[tokio::test]
async fn labels_result_rejects_bad_signal() {
    let (status, _) = post_json(
        app(),
        "/labels/result",
        json!({
            "label_id": "l1", "search_id": "s1", "session_id": "sess1",
            "track_id": "abc", "rank": 1, "signal": "amazing",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn labels_result_accepts_valid_label() {
    let (status, _) = post_json(
        app(),
        "/labels/result",
        json!({
            "label_id": "test-label-1", "search_id": "s1", "session_id": "sess1",
            "track_id": "abc123", "rank": 0, "signal": "relevant",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::NO_CONTENT);
}

#[tokio::test]
async fn labels_events_503_without_gcs() {
    let (status, body) = get(app(), "/labels/events").await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(body["detail"], "GCS unavailable");
}
