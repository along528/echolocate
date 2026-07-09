use axum::http::StatusCode;
use serde_json::{json, Value};
use std::collections::HashSet;

use crate::common::*;

async fn midpoint(method: &str) -> Vec<Value> {
    let seeds = sample_ids(2).await;
    let (status, body) = post_json(
        app(),
        "/interpolate",
        json!({
            "track_id_1": seeds[0],
            "track_id_2": seeds[1],
            "method": method,
            "limit": 5,
            "source": "fma",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap().clone();
    assert!(!rows.is_empty() && rows.len() <= 5);
    assert!(rows.iter().all(|r| {
        let id = r["id"].as_str().unwrap();
        id != seeds[0] && id != seeds[1]
    }));
    assert_sorted_desc(&rows, "similarity");
    rows
}

#[tokio::test]
async fn interpolate_slerp_midpoint() {
    let rows = midpoint("slerp").await;
    // Coordinates get backfilled from the projection columns.
    assert!(rows.iter().all(|r| r["x"].is_f64() && r["y"].is_f64()));
}

#[tokio::test]
async fn interpolate_linear_midpoint() {
    midpoint("linear").await;
}

#[tokio::test]
async fn interpolate_unknown_ids_404() {
    let (status, body) = post_json(
        app(),
        "/interpolate",
        json!({ "track_id_1": "nope1", "track_id_2": "nope2" }),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["detail"].as_str().unwrap().contains("Could not find both tracks"));
}

fn assert_playlist_shape(rows: &[Value], start: &str, end: &str) {
    assert!(rows.len() >= 2);
    assert_eq!(rows.first().unwrap()["id"], start, "playlist starts at track 1");
    assert_eq!(rows.last().unwrap()["id"], end, "playlist ends at track 2");
    let ids = ids_of(rows);
    let unique: HashSet<&String> = ids.iter().collect();
    assert_eq!(unique.len(), ids.len(), "playlist ids must be unique");
}

#[tokio::test]
async fn playlist_greedy_walk() {
    let seeds = distinct_artist_tracks(2).await;
    let (start, end) = (seeds[0]["id"].as_str().unwrap(), seeds[1]["id"].as_str().unwrap());
    let limit = 10;

    let (status, body) = post_json(
        app(),
        "/interpolate/playlist",
        json!({
            "track_id_1": start,
            "track_id_2": end,
            "method": "greedy_walk",
            "limit": limit,
            "source": "fma",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_playlist_shape(rows, start, end);
    assert!(rows.len() <= limit, "walk stays within limit (start+path+end)");

    // Core greedy-walk invariant: every artist appears at most once. (The
    // sample index has only ~10 artists, so paths are short — assert the
    // invariant, never an exact length.)
    let artists: Vec<&str> = rows.iter().map(|r| r["artist"].as_str().unwrap()).collect();
    let unique: HashSet<&&str> = artists.iter().collect();
    assert_eq!(unique.len(), artists.len(), "artists must be pairwise distinct: {artists:?}");

    // Map coordinates are backfilled onto every playlist node for the trail.
    assert!(rows.iter().all(|r| r["x"].is_f64() && r["y"].is_f64()));
}

#[tokio::test]
async fn playlist_geometric_methods() {
    for method in ["slerp", "linear"] {
        let seeds = distinct_artist_tracks(2).await;
        let (start, end) = (seeds[0]["id"].as_str().unwrap(), seeds[1]["id"].as_str().unwrap());
        let (status, body) = post_json(
            app(),
            "/interpolate/playlist",
            json!({
                "track_id_1": start,
                "track_id_2": end,
                "method": method,
                "limit": 8,
                "source": "fma",
            }),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "method={method}");
        assert_playlist_shape(body.as_array().unwrap(), start, end);
    }
}

#[tokio::test]
async fn playlist_bezier_with_steer() {
    // A geometric method + steer ids routes through De Casteljau bezier;
    // steer tracks are control points, excluded from the resulting path.
    let seeds = distinct_artist_tracks(4).await;
    let (start, end) = (seeds[0]["id"].as_str().unwrap(), seeds[1]["id"].as_str().unwrap());
    let steer: Vec<&str> = vec![seeds[2]["id"].as_str().unwrap(), seeds[3]["id"].as_str().unwrap()];

    let (status, body) = post_json(
        app(),
        "/interpolate/playlist",
        json!({
            "track_id_1": start,
            "track_id_2": end,
            "method": "slerp",
            "steer_track_ids": steer,
            "limit": 8,
            "source": "fma",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_playlist_shape(rows, start, end);
    let ids = ids_of(rows);
    assert!(steer.iter().all(|s| !ids.contains(&s.to_string())),
        "bezier control points must not appear in the path");
}

#[tokio::test]
async fn playlist_greedy_walk_visits_steer_in_order() {
    let seeds = distinct_artist_tracks(4).await;
    let (start, end) = (seeds[0]["id"].as_str().unwrap(), seeds[1]["id"].as_str().unwrap());
    let steer: Vec<&str> = vec![seeds[2]["id"].as_str().unwrap(), seeds[3]["id"].as_str().unwrap()];

    let (status, body) = post_json(
        app(),
        "/interpolate/playlist",
        json!({
            "track_id_1": start,
            "track_id_2": end,
            "method": "greedy_walk",
            "steer_track_ids": steer,
            "limit": 9,
            "source": "fma",
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_playlist_shape(rows, start, end);

    // Multi-segment walk: steering waypoints appear, in the requested order.
    let ids = ids_of(rows);
    let positions: Vec<usize> = steer
        .iter()
        .map(|s| {
            ids.iter()
                .position(|id| id == s)
                .unwrap_or_else(|| panic!("steer id {s} missing from playlist {ids:?}"))
        })
        .collect();
    assert!(positions.windows(2).all(|w| w[0] < w[1]), "steer order preserved");
}

#[tokio::test]
async fn playlist_too_many_steer_ids_400() {
    let seeds = sample_ids(2).await;
    let steer: Vec<String> = (0..51).map(|i| format!("s{i}")).collect();
    let (status, body) = post_json(
        app(),
        "/interpolate/playlist",
        json!({
            "track_id_1": seeds[0],
            "track_id_2": seeds[1],
            "steer_track_ids": steer,
        }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["detail"].as_str().unwrap().contains("Too many steering tracks"));
}

#[tokio::test]
async fn playlist_unknown_ids_404() {
    let (status, body) = post_json(
        app(),
        "/interpolate/playlist",
        json!({ "track_id_1": "nope1", "track_id_2": "nope2" }),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["detail"]
        .as_str()
        .unwrap()
        .contains("Could not find both start and end tracks"));
}
