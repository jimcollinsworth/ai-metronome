//! IMU Dual-Gesture Classifier (`DOUBLE_SHAKE` + `HARD_DROP`) & 30s Inactivity `SleepWakeController`.
//!
//! Matches the Python `v2.6` `ShakeModeClassifier` and `SleepWakeController` 100%.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GestureKind {
    DoubleShake,
    HardDrop,
}

impl GestureKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::DoubleShake => "DOUBLE_SHAKE",
            Self::HardDrop => "HARD_DROP",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ImuUpdateResult {
    pub gesture: Option<GestureKind>,
    pub dyn_g: f32,
    pub jerk_g: f32,
}

#[derive(Debug, Clone)]
pub struct ShakeModeClassifier {
    pub shake_threshold_g: f32,
    pub shake_release_g: f32,
    pub required_shakes: u8,
    pub min_shake_gap_sec: f64,
    pub max_shake_gap_sec: f64,
    pub drop_dyn_threshold_g: f32,
    pub drop_jerk_threshold_g: f32,
    pub cooldown_sec: f64,
    last_trigger_sec: f64,
    shake_count: u8,
    last_shake_peak_sec: f64,
    in_peak: bool,
    prev_accel: Option<(f32, f32, f32)>,
}

impl Default for ShakeModeClassifier {
    fn default() -> Self {
        Self::new()
    }
}

impl ShakeModeClassifier {
    pub const fn new() -> Self {
        Self {
            shake_threshold_g: 0.48,
            shake_release_g: 0.20,
            required_shakes: 2,
            min_shake_gap_sec: 0.14,
            max_shake_gap_sec: 0.95,
            drop_dyn_threshold_g: 1.35,
            drop_jerk_threshold_g: 1.45,
            cooldown_sec: 1.50,
            last_trigger_sec: -10.0,
            shake_count: 0,
            last_shake_peak_sec: -10.0,
            in_peak: false,
            prev_accel: None,
        }
    }

    /// Suppress gestures until `now_sec + cooldown_sec` (used after waking from sleep).
    pub fn reset_after_wake(&mut self, now_sec: f64) {
        self.last_trigger_sec = now_sec;
        self.shake_count = 0;
        self.in_peak = false;
        self.prev_accel = None;
    }

    /// Process a 3-axis accelerometer reading `(ax_g, ay_g, az_g)` at `now_sec`.
    pub fn update(&mut self, ax_g: f32, ay_g: f32, az_g: f32, now_sec: f64) -> ImuUpdateResult {
        let mag = libm::sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
        let dyn_g = libm::fabsf(mag - 1.0);

        let jerk_g = match self.prev_accel {
            Some((px, py, pz)) => {
                let dx = ax_g - px;
                let dy = ay_g - py;
                let dz = az_g - pz;
                libm::sqrtf(dx * dx + dy * dy + dz * dz)
            }
            None => 0.0,
        };
        self.prev_accel = Some((ax_g, ay_g, az_g));

        // 1. Cooldown check
        if (now_sec - self.last_trigger_sec) < self.cooldown_sec {
            self.shake_count = 0;
            self.in_peak = false;
            return ImuUpdateResult {
                gesture: None,
                dyn_g,
                jerk_g,
            };
        }

        // 2. Path A: Single firm drop / tap to table
        if dyn_g >= self.drop_dyn_threshold_g || jerk_g >= self.drop_jerk_threshold_g {
            self.last_trigger_sec = now_sec;
            self.shake_count = 0;
            self.in_peak = false;
            return ImuUpdateResult {
                gesture: Some(GestureKind::HardDrop),
                dyn_g,
                jerk_g,
            };
        }

        // 3. Path B: 2 deliberate slowish shakes with hysteresis release
        if self.in_peak {
            if dyn_g < self.shake_release_g {
                self.in_peak = false;
            }
            return ImuUpdateResult {
                gesture: None,
                dyn_g,
                jerk_g,
            };
        }

        if self.shake_count > 0 && (now_sec - self.last_shake_peak_sec) > self.max_shake_gap_sec {
            self.shake_count = 0;
        }

        if dyn_g >= self.shake_threshold_g {
            let gap = now_sec - self.last_shake_peak_sec;
            if self.shake_count == 0 || gap >= self.min_shake_gap_sec {
                self.in_peak = true;
                self.shake_count = self.shake_count.saturating_add(1);
                self.last_shake_peak_sec = now_sec;

                if self.shake_count >= self.required_shakes {
                    self.last_trigger_sec = now_sec;
                    self.shake_count = 0;
                    self.in_peak = false;
                    return ImuUpdateResult {
                        gesture: Some(GestureKind::DoubleShake),
                        dyn_g,
                        jerk_g,
                    };
                }
            }
        }

        ImuUpdateResult {
            gesture: None,
            dyn_g,
            jerk_g,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SleepTransition {
    None,
    EnterSleep,
    WakeUp,
}

#[derive(Debug, Clone)]
pub struct SleepWakeController {
    pub inactivity_timeout_sec: f64,
    pub sleep_motion_threshold_g: f32,
    pub wake_motion_threshold_g: f32,
    pub is_sleeping: bool,
    pub last_activity_sec: f64,
}

impl Default for SleepWakeController {
    fn default() -> Self {
        Self::new()
    }
}

impl SleepWakeController {
    pub const fn new() -> Self {
        Self {
            inactivity_timeout_sec: 30.0,
            sleep_motion_threshold_g: 0.08,
            wake_motion_threshold_g: 0.28,
            is_sleeping: false,
            last_activity_sec: 0.0,
        }
    }

    pub fn notify_activity(&mut self, now_sec: f64) {
        self.last_activity_sec = now_sec;
    }

    pub fn idle_duration_sec(&self, now_sec: f64) -> f64 {
        (now_sec - self.last_activity_sec).max(0.0)
    }

    /// Evaluate motion `(dyn_g, jerk_g)` at `now_sec` and return any state transition.
    pub fn update_motion(&mut self, dyn_g: f32, jerk_g: f32, now_sec: f64) -> SleepTransition {
        if self.last_activity_sec <= 0.0 {
            self.last_activity_sec = now_sec;
        }

        if self.is_sleeping {
            // While sleeping, ONLY check jerk_g (actual dynamic inter-sample displacement).
            // Do NOT check dyn_g because static tilt or resting offset on a table can have |mag - 1.0| > 0.
            if jerk_g >= self.wake_motion_threshold_g {
                self.is_sleeping = false;
                self.last_activity_sec = now_sec;
                return SleepTransition::WakeUp;
            }
            return SleepTransition::None;
        }

        // Awake: reset inactivity timer if movement exceeds quiet threshold
        if dyn_g >= self.sleep_motion_threshold_g || jerk_g >= self.sleep_motion_threshold_g {
            self.last_activity_sec = now_sec;
            return SleepTransition::None;
        }

        if (now_sec - self.last_activity_sec) >= self.inactivity_timeout_sec {
            self.is_sleeping = true;
            return SleepTransition::EnterSleep;
        }

        SleepTransition::None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_double_shake_and_hard_drop() {
        let mut clf = ShakeModeClassifier::new();

        // Rest at 1g
        assert_eq!(clf.update(0.0, 0.0, 1.0, 1.00).gesture, None);

        // Shake 1 peak (1.65g -> dyn_g = 0.65g)
        assert_eq!(clf.update(0.0, 0.0, 1.65, 1.20).gesture, None);
        // Release back to 1.0g
        assert_eq!(clf.update(0.0, 0.0, 1.00, 1.35).gesture, None);
        // Shake 2 peak (1.70g -> triggers DoubleShake)
        assert_eq!(
            clf.update(0.0, 0.0, 1.70, 1.55).gesture,
            Some(GestureKind::DoubleShake)
        );

        // Wait past 1.5s cooldown, then test HardDrop (2.5g impact)
        assert_eq!(clf.update(0.0, 0.0, 1.00, 3.20).gesture, None);
        assert_eq!(
            clf.update(0.0, 0.0, 2.50, 3.30).gesture,
            Some(GestureKind::HardDrop)
        );
    }

    #[test]
    fn test_sleep_after_30s_and_wake_on_movement() {
        let mut sw = SleepWakeController::new();
        assert_eq!(sw.update_motion(0.01, 0.01, 10.0), SleepTransition::None);
        assert_eq!(sw.update_motion(0.01, 0.01, 39.9), SleepTransition::None);
        assert_eq!(
            sw.update_motion(0.01, 0.01, 40.1),
            SleepTransition::EnterSleep
        );
        assert!(sw.is_sleeping);

        // Slight resting noise doesn't wake
        assert_eq!(sw.update_motion(0.03, 0.05, 45.0), SleepTransition::None);

        // Picking up board (jerk_g = 0.35g) wakes it up!
        assert_eq!(sw.update_motion(0.20, 0.35, 46.0), SleepTransition::WakeUp);
        assert!(!sw.is_sleeping);
    }
}
