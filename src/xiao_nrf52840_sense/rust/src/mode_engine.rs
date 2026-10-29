//! 4-Mode Autonomous Phase-Locked Loop (PLL) Beat Sequencer (`no_std`).
//!
//! Matches the Python `v2.6` `MetronomeModeEngine` 100%:
//! - Always starts in Mode 1 (`ON_BEAT`, Red) on reset.
//! - Modes:
//!   - Mode 1: On-Beat (`RED` on every beat).
//!   - Mode 2: In-Between / Upbeat (`BLUE` at `t_beat + 0.5 * period`).
//!   - Mode 3: 4/4 Meter (`GREEN` bright on Beat 1, `RED` dim on Beats 2, 3, 4).
//!   - Mode 4: 3/4 Meter (`GREEN` bright on Beat 1, `RED` dim on Beats 2, 3).
//! - Pre-lock dimming: All LEDs dimmed (`0.18`) until 2 consecutive consistent
//!   intervals (3 steady clicks) lock the PLL (`is_locked == true`).

pub const PRE_LOCK_BRIGHTNESS: f32 = 0.18;
pub const LOCKED_BRIGHTNESS: f32 = 1.00;
pub const WEAK_BEAT_RED_BRIGHTNESS: f32 = 0.20;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum MetronomeMode {
    Mode1OnBeat = 1,
    Mode2InBetween = 2,
    Mode3FourFour = 3,
    Mode4ThreeFour = 4,
}

impl MetronomeMode {
    pub const fn from_u8(val: u8) -> Self {
        match ((val.saturating_sub(1)) % 4) + 1 {
            1 => Self::Mode1OnBeat,
            2 => Self::Mode2InBetween,
            3 => Self::Mode3FourFour,
            _ => Self::Mode4ThreeFour,
        }
    }

    pub const fn next(self) -> Self {
        match self {
            Self::Mode1OnBeat => Self::Mode2InBetween,
            Self::Mode2InBetween => Self::Mode3FourFour,
            Self::Mode3FourFour => Self::Mode4ThreeFour,
            Self::Mode4ThreeFour => Self::Mode1OnBeat,
        }
    }

    pub const fn name(self) -> &'static str {
        match self {
            Self::Mode1OnBeat => "MODE_1_ON_BEAT (RED)",
            Self::Mode2InBetween => "MODE_2_IN_BETWEEN (BLUE UPBEAT)",
            Self::Mode3FourFour => "MODE_3_4_4 (GREEN=1, RED=2,3,4)",
            Self::Mode4ThreeFour => "MODE_4_3_4 (GREEN=1, RED=2,3)",
        }
    }

    pub const fn confirm_color(self) -> LedColor {
        match self {
            Self::Mode1OnBeat => LedColor::Red,
            Self::Mode2InBetween => LedColor::Blue,
            Self::Mode3FourFour => LedColor::Green,
            Self::Mode4ThreeFour => LedColor::Green,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LedColor {
    Off,
    Red,
    Green,
    Blue,
    White,
}

impl LedColor {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Off => "OFF",
            Self::Red => "RED",
            Self::Green => "GREEN",
            Self::Blue => "BLUE",
            Self::White => "WHITE",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FlashEvent {
    pub color: LedColor,
    pub mode: MetronomeMode,
    pub beat_in_bar: u8,
    pub bpm: f32,
    pub scheduled_time_sec: f64,
    pub is_upbeat: bool,
    pub brightness: f32,
    pub is_locked: bool,
}

#[derive(Debug, Clone)]
pub struct MetronomeModeEngine {
    pub mode: MetronomeMode,
    pub min_ioi_sec: f64,
    pub max_ioi_sec: f64,
    pub beat_period_sec: Option<f64>,
    pub last_click_time_sec: Option<f64>,
    pub beat_index: u32,
    pub is_locked: bool,
    locked_intervals: u8,
    next_beat_time_sec: Option<f64>,
    next_upbeat_time_sec: Option<f64>,
    last_fired_beat_time_sec: f64,
    pub coasted_beats: u8,
    pub max_coast_beats: u8,
    prev_dt_sec: Option<f64>,
}

impl Default for MetronomeModeEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl MetronomeModeEngine {
    pub const fn new() -> Self {
        Self {
            mode: MetronomeMode::Mode1OnBeat,
            min_ioi_sec: 0.18,
            max_ioi_sec: 2.00,
            beat_period_sec: None,
            last_click_time_sec: None,
            beat_index: 0,
            is_locked: false,
            locked_intervals: 0,
            next_beat_time_sec: None,
            next_upbeat_time_sec: None,
            last_fired_beat_time_sec: -10.0,
            coasted_beats: 0,
            max_coast_beats: 8,
            prev_dt_sec: None,
        }
    }

    #[inline]
    pub fn bpm(&self) -> f32 {
        match self.beat_period_sec {
            Some(p) if p > 0.0 => (60.0 / p) as f32,
            _ => 0.0,
        }
    }

    pub fn set_mode(&mut self, mode: MetronomeMode) -> MetronomeMode {
        self.mode = mode;
        self.beat_index = 0;
        if self.mode == MetronomeMode::Mode2InBetween {
            if let (Some(period), Some(next_beat)) = (self.beat_period_sec, self.next_beat_time_sec)
            {
                self.next_upbeat_time_sec = Some(next_beat - (period * 0.5));
            }
        } else {
            self.next_upbeat_time_sec = None;
        }
        self.mode
    }

    pub fn cycle_mode(&mut self) -> MetronomeMode {
        let next = self.mode.next();
        self.set_mode(next)
    }

    /// Cleanly reset the tempo, phase, and locked state to listen for a new pattern,
    /// while preserving the selected metronome mode.
    pub fn reset_pattern(&mut self) {
        self.beat_period_sec = None;
        self.last_click_time_sec = None;
        self.beat_index = 0;
        self.is_locked = false;
        self.locked_intervals = 0;
        self.next_beat_time_sec = None;
        self.next_upbeat_time_sec = None;
        self.last_fired_beat_time_sec = -10.0;
        self.coasted_beats = 0;
        self.prev_dt_sec = None;
    }

    /// Register a detected acoustic click at `click_time_sec`.
    /// Returns `Some(FlashEvent)` if an immediate visual flash should fire.
    pub fn register_click(&mut self, click_time_sec: f64) -> Option<FlashEvent> {
        let prev_click = self.last_click_time_sec;
        let mut ioi: Option<f64> = None;

        if let Some(prev) = prev_click {
            let delta = click_time_sec - prev;
            if delta < self.min_ioi_sec {
                return None;
            }
            if delta <= self.max_ioi_sec {
                ioi = Some(delta);
            } else {
                // Gap > 2.0s after sound stopped: clean reset and treat this click as fresh Beat 1!
                self.reset_pattern();
                self.last_click_time_sec = Some(click_time_sec);
                return self.fire_beat(click_time_sec);
            }
        }

        self.last_click_time_sec = Some(click_time_sec);
        self.coasted_beats = 0;

        if let Some(interval) = ioi {
            match self.beat_period_sec {
                None => {
                    self.beat_period_sec = Some(interval);
                    self.locked_intervals = 1;
                    self.is_locked = false;
                    self.prev_dt_sec = Some(interval);
                }
                Some(curr_period) => {
                    if (curr_period * 0.72..=curr_period * 1.38).contains(&interval) {
                        self.beat_period_sec = Some(0.65 * curr_period + 0.35 * interval);
                        self.locked_intervals = self.locked_intervals.saturating_add(1);
                        if self.locked_intervals >= 2 {
                            self.is_locked = true;
                        }
                    } else if let Some(prev_dt) = self.prev_dt_sec {
                        if (interval - prev_dt).abs() / prev_dt < 0.25 {
                            // Two consecutive consistent intervals at a new slower or faster tempo!
                            let new_period = 0.5 * (interval + prev_dt);
                            self.beat_period_sec = Some(new_period);
                            self.locked_intervals = 2;
                            self.is_locked = true;
                        } else {
                            // First interval of a potential tempo change -> adopt immediately so slowing down tracks
                            self.beat_period_sec = Some(interval);
                            self.beat_index = 0;
                            self.locked_intervals = 1;
                            self.is_locked = false;
                        }
                    } else {
                        // Tempo change -> adopt new interval
                        self.beat_period_sec = Some(interval);
                        self.beat_index = 0;
                        self.locked_intervals = 1;
                        self.is_locked = false;
                    }
                    self.prev_dt_sec = Some(interval);
                }
            }
        }

        // Check if our autonomous PLL already fired a beat flash within +/- 38% of this click
        let mut already_fired = false;
        if let Some(period) = self.beat_period_sec {
            if (click_time_sec - self.last_fired_beat_time_sec).abs() < (period * 0.38) {
                already_fired = true;
            }
        }

        let mut immediate_event: Option<FlashEvent> = None;
        if !already_fired {
            immediate_event = self.fire_beat(click_time_sec);
        }

        if let Some(period) = self.beat_period_sec {
            let next_beat = match self.next_beat_time_sec {
                Some(nb) => {
                    let predicted_this_beat = nb - period;
                    let phase_err = click_time_sec - predicted_this_beat;
                    if phase_err.abs() < period * 0.40 {
                        predicted_this_beat + (0.45 * phase_err) + period
                    } else {
                        click_time_sec + period
                    }
                }
                None => click_time_sec + period,
            };
            self.next_beat_time_sec = Some(next_beat);

            if self.mode == MetronomeMode::Mode2InBetween {
                self.next_upbeat_time_sec = Some(click_time_sec + (period * 0.5));
            } else {
                self.next_upbeat_time_sec = None;
            }
        }

        immediate_event
    }

    /// Advance the autonomous PLL clock to `now_sec` (continuous flywheel coasting).
    pub fn poll(&mut self, now_sec: f64) -> Option<FlashEvent> {
        let period = self.beat_period_sec?;

        // 1. Mode 2 upbeat check (`t_beat + period / 2`)
        if self.mode == MetronomeMode::Mode2InBetween {
            if let Some(upbeat_t) = self.next_upbeat_time_sec {
                if now_sec >= upbeat_t {
                    self.next_upbeat_time_sec = None;
                    // Guard against firing a stale upbeat if the user switched into Mode 2
                    // during the second half of a beat interval (`now_sec - upbeat_t > 0.25 * period`)
                    if (now_sec - upbeat_t) <= (period * 0.25) {
                        let brightness = if self.is_locked {
                            LOCKED_BRIGHTNESS
                        } else {
                            PRE_LOCK_BRIGHTNESS
                        };
                        return Some(FlashEvent {
                            color: LedColor::Blue,
                            mode: self.mode,
                            beat_in_bar: 1,
                            bpm: self.bpm(),
                            scheduled_time_sec: upbeat_t,
                            is_upbeat: true,
                            brightness,
                            is_locked: self.is_locked,
                        });
                    }
                }
            }
        }

        // 2. Autonomous beat clock check (flywheels through pauses, then times out to listening)
        let next_beat = self.next_beat_time_sec?;
        if now_sec >= next_beat {
            let event_time = next_beat;
            self.coasted_beats = self.coasted_beats.saturating_add(1);
            if self.coasted_beats > self.max_coast_beats {
                self.reset_pattern();
                return None;
            }
            self.next_beat_time_sec = Some(event_time + period);
            if self.mode == MetronomeMode::Mode2InBetween {
                self.next_upbeat_time_sec = Some(event_time + (period * 0.5));
            }
            return self.fire_beat(event_time);
        }

        None
    }

    fn fire_beat(&mut self, event_time_sec: f64) -> Option<FlashEvent> {
        self.last_fired_beat_time_sec = event_time_sec;
        let bpm = self.bpm();
        let locked = self.is_locked;
        let base_bright = if locked {
            LOCKED_BRIGHTNESS
        } else {
            PRE_LOCK_BRIGHTNESS
        };

        match self.mode {
            MetronomeMode::Mode1OnBeat => {
                self.beat_index = self.beat_index.wrapping_add(1);
                Some(FlashEvent {
                    color: LedColor::Red,
                    mode: self.mode,
                    beat_in_bar: 1,
                    bpm,
                    scheduled_time_sec: event_time_sec,
                    is_upbeat: false,
                    brightness: base_bright,
                    is_locked: locked,
                })
            }
            MetronomeMode::Mode2InBetween => {
                self.beat_index = self.beat_index.wrapping_add(1);
                let dim_blue_bright = if locked {
                    WEAK_BEAT_RED_BRIGHTNESS
                } else {
                    PRE_LOCK_BRIGHTNESS
                };
                Some(FlashEvent {
                    color: LedColor::Blue,
                    mode: self.mode,
                    beat_in_bar: 1,
                    bpm,
                    scheduled_time_sec: event_time_sec,
                    is_upbeat: false,
                    brightness: dim_blue_bright,
                    is_locked: locked,
                })
            }
            MetronomeMode::Mode3FourFour => {
                let beat_in_bar = ((self.beat_index % 4) + 1) as u8;
                self.beat_index = self.beat_index.wrapping_add(1);
                let (color, brightness) = if beat_in_bar == 1 {
                    (LedColor::Green, base_bright)
                } else {
                    let b = if locked {
                        WEAK_BEAT_RED_BRIGHTNESS
                    } else {
                        PRE_LOCK_BRIGHTNESS
                    };
                    (LedColor::Red, b)
                };
                Some(FlashEvent {
                    color,
                    mode: self.mode,
                    beat_in_bar,
                    bpm,
                    scheduled_time_sec: event_time_sec,
                    is_upbeat: false,
                    brightness,
                    is_locked: locked,
                })
            }
            MetronomeMode::Mode4ThreeFour => {
                let beat_in_bar = ((self.beat_index % 3) + 1) as u8;
                self.beat_index = self.beat_index.wrapping_add(1);
                let (color, brightness) = if beat_in_bar == 1 {
                    (LedColor::Green, base_bright)
                } else {
                    let b = if locked {
                        WEAK_BEAT_RED_BRIGHTNESS
                    } else {
                        PRE_LOCK_BRIGHTNESS
                    };
                    (LedColor::Red, b)
                };
                Some(FlashEvent {
                    color,
                    mode: self.mode,
                    beat_in_bar,
                    bpm,
                    scheduled_time_sec: event_time_sec,
                    is_upbeat: false,
                    brightness,
                    is_locked: locked,
                })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_starts_in_mode_1_and_dims_until_locked() {
        let mut eng = MetronomeModeEngine::new();
        assert_eq!(eng.mode, MetronomeMode::Mode1OnBeat);

        // Click 1 & 2: not locked yet -> PRE_LOCK_BRIGHTNESS (0.18)
        let ev1 = eng.register_click(1.0).unwrap();
        assert!(!ev1.is_locked);
        assert!((ev1.brightness - PRE_LOCK_BRIGHTNESS).abs() < 1e-5);

        let ev2 = eng.register_click(1.5).unwrap();
        assert!(!ev2.is_locked);
        assert!((ev2.brightness - PRE_LOCK_BRIGHTNESS).abs() < 1e-5);

        // Click 3 (2nd consistent 0.5s interval = 120 BPM) -> locks PLL!
        let ev3 = eng.register_click(2.0).unwrap();
        assert!(ev3.is_locked);
        assert!((ev3.brightness - LOCKED_BRIGHTNESS).abs() < 1e-5);
        assert!((eng.bpm() - 120.0).abs() < 1.0);
    }

    #[test]
    fn test_mode_3_and_4_dim_red_weak_beats_when_locked() {
        let mut eng = MetronomeModeEngine::new();
        eng.set_mode(MetronomeMode::Mode3FourFour);

        let _ = eng.register_click(1.0).unwrap(); // beat 1 (un-locked)
        let _ = eng.register_click(1.5).unwrap(); // beat 2 (un-locked)
        let ev3 = eng.register_click(2.0).unwrap(); // beat 3 (now locked, weak beat Red)
        assert!(ev3.is_locked);
        assert_eq!(ev3.beat_in_bar, 3);
        assert_eq!(ev3.color, LedColor::Red);
        assert!((ev3.brightness - WEAK_BEAT_RED_BRIGHTNESS).abs() < 1e-5);

        let _ = eng.register_click(2.5).unwrap(); // beat 4
        let ev5 = eng.register_click(3.0).unwrap(); // beat 1 of next bar (Green bright)
        assert_eq!(ev5.beat_in_bar, 1);
        assert_eq!(ev5.color, LedColor::Green);
        assert!((ev5.brightness - LOCKED_BRIGHTNESS).abs() < 1e-5);
    }

    #[test]
    fn test_continuous_flywheel_coasting_and_mode_switch_preserves_tempo() {
        let mut eng = MetronomeModeEngine::new();
        let _ = eng.register_click(1.0);
        let _ = eng.register_click(1.5);
        let _ = eng.register_click(2.0);
        assert!(eng.is_locked);
        assert!((eng.bpm() - 120.0).abs() < 1.0);

        // Coast for 6 beats (3.0 seconds) without any clicks -> stays locked and keeps firing!
        for i in 1..=6 {
            let t = 2.0 + (i as f64) * 0.5 + 0.001;
            let ev = eng.poll(t).expect("Flywheel should continue coasting");
            assert!(ev.is_locked);
            assert!((ev.bpm - 120.0).abs() < 1.0);
        }

        // Switch mode to Mode 3 (4/4) while coasting -> preserves tempo & lock!
        eng.set_mode(MetronomeMode::Mode3FourFour);
        assert!(eng.is_locked);
        let ev_m3 = eng.poll(5.501).expect("Mode 3 should immediately coast at same speed");
        assert_eq!(ev_m3.color, LedColor::Green);
        assert_eq!(ev_m3.beat_in_bar, 1);
    }

    #[test]
    fn test_tempo_deceleration_adapts_immediately() {
        let mut eng = MetronomeModeEngine::new();
        // Lock at 150 BPM (0.40s period)
        let _ = eng.register_click(1.0);
        let _ = eng.register_click(1.4);
        let _ = eng.register_click(1.8);
        assert!((eng.bpm() - 150.0).abs() < 1.0);

        //Suddenly slow down to 75 BPM (0.80s interval = 2x slower)
        let _ = eng.register_click(2.6);
        let ev_slow = eng.register_click(3.4).unwrap();
        assert!(ev_slow.is_locked);
        assert!((eng.bpm() - 75.0).abs() < 2.0);
    }

    #[test]
    fn test_mode_2_on_beat_dim_blue_vs_off_beat_accent() {
        let mut eng = MetronomeModeEngine::new();
        eng.set_mode(MetronomeMode::Mode2InBetween);

        let _ = eng.register_click(1.0).unwrap();
        let _ = eng.register_click(1.5).unwrap();
        let on_beat = eng.register_click(2.0).unwrap();
        assert!(on_beat.is_locked);
        assert!(!on_beat.is_upbeat);
        assert_eq!(on_beat.color, LedColor::Blue);
        assert!((on_beat.brightness - WEAK_BEAT_RED_BRIGHTNESS).abs() < 1e-5);

        let off_beat = eng.poll(2.251).expect("Mode 2 off-beat accent should fire halfway");
        assert!(off_beat.is_upbeat);
        assert_eq!(off_beat.color, LedColor::Blue);
        assert!((off_beat.brightness - LOCKED_BRIGHTNESS).abs() < 1e-5);
        assert!(off_beat.brightness > on_beat.brightness * 4.0);
    }

    #[test]
    fn test_reset_pattern_clears_tempo_and_lock_preserves_mode() {
        let mut eng = MetronomeModeEngine::new();
        eng.set_mode(MetronomeMode::Mode3FourFour);
        let _ = eng.register_click(1.0);
        let _ = eng.register_click(1.5);
        let _ = eng.register_click(2.0);
        assert!(eng.is_locked);
        assert_eq!(eng.mode, MetronomeMode::Mode3FourFour);
        assert!((eng.bpm() - 120.0).abs() < 1.0);

        eng.reset_pattern();
        assert_eq!(eng.mode, MetronomeMode::Mode3FourFour);
        assert!(!eng.is_locked);
        assert_eq!(eng.bpm(), 0.0);
        assert_eq!(eng.beat_period_sec, None);
        assert_eq!(eng.poll(2.5), None);
    }

    #[test]
    fn test_silence_gap_and_coasting_timeout_resets_to_listening() {
        let mut eng = MetronomeModeEngine::new();
        // 1. Lock at 120 BPM (0.50s period)
        let _ = eng.register_click(1.0);
        let _ = eng.register_click(1.5);
        let ev = eng.register_click(2.0).unwrap();
        assert!(ev.is_locked);
        assert!((eng.bpm() - 120.0).abs() < 1.0);

        // 2. Coast for 8 beats (up to 6.0s)
        for i in 1..=8 {
            let t = 2.0 + (i as f64) * 0.5 + 0.001;
            assert!(eng.poll(t).is_some());
        }
        // Beat 9 exceeds max_coast_beats (8) -> cleanly resets to listening!
        let t9 = 2.0 + 9.0 * 0.5 + 0.001;
        assert_eq!(eng.poll(t9), None);
        assert!(!eng.is_locked);
        assert_eq!(eng.beat_period_sec, None);

        // 3. Silence gap of 5 seconds, then new metronome starts at 80 BPM (0.75s)
        let _ = eng.register_click(12.0); // Beat 1
        assert!(!eng.is_locked);
        let _ = eng.register_click(12.75); // Beat 2
        let ev_locked = eng.register_click(13.50).unwrap(); // Beat 3
        assert!(ev_locked.is_locked);
        assert!((eng.bpm() - 80.0).abs() < 1.5);
    }
}
