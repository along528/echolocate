//! Live per-track vibe chips.
//!
//! A fixed vibe vocabulary (`vibes.txt`) is embedded with the in-process CLAP
//! text encoder once, in the background at startup, into unit-normalized
//! anchor vectors. A track's vibes are then just the top-k cosine scores
//! between its stored `v_clap` and the anchors — no DB column, no pipeline
//! rebuild, and the vocabulary can change with a redeploy.
//!
//! Anchor computation is ~48 serial inferences (a few seconds, off the serving
//! path). If the vocabulary ever grows 10x, the escape hatch is precomputing
//! an anchors.json into the Docker image next to the ONNX model dir.

use crate::clap_onnx::ClapOnnxModel;
use crate::models::VibeScore;

pub const DEFAULT_TOP_K: usize = 3;
pub const MAX_TOP_K: usize = 10;
/// CLAP text–audio cosine scores run low; 0.25 is a starting point, tune via
/// the `min_score` query param before changing the default.
pub const DEFAULT_MIN_SCORE: f32 = 0.25;

/// Vibe vocabulary embedded into unit-normalized 512-dim anchor rows.
pub struct VibeAnchors {
    pub vocab: Vec<String>,
    pub matrix: Vec<Vec<f32>>,
}

/// Parse the compiled-in vocabulary: one term per line, `#` comments allowed.
pub fn default_vocab() -> Vec<String> {
    include_str!("../vibes.txt")
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(String::from)
        .collect()
}

/// Encode every vocabulary term with the CLAP text encoder and l2-normalize.
pub fn compute_anchors(model: &ClapOnnxModel, vocab: &[String]) -> Result<VibeAnchors, String> {
    let mut matrix = Vec::with_capacity(vocab.len());
    for term in vocab {
        let start = std::time::Instant::now();
        let mut v = model
            .encode_text(term)
            .map_err(|e| format!("CLAP encoding failed for vibe '{term}': {e}"))?;
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            for x in v.iter_mut() {
                *x /= norm;
            }
        }
        tracing::debug!("Vibe anchor '{term}' embedded in {:.2?}", start.elapsed());
        matrix.push(v);
    }
    Ok(VibeAnchors {
        vocab: vocab.to_vec(),
        matrix,
    })
}

/// Top-k vibes for a track's `v_clap`, sorted by descending cosine score and
/// cut at `min_score`. Returns empty for a zero/empty input vector.
pub fn top_vibes(anchors: &VibeAnchors, v_clap: &[f32], k: usize, min_score: f32) -> Vec<VibeScore> {
    let norm = v_clap.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm == 0.0 {
        return Vec::new();
    }
    let k = k.clamp(1, MAX_TOP_K);

    let mut scored: Vec<VibeScore> = anchors
        .vocab
        .iter()
        .zip(&anchors.matrix)
        .filter_map(|(vibe, anchor)| {
            if anchor.len() != v_clap.len() {
                return None;
            }
            let dot: f32 = anchor.iter().zip(v_clap).map(|(a, b)| a * b).sum();
            let score = dot / norm; // anchors are unit vectors
            (score >= min_score).then(|| VibeScore {
                vibe: vibe.clone(),
                score,
            })
        })
        .collect();

    scored.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(k);
    scored
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(dim: usize, idx: usize) -> Vec<f32> {
        let mut v = vec![0.0; dim];
        v[idx] = 1.0;
        v
    }

    fn anchors() -> VibeAnchors {
        VibeAnchors {
            vocab: vec!["a".into(), "b".into(), "c".into()],
            matrix: vec![unit(4, 0), unit(4, 1), unit(4, 2)],
        }
    }

    #[test]
    fn sorted_desc_and_thresholded() {
        let v = vec![0.9, 0.3, -0.5, 0.0];
        let out = top_vibes(&anchors(), &v, 10, 0.0);
        assert_eq!(out.len(), 2); // -0.5 cut by threshold
        assert_eq!(out[0].vibe, "a");
        assert_eq!(out[1].vibe, "b");
        assert!(out[0].score > out[1].score);
    }

    #[test]
    fn k_is_clamped() {
        let v = vec![0.5, 0.5, 0.5, 0.0];
        assert_eq!(top_vibes(&anchors(), &v, 0, -1.0).len(), 1); // clamped up to 1
        assert_eq!(top_vibes(&anchors(), &v, 100, -1.0).len(), 3); // only 3 anchors
    }

    #[test]
    fn zero_vector_is_empty() {
        assert!(top_vibes(&anchors(), &[0.0; 4], 3, -1.0).is_empty());
    }

    #[test]
    fn dimension_mismatch_skipped() {
        let mut a = anchors();
        a.matrix[1] = unit(8, 1); // wrong dim — must be skipped, not panic
        let v = vec![1.0, 0.0, 0.0, 0.0];
        let out = top_vibes(&a, &v, 10, -1.0);
        assert_eq!(out.len(), 2);
    }

    #[test]
    fn scores_are_cosine() {
        // Non-unit input vector: score must be normalized dot product.
        let v = vec![2.0, 0.0, 0.0, 0.0];
        let out = top_vibes(&anchors(), &v, 1, -1.0);
        assert!((out[0].score - 1.0).abs() < 1e-6);
    }

    #[test]
    fn default_vocab_parses() {
        let vocab = default_vocab();
        assert!(vocab.len() >= 40, "expected ~48 terms, got {}", vocab.len());
        assert!(vocab.contains(&"dreamy lo-fi".to_string()));
        assert!(vocab.iter().all(|t| !t.starts_with('#') && !t.is_empty()));
    }
}
