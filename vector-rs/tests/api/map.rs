use axum::http::StatusCode;
use crate::common::*;

#[tokio::test]
async fn backdrop_default_sample() {
    let (status, body) = get(app(), "/map/backdrop?source=fma").await;
    assert_eq!(status, StatusCode::OK);
    let points = body.as_array().unwrap();
    assert!(!points.is_empty() && points.len() <= 400);
    for p in points {
        assert!(p["id"].is_string());
        let x = p["x"].as_f64().unwrap();
        let y = p["y"].as_f64().unwrap();
        assert!((0.0..=1.0).contains(&x) && (0.0..=1.0).contains(&y));
    }
}

#[tokio::test]
async fn backdrop_n_is_clamped() {
    let (status, body) = get(app(), "/map/backdrop?source=all&n=5000").await;
    assert_eq!(status, StatusCode::OK);
    assert!(body.as_array().unwrap().len() <= 2000);

    let (status, body) = get(app(), "/map/backdrop?source=fma&n=0").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body.as_array().unwrap().len(), 1, "n=0 clamps up to 1");
}

#[tokio::test]
async fn nearest_returns_single_track() {
    let (status, body) = get(app(), "/map/nearest?x=0.5&y=0.5&source=fma").await;
    assert_eq!(status, StatusCode::OK);
    assert!(body.is_object(), "single TrackResponse, not an array");
    assert!(body["id"].is_string());
    assert!(body["x"].is_f64() && body["y"].is_f64());
}

#[tokio::test]
async fn nearest_404_when_nothing_projected() {
    // source=bogus matches zero rows on the view — the constructible
    // "no projected track" case in an index where every track has x,y.
    let (status, body) = get(app(), "/map/nearest?x=0.5&y=0.5&source=bogus").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "No projected track found");
}

#[tokio::test]
async fn nearest_requires_coordinates() {
    // Missing x/y fails Query<MapNearestQuery> deserialization → 400.
    let (status, _) = get(app(), "/map/nearest?source=fma").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}
