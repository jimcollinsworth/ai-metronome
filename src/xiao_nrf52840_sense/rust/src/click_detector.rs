//! High-Pass Transients & Sample-Indexed Onset Click Detector (`no_std`).
//!
//! Matches the Python `v2.6` `ClickDetector` algorithm 100%:
//! - First-difference high-pass filter `H(z) = 1 - z^-1` (`y[n] = x[n] - x[n-1]`).
//! - Outlier-resistant lower-tertile ambient calibration across 25 startup frames.
//! - Sub-frame sample-index timestamping (`62.5 us` resolution at 16 kHz).
//! - Adaptive EMA noise floor, crest factor (`>= 1.9`), sharp attack ratio (`>= 1.45x`),
//!   and `120 ms` refractory period.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ClickEvent {
    pub is_click: bool,
    pub onset_time_sec: f64,
    pub hp_peak: i32,
    pub hp_mean: f32,
    pub crest_factor: f32,
    pub threshold: f32,
    pub peak_sample_idx: usize,
}

#[derive(Debug, Clone)]
pub struct ClickDetector {
    pub sample_rate_hz: u32,
    pub refractory_sec: f64,
    pub min_peak_threshold: f32,
    pub snr_ratio: f32,
    pub min_crest_factor: f32,
    pub attack_ratio: f32,
    pub noise_floor_peak: f32,
    pub prev_quiet_peak: f32,
    pub last_click_time_sec: f64,
    pub click_count: u32,
}

impl Default for ClickDetector {
    fn default() -> Self {
        Self::new()
    }
}

impl ClickDetector {
    pub const fn new() -> Self {
        Self {
            sample_rate_hz: 16_000,
            refractory_sec: 0.120,
            min_peak_threshold: 95.0,
            snr_ratio: 2.6,
            min_crest_factor: 1.9,
            attack_ratio: 1.45,
            noise_floor_peak: 55.0,
            prev_quiet_peak: 55.0,
            last_click_time_sec: -10.0,
            click_count: 0,
        }
    }

    /// Compute first-difference high-pass statistics (`(hp_peak, hp_mean, crest, peak_idx)`).
    pub fn compute_hp_stats(samples: &[i16]) -> (i32, f32, f32, usize) {
        let n = samples.len();
        if n < 2 {
            return (0, 0.0, 0.0, 0);
        }

        let mut prev = samples[0] as i32;
        let mut hp_peak: i32 = 0;
        let mut hp_peak_idx: usize = 1;
        let mut hp_sum: i64 = 0;

        for (i, &sample) in samples.iter().enumerate().skip(1) {
            let s = sample as i32;
            let diff = (s - prev).abs();
            prev = s;
            if diff > hp_peak {
                hp_peak = diff;
                hp_peak_idx = i;
            }
            hp_sum += diff as i64;
        }

        let hp_mean = (hp_sum as f32) / ((n - 1) as f32);
        let denom = if hp_mean > 1.0 { hp_mean } else { 1.0 };
        let crest = (hp_peak as f32) / denom;
        (hp_peak, hp_mean, crest, hp_peak_idx)
    }

    /// Calibrate ambient noise floor from startup frame HP peaks using lower-tertile clamping
    /// so accidental clicks during calibration cannot deafen the detector.
    pub fn calibrate_from_peaks(&mut self, peaks: &[i32]) -> f32 {
        if peaks.is_empty() {
            return self.noise_floor_peak;
        }

        // Copy up to 64 peaks onto the stack and insertion-sort them
        let mut sorted = [0i32; 64];
        let count = peaks.len().min(sorted.len());
        sorted[..count].copy_from_slice(&peaks[..count]);
        for i in 1..count {
            let key = sorted[i];
            let mut j = i;
            while j > 0 && sorted[j - 1] > key {
                sorted[j] = sorted[j - 1];
                j -= 1;
            }
            sorted[j] = key;
        }

        let idx = (count / 3).saturating_sub(1);
        let base_peak = sorted[idx] as f32;
        let clamped = base_peak.clamp(35.0, 320.0);
        self.noise_floor_peak = clamped;
        self.prev_quiet_peak = clamped;
        clamped
    }

    /// Current dynamic threshold based on noise floor and bounds.
    #[inline]
    pub fn current_threshold(&self) -> f32 {
        let scaled = (self.noise_floor_peak * self.snr_ratio).min(550.0);
        self.min_peak_threshold.max(scaled)
    }

    /// Process a single audio frame (`80` samples = `5 ms` @ 16 kHz) and return `ClickEvent`.
    pub fn process_frame(&mut self, samples: &[i16], frame_end_sec: f64) -> ClickEvent {
        let (hp_peak, hp_mean, crest, hp_peak_idx) = Self::compute_hp_stats(samples);
        let dyn_thresh = self.current_threshold();
        let hp_peak_f = hp_peak as f32;

        // 1. Refractory window check (120 ms)
        if (frame_end_sec - self.last_click_time_sec) < self.refractory_sec {
            self.prev_quiet_peak = self.noise_floor_peak.max(self.prev_quiet_peak * 0.85);
            return ClickEvent {
                is_click: false,
                onset_time_sec: frame_end_sec,
                hp_peak,
                hp_mean,
                crest_factor: crest,
                threshold: dyn_thresh,
                peak_sample_idx: hp_peak_idx,
            };
        }

        // 2. Evaluate transient sharpness, crest factor, and dynamic SNR threshold
        let is_sharp_attack = hp_peak_f >= (self.prev_quiet_peak * self.attack_ratio);
        let is_impulsive = crest >= self.min_crest_factor;
        let is_above_thresh = hp_peak_f >= dyn_thresh;

        if is_above_thresh && is_impulsive && is_sharp_attack {
            let n = samples.len();
            let sample_offset_sec =
                (n.saturating_sub(hp_peak_idx) as f64) / (self.sample_rate_hz as f64);
            let onset_time_sec = (frame_end_sec - sample_offset_sec).max(0.0);

            self.last_click_time_sec = onset_time_sec;
            self.click_count = self.click_count.wrapping_add(1);
            self.prev_quiet_peak = hp_peak_f;

            return ClickEvent {
                is_click: true,
                onset_time_sec,
                hp_peak,
                hp_mean,
                crest_factor: crest,
                threshold: dyn_thresh,
                peak_sample_idx: hp_peak_idx,
            };
        }

        // 3. Non-click frame: update asymmetric EMA noise floor
        if hp_peak_f < self.noise_floor_peak * 2.0 {
            let alpha = if hp_peak_f < self.noise_floor_peak {
                0.12
            } else {
                0.02
            };
            let updated = (1.0 - alpha) * self.noise_floor_peak + alpha * hp_peak_f;
            self.noise_floor_peak = updated.clamp(35.0, 380.0);
        }
        self.prev_quiet_peak = 0.65 * hp_peak_f + 0.35 * self.noise_floor_peak;

        ClickEvent {
            is_click: false,
            onset_time_sec: frame_end_sec,
            hp_peak,
            hp_mean,
            crest_factor: crest,
            threshold: dyn_thresh,
            peak_sample_idx: hp_peak_idx,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calibration_resists_startup_click_outliers() {
        let mut det = ClickDetector::new();
        // 20 quiet frames around 60, plus 5 loud clicks at 2500
        let mut peaks = [60i32; 25];
        for p in peaks.iter_mut().skip(20) {
            *p = 2500;
        }
        let floor = det.calibrate_from_peaks(&peaks);
        assert!((floor - 60.0).abs() < 1e-3);
        assert!(det.current_threshold() < 200.0);
    }

    #[test]
    fn test_detects_sharp_impulse_with_subframe_timestamp() {
        let mut det = ClickDetector::new();
        det.calibrate_from_peaks(&[50; 25]);

        let quiet = [100i16; 80];
        assert!(!det.process_frame(&quiet, 1.000).is_click);

        // Inject sharp impulse at sample index 40 (halfway through 80-sample 5ms buffer)
        let mut click_frame = [100i16; 80];
        click_frame[40] = 1600;
        click_frame[41] = -800;

        let ev = det.process_frame(&click_frame, 1.005);
        assert!(ev.is_click);
        assert_eq!(ev.peak_sample_idx, 41);
        // Sample 41 out of 80 -> 39 samples before frame_end (39 / 16000 = 0.0024375s)
        let expected_onset = 1.005 - (39.0 / 16000.0);
        assert!((ev.onset_time_sec - expected_onset).abs() < 1e-6);

        // Refractory window suppresses immediate echo 10ms later
        let echo = det.process_frame(&click_frame, 1.015);
        assert!(!echo.is_click);
    }
}
