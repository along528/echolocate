use axum::http::StatusCode;
use serde_json::json;

use crate::common::*;

#[tokio::test]
async fn search_without_terms_is_400() {
    let (status, body) = get(app(), "/search").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["detail"]
        .as_str()
        .unwrap()
        .contains("At least one search parameter required"));
}

#[tokio::test]
async fn search_matches_title_ilike() {
    // Derive the term from a real track so the test is index-agnostic.
    let track = &sample_tracks(1).await[0];
    let title = track["title"].as_str().unwrap();
    let term = title.split_whitespace().next().unwrap();

    let (status, body) = get(
        app(),
        &format!("/search?query={}&source=all&limit=50", term),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert!(!rows.is_empty());
    assert!(ids_of(rows).contains(&track["id"].as_str().unwrap().to_string()));

    let needle = term.to_lowercase();
    for row in rows {
        let haystack = format!(
            "{} {} {}",
            row["title"].as_str().unwrap(),
            row["artist"].as_str().unwrap(),
            row["album"].as_str().unwrap()
        )
        .to_lowercase();
        assert!(haystack.contains(&needle), "ILIKE mismatch: {row}");
    }
}

#[tokio::test]
async fn search_no_match_is_empty() {
    let (status, body) = get(app(), "/search?query=zzz_no_such_track_zzz&source=all").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!([]));
}

#[tokio::test]
async fn search_artist_filter_and_limit() {
    let track = &sample_tracks(1).await[0];
    let artist_word = track["artist"]
        .as_str()
        .unwrap()
        .split_whitespace()
        .next()
        .unwrap();

    let (status, body) = get(
        app(),
        &format!("/search?artist={}&source=all&limit=3", artist_word),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert!(!rows.is_empty() && rows.len() <= 3, "limit respected");
    let needle = artist_word.to_lowercase();
    for row in rows {
        assert!(row["artist"].as_str().unwrap().to_lowercase().contains(&needle));
    }
}

#[tokio::test]
async fn search_unknown_source_is_empty_200() {
    // Pins current behavior: an unknown source is not an error — the WHERE
    // source = 'bogus' filter simply matches nothing on the tracks view.
    let track = &sample_tracks(1).await[0];
    let term = track["title"].as_str().unwrap().split_whitespace().next().unwrap();
    let (status, body) = get(app(), &format!("/search?query={term}&source=bogus")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, json!([]));
}

#[tokio::test]
async fn vector_search_validates_dimension() {
    let (status, body) = post_json(
        app(),
        "/vector-search",
        json!({ "vector": [0.1, 0.2, 0.3], "limit": 5 }),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["detail"].as_str().unwrap().contains("768"));
}

#[tokio::test]
async fn vector_search_returns_sorted_results() {
    let mut vector = vec![0.0f32; 768];
    vector[0] = 1.0;
    let (status, body) = post_json(
        app(),
        "/vector-search",
        json!({ "vector": vector, "limit": 5, "source": "fma" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_eq!(rows.len(), 5);
    assert_sorted_desc(rows, "similarity");
    assert!(rows.iter().all(|r| r["source"] == "fma"));
}

#[tokio::test]
async fn semantic_search_503_without_model() {
    // The ONNX-less state must degrade to 503, mirroring stream-without-GCS.
    let (status, body) = post_json(
        app(),
        "/semantic-search",
        json!({ "query": "dreamy lo-fi", "limit": 3 }),
    )
    .await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(body["detail"].as_str().unwrap().contains("semantic search unavailable"));
}

#[tokio::test]
async fn semantic_search_with_real_model() {
    let Some(state) = onnx_state() else {
        eprintln!("SKIPPED: semantic_search_with_real_model (CLAP model / ORT unavailable)");
        return;
    };
    let router = cloud_crate_vector::build_router(state);

    let (status, body) = post_json(
        router.clone(),
        "/semantic-search",
        json!({ "query": "dreamy lo-fi", "limit": 7, "source": "fma" }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["original_query"], "dreamy lo-fi");
    assert!(body.get("enhanced_query").is_none(), "no Gemini in tests");
    let rows = body["results"].as_array().unwrap();
    assert_eq!(rows.len(), 7);
    assert_sorted_desc(rows, "similarity");

    // enhance=true must still succeed as a no-op without Gemini.
    let (status, body) = post_json(
        router,
        "/semantic-search",
        json!({ "query": "acid house", "limit": 2, "source": "fma", "enhance": true }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["results"].as_array().unwrap().len(), 2);
}
