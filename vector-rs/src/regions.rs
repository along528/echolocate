//! Constellations: auto-named neighborhoods of the sonar map.
//!
//! The 2D projection (`x,y` from `generate_projection.py`) places sonically
//! similar tracks together, but its axes mean nothing to a human — the map is
//! an unlabeled starfield. This module names it: k-means over a sample of the
//! projected corpus finds the dense neighborhoods, and each one is labeled by
//! scoring the unit-mean of its members' `v_clap` embeddings against the same
//! CLAP vibe anchors that power per-track vibe chips (`vibes.rs`). No new
//! models, no DB columns — the vocabulary in `vibes.txt` becomes place names.
//!
//! Everything here is pure (no I/O); the `/map/regions` handler feeds it a
//! DB sample and caches the result per (source, k, n) for the process
//! lifetime, so the constellation names are stable for every client of a
//! given deployment.

use crate::models::MapRegion;
use crate::vibes::VibeAnchors;

pub const DEFAULT_K: usize = 6;
pub const MAX_K: usize = 12;
pub const DEFAULT_SAMPLE: i64 = 1500;
pub const MAX_SAMPLE: i64 = 4000;
const KMEANS_ITERS: usize = 50;
/// Fixed PRNG seed ("SONar-CODE-DESIgn-SEED"): clustering is deterministic
/// for a given input sample.
const KMEANS_SEED: u64 = 0x5051_4EC7_0DE5_1EED;

/// One sampled track: projected position + CLAP embedding.
pub struct RegionPoint {
    pub x: f64,
    pub y: f64,
    pub v_clap: Vec<f32>,
}

/// A k-means cluster of the 2D projection, with the unit-normalized mean
/// CLAP embedding of its members (empty when no member had a usable vector).
pub struct RegionCluster {
    pub x: f64,
    pub y: f64,
    pub count: usize,
    /// RMS distance of members to the centroid, in projection units — a size
    /// hint for rendering (bigger, sparser neighborhoods get smaller type).
    pub spread: f64,
    pub mean_clap: Vec<f32>,
}

/// Minimal deterministic PRNG (PCG-style LCG) so clustering is reproducible
/// for a given input sample without pulling in a rand dependency.
struct Lcg(u64);

impl Lcg {
    fn next_u64(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        // xorshift the high bits down so short ranges aren't stuck in the
        // low-entropy low bits of the LCG state.
        (self.0 >> 33) ^ self.0
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next_u64() % n.max(1) as u64) as usize
    }

    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
}

fn dist2(ax: f64, ay: f64, bx: f64, by: f64) -> f64 {
    (ax - bx) * (ax - bx) + (ay - by) * (ay - by)
}

/// K-means over the 2D projection with k-means++ seeding. Deterministic for a
/// given input slice. Empty clusters are dropped, so the result may have fewer
/// than `k` entries; output is sorted by descending member count.
pub fn cluster(points: &[RegionPoint], k: usize) -> Vec<RegionCluster> {
    if points.is_empty() {
        return Vec::new();
    }
    let k = k.clamp(1, points.len());
    let mut rng = Lcg(KMEANS_SEED);

    // k-means++ init: first centroid uniform, then each next one drawn with
    // probability proportional to squared distance from the nearest centroid.
    let mut centroids: Vec<(f64, f64)> = Vec::with_capacity(k);
    let first = &points[rng.below(points.len())];
    centroids.push((first.x, first.y));
    let mut d2: Vec<f64> = points
        .iter()
        .map(|p| dist2(p.x, p.y, first.x, first.y))
        .collect();
    while centroids.len() < k {
        let total: f64 = d2.iter().sum();
        let idx = if total <= 0.0 {
            rng.below(points.len())
        } else {
            let mut target = rng.next_f64() * total;
            let mut chosen = points.len() - 1;
            for (i, w) in d2.iter().enumerate() {
                target -= w;
                if target <= 0.0 {
                    chosen = i;
                    break;
                }
            }
            chosen
        };
        let c = &points[idx];
        centroids.push((c.x, c.y));
        for (i, p) in points.iter().enumerate() {
            d2[i] = d2[i].min(dist2(p.x, p.y, c.x, c.y));
        }
    }

    // Lloyd iterations until assignments stabilize.
    let mut assign = vec![0usize; points.len()];
    for _ in 0..KMEANS_ITERS {
        let mut changed = false;
        for (i, p) in points.iter().enumerate() {
            let mut best = 0;
            let mut best_d = f64::INFINITY;
            for (ci, &(cx, cy)) in centroids.iter().enumerate() {
                let d = dist2(p.x, p.y, cx, cy);
                if d < best_d {
                    best_d = d;
                    best = ci;
                }
            }
            if assign[i] != best {
                assign[i] = best;
                changed = true;
            }
        }
        let mut sums = vec![(0.0f64, 0.0f64, 0usize); centroids.len()];
        for (i, p) in points.iter().enumerate() {
            let s = &mut sums[assign[i]];
            s.0 += p.x;
            s.1 += p.y;
            s.2 += 1;
        }
        for (ci, &(sx, sy, n)) in sums.iter().enumerate() {
            if n > 0 {
                centroids[ci] = (sx / n as f64, sy / n as f64);
            }
        }
        if !changed {
            break;
        }
    }

    let mut clusters: Vec<RegionCluster> = centroids
        .iter()
        .enumerate()
        .filter_map(|(ci, &(cx, cy))| {
            let members: Vec<&RegionPoint> =
                points.iter().zip(&assign).filter(|(_, &a)| a == ci).map(|(p, _)| p).collect();
            if members.is_empty() {
                return None;
            }
            let spread = (members
                .iter()
                .map(|p| dist2(p.x, p.y, cx, cy))
                .sum::<f64>()
                / members.len() as f64)
                .sqrt();
            // Mean CLAP over members with the modal (most common) vector
            // length, so a few malformed rows can't poison the dimension.
            let dim = modal_dim(&members);
            let mut mean = vec![0.0f32; dim];
            let mut n = 0usize;
            for p in &members {
                if p.v_clap.len() == dim && dim > 0 {
                    for (m, v) in mean.iter_mut().zip(&p.v_clap) {
                        *m += v;
                    }
                    n += 1;
                }
            }
            if n > 0 {
                let norm = mean.iter().map(|x| x * x).sum::<f32>().sqrt();
                if norm > 0.0 {
                    for m in mean.iter_mut() {
                        *m /= norm;
                    }
                } else {
                    mean.clear();
                }
            } else {
                mean.clear();
            }
            Some(RegionCluster {
                x: cx,
                y: cy,
                count: members.len(),
                spread,
                mean_clap: mean,
            })
        })
        .collect();
    clusters.sort_by(|a, b| b.count.cmp(&a.count));
    clusters
}

fn modal_dim(members: &[&RegionPoint]) -> usize {
    let mut counts: std::collections::HashMap<usize, usize> = std::collections::HashMap::new();
    for p in members {
        if !p.v_clap.is_empty() {
            *counts.entry(p.v_clap.len()).or_insert(0) += 1;
        }
    }
    counts.into_iter().max_by_key(|&(_, n)| n).map(|(d, _)| d).unwrap_or(0)
}

/// Name each cluster from the vibe anchors. Labels are unique: clusters are
/// processed in order of their strongest anchor affinity, each taking its
/// best-ranked term not already claimed. If there are more clusters than
/// vocabulary terms, leftovers reuse their own top term. Clusters with no
/// usable mean embedding (or an empty vocabulary) are dropped.
pub fn label_clusters(anchors: &VibeAnchors, clusters: &[RegionCluster]) -> Vec<MapRegion> {
    // Per-cluster ranked (score, vocab index) lists, best first.
    let ranked: Vec<Vec<(f32, usize)>> = clusters
        .iter()
        .map(|c| {
            let mut scores: Vec<(f32, usize)> = anchors
                .vocab
                .iter()
                .enumerate()
                .filter_map(|(vi, _)| {
                    let a = &anchors.matrix[vi];
                    if a.len() != c.mean_clap.len() || a.is_empty() {
                        return None;
                    }
                    let dot: f32 = a.iter().zip(&c.mean_clap).map(|(x, y)| x * y).sum();
                    Some((dot, vi))
                })
                .collect();
            scores.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
            scores
        })
        .collect();

    // Strongest-affinity cluster picks first.
    let mut order: Vec<usize> = (0..clusters.len()).filter(|&i| !ranked[i].is_empty()).collect();
    order.sort_by(|&a, &b| {
        ranked[b][0]
            .0
            .partial_cmp(&ranked[a][0].0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut used = vec![false; anchors.vocab.len()];
    let mut out: Vec<MapRegion> = Vec::with_capacity(order.len());
    for ci in order {
        let pick = ranked[ci]
            .iter()
            .find(|&&(_, vi)| !used[vi])
            .or_else(|| ranked[ci].first());
        if let Some(&(score, vi)) = pick {
            used[vi] = true;
            let c = &clusters[ci];
            out.push(MapRegion {
                label: anchors.vocab[vi].clone(),
                x: c.x,
                y: c.y,
                count: c.count,
                spread: c.spread,
                score,
            });
        }
    }
    // Back to biggest-first, the order clients want to draw them in.
    out.sort_by(|a, b| b.count.cmp(&a.count));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pt(x: f64, y: f64, v: Vec<f32>) -> RegionPoint {
        RegionPoint { x, y, v_clap: v }
    }

    fn unit(dim: usize, idx: usize) -> Vec<f32> {
        let mut v = vec![0.0; dim];
        v[idx] = 1.0;
        v
    }

    fn anchors() -> VibeAnchors {
        VibeAnchors {
            vocab: vec!["calm".into(), "fierce".into(), "weird".into()],
            matrix: vec![unit(4, 0), unit(4, 1), unit(4, 2)],
        }
    }

    /// Two tight blobs in opposite corners, each pure in one anchor direction.
    fn two_blobs() -> Vec<RegionPoint> {
        let mut pts = Vec::new();
        for i in 0..20 {
            let j = (i % 5) as f64 * 0.01;
            pts.push(pt(0.1 + j, 0.1 + j, unit(4, 0)));
            pts.push(pt(0.9 - j, 0.9 - j, unit(4, 1)));
        }
        pts
    }

    #[test]
    fn clusters_separate_blobs() {
        let clusters = cluster(&two_blobs(), 2);
        assert_eq!(clusters.len(), 2);
        assert_eq!(clusters[0].count + clusters[1].count, 40);
        // One centroid near each corner, whichever order.
        let mut xs: Vec<f64> = clusters.iter().map(|c| c.x).collect();
        xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
        assert!((xs[0] - 0.12).abs() < 0.05, "low blob centroid: {xs:?}");
        assert!((xs[1] - 0.88).abs() < 0.05, "high blob centroid: {xs:?}");
        // Tight blobs → small spread; mean vectors are unit-normalized.
        for c in &clusters {
            assert!(c.spread < 0.05);
            let norm: f32 = c.mean_clap.iter().map(|x| x * x).sum::<f32>().sqrt();
            assert!((norm - 1.0).abs() < 1e-5);
        }
    }

    #[test]
    fn deterministic_for_same_input() {
        let pts = two_blobs();
        let a = cluster(&pts, 3);
        let b = cluster(&pts, 3);
        assert_eq!(a.len(), b.len());
        for (ca, cb) in a.iter().zip(&b) {
            assert_eq!(ca.count, cb.count);
            assert!((ca.x - cb.x).abs() < 1e-12 && (ca.y - cb.y).abs() < 1e-12);
        }
    }

    #[test]
    fn k_clamped_to_point_count() {
        let pts = vec![pt(0.2, 0.2, unit(4, 0)), pt(0.8, 0.8, unit(4, 1))];
        let clusters = cluster(&pts, 10);
        assert_eq!(clusters.len(), 2);
    }

    #[test]
    fn empty_input_empty_output() {
        assert!(cluster(&[], 5).is_empty());
    }

    #[test]
    fn malformed_vectors_dont_poison_the_mean() {
        // 3 good members + 1 wrong-dim member: modal dim wins.
        let pts = vec![
            pt(0.5, 0.5, unit(4, 2)),
            pt(0.5, 0.5, unit(4, 2)),
            pt(0.5, 0.5, unit(4, 2)),
            pt(0.5, 0.5, unit(8, 1)),
        ];
        let clusters = cluster(&pts, 1);
        assert_eq!(clusters[0].mean_clap.len(), 4);
        assert!((clusters[0].mean_clap[2] - 1.0).abs() < 1e-5);
    }

    #[test]
    fn labels_are_unique_and_matched() {
        let clusters = cluster(&two_blobs(), 2);
        let regions = label_clusters(&anchors(), &clusters);
        assert_eq!(regions.len(), 2);
        let labels: Vec<&str> = regions.iter().map(|r| r.label.as_str()).collect();
        assert!(labels.contains(&"calm") && labels.contains(&"fierce"), "{labels:?}");
        for r in &regions {
            assert!(r.score > 0.9, "pure blobs should score ~1: {}", r.score);
        }
    }

    #[test]
    fn more_clusters_than_vocab_reuses_top_term() {
        // 4 clusters, 3 vocab terms — every cluster still gets a name.
        let mut pts = Vec::new();
        for (cx, cy) in [(0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)] {
            for i in 0..10 {
                pts.push(pt(cx + (i as f64) * 0.005, cy, unit(4, 0)));
            }
        }
        let clusters = cluster(&pts, 4);
        assert_eq!(clusters.len(), 4);
        let regions = label_clusters(&anchors(), &clusters);
        assert_eq!(regions.len(), 4);
        assert!(regions.iter().all(|r| !r.label.is_empty()));
    }

    #[test]
    fn unlabelable_clusters_dropped() {
        // A cluster whose members have no usable v_clap gets no region.
        let pts = vec![pt(0.5, 0.5, vec![]), pt(0.51, 0.5, vec![])];
        let clusters = cluster(&pts, 1);
        assert_eq!(clusters.len(), 1);
        assert!(clusters[0].mean_clap.is_empty());
        assert!(label_clusters(&anchors(), &clusters).is_empty());
    }
}
