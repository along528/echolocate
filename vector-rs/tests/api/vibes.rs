use axum::http::StatusCode;
use serde_json::json;

use crate::common::*;
use cloud_crate_vector::vibes::{compute_anchors, top_vibes};

#[tokio::test]
async fn vibes_not_ready_is_200_empty() {
    // Default state has an empty anchors OnceLock — mirrors a cold start
    // before the background warmup lands (or an ONNX-less deployment).
    let id = &sample_ids(1).await[0];
    let (status, body) = get(app(), &format!("/tracks/{id}/vibes")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], false);
    assert_eq!(body["vibes"], json!([]));
}

#[tokio::test]
async fn vibes_structural_with_fake_anchors() {
    let id = &sample_ids(1).await[0];
    // min_score=-1 admits every anchor; random v_clap scores hover near 0.
    let (status, body) = get(
        fake_vibes_app(),
        &format!("/tracks/{id}/vibes?min_score=-1&k=5"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], true);
    assert_eq!(body["track_id"].as_str().unwrap(), id);

    let vibes = body["vibes"].as_array().unwrap();
    assert_eq!(vibes.len(), FAKE_VIBES.len(), "all 3 fake anchors admitted");
    assert_sorted_desc(vibes, "score");
    for v in vibes {
        assert!(FAKE_VIBES.contains(&v["vibe"].as_str().unwrap()));
        let score = v["score"].as_f64().unwrap();
        assert!((-1.0..=1.0).contains(&score), "cosine out of range: {score}");
    }
}

#[tokio::test]
async fn vibes_threshold_filters_everything() {
    let id = &sample_ids(1).await[0];
    let (status, body) = get(
        fake_vibes_app(),
        &format!("/tracks/{id}/vibes?min_score=1.1"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ready"], true);
    assert_eq!(body["vibes"], json!([]));
}

#[tokio::test]
async fn vibes_unknown_track_404() {
    let (status, body) = get(fake_vibes_app(), "/tracks/doesnotexist/vibes").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["detail"], "Track not found");
}

#[tokio::test]
async fn by_ids_include_vibes_attaches_field() {
    let ids = sample_ids(4).await;

    let (status, body) = post_json(
        fake_vibes_app(),
        "/tracks/by-ids",
        json!({ "ids": ids, "include_vibes": true }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let rows = body.as_array().unwrap();
    assert_eq!(rows.len(), 4);
    for row in rows {
        // Present as an array even when the default min_score cuts every
        // near-zero random score.
        assert!(row["vibes"].is_array(), "vibes field attached: {row}");
    }

    // Explicit false (and the default) must omit the field entirely.
    let (status, body) = post_json(
        fake_vibes_app(),
        "/tracks/by-ids",
        json!({ "ids": ids, "include_vibes": false }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    for row in body.as_array().unwrap() {
        assert!(row.get("vibes").is_none(), "no vibes field when not requested");
    }
}

#[tokio::test]
async fn by_ids_vibes_threshold_and_k_overrides() {
    // The sonar preview drops the threshold to -1 so chips render against the
    // synthetic index's random vectors — pin that contract.
    let ids = sample_ids(2).await;
    let (status, body) = post_json(
        fake_vibes_app(),
        "/tracks/by-ids",
        json!({ "ids": ids, "include_vibes": true, "vibes_min_score": -1.0, "vibes_k": 5 }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    for row in body.as_array().unwrap() {
        let vibes = row["vibes"].as_array().unwrap();
        assert_eq!(vibes.len(), FAKE_VIBES.len(), "min_score=-1 admits all fake anchors");
        assert_sorted_desc(vibes, "score");
    }
}

#[tokio::test]
async fn by_ids_include_vibes_noop_while_warming() {
    // include_vibes against a state with no anchors: field silently absent.
    let ids = sample_ids(2).await;
    let (status, body) = post_json(
        app(),
        "/tracks/by-ids",
        json!({ "ids": ids, "include_vibes": true }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    for row in body.as_array().unwrap() {
        assert!(row.get("vibes").is_none());
    }
}

#[tokio::test(flavor = "multi_thread")] // block_in_place needs the threaded runtime
async fn real_onnx_anchors_are_unit_512dim() {
    let Some(state) = onnx_state() else {
        eprintln!("SKIPPED: real_onnx_anchors_are_unit_512dim (CLAP model / ORT unavailable)");
        return;
    };
    let model = state.onnx.as_ref().as_ref().unwrap();

    // A 3-term slice keeps this to 3 inferences.
    let vocab: Vec<String> = vec!["calm ambient".into(), "aggressive noise".into(), "smooth jazz".into()];
    let anchors = tokio::task::block_in_place(|| compute_anchors(model, &vocab)).unwrap();

    assert_eq!(anchors.vocab, vocab);
    for row in &anchors.matrix {
        assert_eq!(row.len(), 512);
        let norm: f32 = row.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-3, "anchor not unit-normalized: {norm}");
    }

    // An anchor queried against itself must rank first with cosine ~1.
    let top = top_vibes(&anchors, &anchors.matrix[1], 3, -1.0);
    assert_eq!(top[0].vibe, "aggressive noise");
    assert!((top[0].score - 1.0).abs() < 1e-4);
}
