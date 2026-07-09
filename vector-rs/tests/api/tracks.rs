use axum::http::StatusCode;
use serde_json::json;
use std::collections::HashSet;

use crate::common::*;

#[tokio::test]
async fn tracks_random_default() {
    let (status, body) = get(app(), "/tracks?source=fma").await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_eq!(rows.len(), 50, "default limit is 50");

    let ids: HashSet<&str> = rows.iter().map(|r| r["id"].as_str().unwrap()).collect();
    assert_eq!(ids.len(), rows.len(), "ids must be unique");

    for row in rows {
        assert!(!row["title"].as_str().unwrap().is_empty());
        assert!(!row["artist"].as_str().unwrap().is_empty());
        assert!(!row["relative_path"].as_str().unwrap().is_empty());
        let x = row["x"].as_f64().unwrap();
        let y = row["y"].as_f64().unwrap();
        assert!((0.0..=1.0).contains(&x) && (0.0..=1.0).contains(&y));
        assert!(row["duration"].as_f64().unwrap() > 0.0);
        assert_eq!(row["source"], "fma");
    }
}

#[tokio::test]
async fn tracks_paged_disjoint_and_sorted() {
    let (s1, page1) = get(app(), "/tracks?random=false&limit=10&offset=0&source=fma").await;
    let (s2, page2) = get(app(), "/tracks?random=false&limit=10&offset=10&source=fma").await;
    assert_eq!(s1, StatusCode::OK);
    assert_eq!(s2, StatusCode::OK);

    let ids1 = ids_of(page1.as_array().unwrap());
    let ids2 = ids_of(page2.as_array().unwrap());
    assert_eq!(ids1.len(), 10);
    assert_eq!(ids2.len(), 10);

    let mut sorted = ids1.clone();
    sorted.sort();
    assert_eq!(ids1, sorted, "non-random listing is ordered by id");

    let set1: HashSet<_> = ids1.iter().collect();
    assert!(ids2.iter().all(|id| !set1.contains(id)), "pages must be disjoint");
}

#[tokio::test]
async fn tracks_source_all() {
    let (status, body) = get(app(), "/tracks?source=all&limit=20").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body.as_array().unwrap().len(), 20);
}

#[tokio::test]
async fn by_ids_roundtrip() {
    let ids = sample_ids(5).await;
    let (status, body) = post_json(app(), "/tracks/by-ids", json!({ "ids": ids })).await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_eq!(rows.len(), 5);

    let returned: HashSet<String> = ids_of(rows).into_iter().collect();
    assert_eq!(returned, ids.into_iter().collect::<HashSet<_>>());
    for row in rows {
        assert!(row["source"].is_string());
    }
}

#[tokio::test]
async fn by_ids_empty_returns_empty() {
    let (status, body) = post_json(app(), "/tracks/by-ids", json!({ "ids": [] })).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!([]));
}

#[tokio::test]
async fn by_ids_over_500_rejected() {
    let ids: Vec<String> = (0..501).map(|i| format!("x{i}")).collect();
    let (status, body) = post_json(app(), "/tracks/by-ids", json!({ "ids": ids })).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["detail"].as_str().unwrap().contains("too many ids"));
}

#[tokio::test]
async fn by_ids_unknown_ids_empty() {
    let (status, body) =
        post_json(app(), "/tracks/by-ids", json!({ "ids": ["doesnotexist"] })).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!([]));
}

#[tokio::test]
async fn similar_excludes_self_and_sorts() {
    let id = &sample_ids(1).await[0];
    let (status, body) = get(app(), &format!("/tracks/{id}/similar?source=fma&limit=5")).await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert!(!rows.is_empty() && rows.len() <= 5);
    assert!(rows.iter().all(|r| r["id"].as_str().unwrap() != id));
    assert_sorted_desc(rows, "similarity");
}

#[tokio::test]
async fn similar_source_all_merges() {
    let id = &sample_ids(1).await[0];
    let (status, body) = get(app(), &format!("/tracks/{id}/similar?source=all&limit=8")).await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert!(!rows.is_empty() && rows.len() <= 8);
    assert_sorted_desc(rows, "similarity");
}

#[tokio::test]
async fn dissimilar_sorted_ascending() {
    let id = &sample_ids(1).await[0];
    let (status, body) = get(app(), &format!("/tracks/{id}/dissimilar?source=fma&limit=5")).await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert!(!rows.is_empty() && rows.len() <= 5);
    let sims: Vec<f64> = rows.iter().map(|r| r["similarity"].as_f64().unwrap()).collect();
    for pair in sims.windows(2) {
        assert!(pair[0] <= pair[1], "dissimilar must sort ascending: {sims:?}");
    }
}

#[tokio::test]
async fn similar_unknown_id_404() {
    let (status, body) = get(app(), "/tracks/doesnotexist/similar").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "Track not found");
}
