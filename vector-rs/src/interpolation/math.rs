/// Spherical Linear Interpolation.
/// v0, v1: vectors, t: interpolation factor (0.0 to 1.0). Default 0.5 for midpoint.
pub fn slerp(v0: &[f32], v1: &[f32], t: f32) -> Vec<f32> {
    let norm0 = norm(v0);
    let norm1 = norm(v1);

    if norm0 == 0.0 || norm1 == 0.0 {
        return average(v0, v1);
    }

    let v0_norm: Vec<f32> = v0.iter().map(|x| x / norm0).collect();
    let v1_norm: Vec<f32> = v1.iter().map(|x| x / norm1).collect();

    let dot: f32 = v0_norm
        .iter()
        .zip(v1_norm.iter())
        .map(|(a, b)| a * b)
        .sum();
    let dot = dot.clamp(-1.0, 1.0);

    // If vectors are too close, fall back to linear average
    if dot > 0.9995 {
        return average(v0, v1);
    }

    let theta_0 = dot.acos();
    let sin_theta_0 = theta_0.sin();

    let theta_t = theta_0 * t;
    let sin_theta_t = theta_t.sin();

    let s0 = (theta_0 - theta_t).sin() / sin_theta_0;
    let s1 = sin_theta_t / sin_theta_0;

    v0.iter()
        .zip(v1.iter())
        .map(|(a, b)| s0 * a + s1 * b)
        .collect()
}

/// De Casteljau algorithm for Bezier curves on the hypersphere via recursive slerp.
pub fn de_casteljau_slerp(control_points: &[Vec<f32>], t: f32) -> Vec<f32> {
    if control_points.len() == 1 {
        return control_points[0].clone();
    }
    let reduced: Vec<Vec<f32>> = control_points
        .windows(2)
        .map(|w| slerp(&w[0], &w[1], t))
        .collect();
    de_casteljau_slerp(&reduced, t)
}

pub fn get_midpoint(vec_a: &[f32], vec_b: &[f32], method: &str) -> Vec<f32> {
    if method == "linear" {
        average(vec_a, vec_b)
    } else {
        slerp(vec_a, vec_b, 0.5)
    }
}

fn norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

fn average(v0: &[f32], v1: &[f32]) -> Vec<f32> {
    v0.iter().zip(v1.iter()).map(|(a, b)| (a + b) / 2.0).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_slerp_midpoint_is_between() {
        let v0 = vec![1.0, 0.0, 0.0];
        let v1 = vec![0.0, 1.0, 0.0];
        let mid = slerp(&v0, &v1, 0.5);
        // Midpoint should be roughly (0.707, 0.707, 0) on the unit sphere
        assert!((mid[0] - 0.5f32.sqrt()).abs() < 0.01);
        assert!((mid[1] - 0.5f32.sqrt()).abs() < 0.01);
        assert!(mid[2].abs() < 0.001);
    }

    #[test]
    fn test_slerp_endpoints() {
        let v0 = vec![1.0, 0.0, 0.0];
        let v1 = vec![0.0, 1.0, 0.0];
        let at_start = slerp(&v0, &v1, 0.0);
        let at_end = slerp(&v0, &v1, 1.0);
        assert!((at_start[0] - 1.0).abs() < 0.01);
        assert!((at_end[1] - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_get_midpoint_linear() {
        let a = vec![2.0, 4.0];
        let b = vec![6.0, 8.0];
        let mid = get_midpoint(&a, &b, "linear");
        assert!((mid[0] - 4.0).abs() < 0.001);
        assert!((mid[1] - 6.0).abs() < 0.001);
    }

    #[test]
    fn test_de_casteljau_two_points() {
        // With 2 points, should be equivalent to slerp
        let v0 = vec![1.0, 0.0, 0.0];
        let v1 = vec![0.0, 1.0, 0.0];
        let bezier = de_casteljau_slerp(&[v0.clone(), v1.clone()], 0.5);
        let direct = slerp(&v0, &v1, 0.5);
        for (a, b) in bezier.iter().zip(direct.iter()) {
            assert!((a - b).abs() < 0.001);
        }
    }
}
