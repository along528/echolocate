//! GET /map/regions — constellation (named-neighborhood) tests against the
//! synthetic sample index with the fake unit-basis vibe anchors.

use axum::http::StatusCode;
use std::collections::HashSet;

use crate::common::*;

#[tokio::test]
async fn regions_not_ready_without_anchors() {
    // The default app has no vibe anchors — same "optional decoration"
    // contract as /tracks/{id}/vibes: 200, ready:false, no regions.
    let (status, body) = get(app(), "/map/regions?source=fma").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], false);
    assert!(body["regions"].as_array().unwrap().is_empty());
}

#[tokio::test]
async fn regions_named_from_anchors() {
    let (status, body) = get(fake_vibes_app(), "/map/regions?source=fma&k=3").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], true);
    assert_eq!(body["source"], "fma");
    assert_eq!(body["k"], 3);

    let regions = body["regions"].as_array().unwrap();
    assert!(!regions.is_empty() && regions.len() <= 3, "1..=k regions: {}", regions.len());

    let mut labels = HashSet::new();
    for r in regions {
        let label = r["label"].as_str().unwrap();
        assert!(FAKE_VIBES.contains(&label), "label from the vocabulary: {label}");
        assert!(labels.insert(label), "labels unique while vocab lasts");
        let x = r["x"].as_f64().unwrap();
        let y = r["y"].as_f64().unwrap();
        assert!((0.0..=1.0).contains(&x) && (0.0..=1.0).contains(&y));
        assert!(r["count"].as_u64().unwrap() >= 1);
        assert!(r["spread"].as_f64().unwrap() >= 0.0);
        assert!(r["score"].is_number());
    }

    // Biggest neighborhoods come first (draw order for clients).
    let counts: Vec<u64> = regions.iter().map(|r| r["count"].as_u64().unwrap()).collect();
    for pair in counts.windows(2) {
        assert!(pair[0] >= pair[1], "counts sorted descending: {counts:?}");
    }
}

#[tokio::test]
async fn regions_are_cached_per_key() {
    // Two calls with the same (source, k, n) must return the identical
    // payload — the sample is random, so equality proves the cache hit.
    let uri = "/map/regions?source=fma&k=4&n=200";
    let (s1, b1) = get(fake_vibes_app(), uri).await;
    let (s2, b2) = get(fake_vibes_app(), uri).await;
    assert_eq!(s1, StatusCode::OK);
    assert_eq!(s2, StatusCode::OK);
    assert_eq!(b1, b2);
}

#[tokio::test]
async fn regions_params_clamped() {
    // k above the max clamps down; a bogus source yields no rows → ready but
    // empty (nothing to name), never an error.
    let (status, body) = get(fake_vibes_app(), "/map/regions?source=fma&k=99").await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["k"].as_u64().unwrap() <= 12);

    let (status, body) = get(fake_vibes_app(), "/map/regions?source=bogus").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], true);
    assert!(body["regions"].as_array().unwrap().is_empty());
}
