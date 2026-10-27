"""Unit tests for AI Metronome visual mode engine, PLL beat clock, and gesture detector."""

from ai_metronome.mode_engine import (
    BRIGHTNESS_DIM_METER,
    BRIGHTNESS_DIM_UNLOCKED,
    BRIGHTNESS_FULL,
    GestureDetector,
    MetronomeMode,
    ModeEngine,
    SleepWakeController,
)


def test_mode_cycling():
    """Verify cycling through all 4 modes wraps around cleanly."""
    engine = ModeEngine()
    assert engine.current_mode == MetronomeMode.ON_BEAT

    assert engine.cycle_mode() == MetronomeMode.UPBEAT
    assert engine.cycle_mode() == MetronomeMode.METER_4_4
    assert engine.cycle_mode() == MetronomeMode.METER_3_4
    assert engine.cycle_mode() == MetronomeMode.ON_BEAT


def test_mode_1_on_beat_flashes_red_every_click():
    """Mode 1: Flashes Red on every click immediately."""
    engine = ModeEngine(initial_mode=MetronomeMode.ON_BEAT)
    flashes = engine.on_click(now=10.0, ioi=0.5)
    assert len(flashes) == 1
    assert flashes[0].color == "RED"
    assert flashes[0].target_time == 10.0


def test_mode_2_upbeat_flashes_halfway_between_clicks():
    """Mode 2: Flashes Blue halfway between clicks (t + IOI / 2)."""
    engine = ModeEngine(initial_mode=MetronomeMode.UPBEAT)
    flashes = engine.on_click(now=10.0, ioi=0.5)
    assert len(flashes) == 0  # No flash immediately on the click

    # Upbeat should be scheduled at 10.25s (10.0 + 0.5 / 2)
    pending_early = engine.get_due_flashes(now=10.20)
    assert len(pending_early) == 0

    pending_due = engine.get_due_flashes(now=10.26)
    assert len(pending_due) == 1
    assert pending_due[0].color == "BLUE"
    assert pending_due[0].target_time == 10.25


def test_mode_3_meter_4_4_green_on_1_red_on_others():
    """Mode 3: 4/4 meter — Green on beat 1, Red on beats 2, 3, 4 (dimmed until locked, then bright Green / dim Red)."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_4_4)

    # Beat 1 (unlocked): Dimmed Green
    b1 = engine.on_click(now=1.0, ioi=0.5)
    assert len(b1) == 1
    assert b1[0].color == "GREEN"
    assert b1[0].beat_num == 1
    assert b1[0].brightness == BRIGHTNESS_DIM_UNLOCKED

    # Beat 2 (unlocked, 1st interval): Dimmed Red
    b2 = engine.on_click(now=1.5, ioi=0.5)
    assert len(b2) == 1
    assert b2[0].color == "RED"
    assert b2[0].beat_num == 2
    assert b2[0].brightness == BRIGHTNESS_DIM_UNLOCKED

    # Beat 3 (2nd consistent interval -> LOCKED!): Dimmed Red for weak beat
    b3 = engine.on_click(now=2.0, ioi=0.5)
    assert engine.is_locked is True
    assert len(b3) == 1
    assert b3[0].color == "RED"
    assert b3[0].beat_num == 3
    assert b3[0].brightness == BRIGHTNESS_DIM_METER

    # Beat 4 (locked): Dimmed Red for weak beat
    b4 = engine.on_click(now=2.5, ioi=0.5)
    assert len(b4) == 1
    assert b4[0].color == "RED"
    assert b4[0].beat_num == 4
    assert b4[0].brightness == BRIGHTNESS_DIM_METER

    # Beat 1 (next measure, locked): FULL BRIGHT Green to emphasize downbeat!
    b1_next = engine.on_click(now=3.0, ioi=0.5)
    assert len(b1_next) == 1
    assert b1_next[0].color == "GREEN"
    assert b1_next[0].beat_num == 1
    assert b1_next[0].brightness == BRIGHTNESS_FULL


def test_mode_4_meter_3_4_green_on_1_red_on_others():
    """Mode 4: 3/4 meter — Green on beat 1, Red on beats 2, 3 (dimmed until locked, then bright Green / dim Red)."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_3_4)

    # Beat 1 (unlocked): Dimmed Green
    b1 = engine.on_click(now=1.0, ioi=0.5)
    assert len(b1) == 1
    assert b1[0].color == "GREEN"
    assert b1[0].beat_num == 1
    assert b1[0].brightness == BRIGHTNESS_DIM_UNLOCKED

    # Beat 2 (unlocked): Dimmed Red
    b2 = engine.on_click(now=1.5, ioi=0.5)
    assert len(b2) == 1
    assert b2[0].color == "RED"
    assert b2[0].beat_num == 2
    assert b2[0].brightness == BRIGHTNESS_DIM_UNLOCKED

    # Beat 3 (locked): Dimmed Red for weak beat
    b3 = engine.on_click(now=2.0, ioi=0.5)
    assert engine.is_locked is True
    assert len(b3) == 1
    assert b3[0].color == "RED"
    assert b3[0].beat_num == 3
    assert b3[0].brightness == BRIGHTNESS_DIM_METER

    # Beat 1 (next measure, locked): FULL BRIGHT Green!
    b1_next = engine.on_click(now=2.5, ioi=0.5)
    assert len(b1_next) == 1
    assert b1_next[0].color == "GREEN"
    assert b1_next[0].beat_num == 1
    assert b1_next[0].brightness == BRIGHTNESS_FULL


def test_meter_resets_beat_count_after_pause():
    """Verify meter resets to beat 1 if clicks stop for longer than timeout."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_4_4, pause_reset_sec=2.0)
    engine.on_click(now=1.0, ioi=0.5)  # Beat 1
    engine.on_click(now=1.5, ioi=0.5)  # Beat 2

    # Pause 3 seconds
    after_pause = engine.on_click(now=4.5, ioi=0.5)
    assert len(after_pause) == 1
    assert after_pause[0].color == "GREEN"
    assert after_pause[0].beat_num == 1


def test_pll_continuous_freewheeling_and_resync_after_sound_pause():
    """Verify internal clock continues flashing indefinitely after sound stops and resyncs when clicks return."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_4_4)
    # Lock the PLL with 3 steady clicks at 120 BPM (0.5s period)
    engine.on_click(now=1.0, ioi=0.5)
    engine.on_click(now=1.5, ioi=0.5)
    engine.on_click(now=2.0, ioi=0.5)
    assert engine.is_locked is True

    # Clicks STOP completely! Freewheel for 10 beats (5.0s of silence)
    flashes = []
    t = 2.0
    for _ in range(10):
        t += 0.5
        flashes.extend(engine.get_due_flashes(now=t))
    assert len(flashes) == 10
    # Still locked and running at 120 BPM!
    assert engine.is_locked is True

    # Acoustic click resumes at t=7.3s (late click, start of new phrase)
    # Resync snaps phase and starts on Beat 1 (Green accent)
    resync_flashes = engine.on_click(now=7.3, ioi=0.5)
    assert len(resync_flashes) == 1
    assert resync_flashes[0].color == "GREEN"
    assert resync_flashes[0].beat_num == 1
    assert engine.is_locked is True


def test_pll_internal_clock_fires_on_schedule_and_filters_jitter():
    """Verify internal PLL clock dims until locked (3 clicks / 2 intervals), fires on schedule, and filters jitter."""
    engine = ModeEngine(initial_mode=MetronomeMode.ON_BEAT)

    # Click 1 at t=1.000s, Click 2 at t=1.500s -> still unlocked (dimmed), Click 3 at t=2.000s -> locks PLL (full bright)
    f1 = engine.on_click(now=1.000)
    assert len(f1) == 1 and f1[0].brightness == BRIGHTNESS_DIM_UNLOCKED
    assert engine.is_locked is False

    f2 = engine.on_click(now=1.500)
    assert len(f2) == 1 and f2[0].brightness == BRIGHTNESS_DIM_UNLOCKED
    assert engine.is_locked is False

    f3 = engine.on_click(now=2.000)
    assert len(f3) == 1 and f3[0].brightness == BRIGHTNESS_FULL
    assert engine.is_locked is True
    assert abs(engine.period - 0.500) < 1e-6

    # Beat 4 is due at t=2.500s on the internal clock BEFORE the delayed click recognition at t=2.518s
    auto_flashes = engine.get_due_flashes(now=2.501)
    assert len(auto_flashes) == 1
    assert auto_flashes[0].color == "RED"
    assert auto_flashes[0].brightness == BRIGHTNESS_FULL
    assert abs(auto_flashes[0].target_time - 2.500) < 1e-6

    # Now the delayed click recognition arrives 18ms late at t=2.518s:
    # Should NOT double-flash, and should gently nudge phase & period rather than jumping +18ms
    late_click_flashes = engine.on_click(now=2.518)
    assert len(late_click_flashes) == 0
    # Period should only shift by freq_gain * 0.018 (~4ms), staying very close to 0.504s
    assert 0.500 < engine.period < 0.506


def test_gesture_backed_off_sensitivity_ignores_minor_bumps_and_triggers_deliberate():
    """Verify minor 1.25g nudges are ignored while 2 deliberate ~1.55g shakes or a 2.4g drop trigger."""
    gd = GestureDetector()
    assert gd.update(0.0, 0.0, 1.0, now=1.0) == (False, "")

    # Minor bumps (~1.25g) should NOT trigger
    assert gd.update(0.2, 0.0, 1.23, now=1.20) == (False, "")
    assert gd.update(0.0, 0.0, 1.0, now=1.35) == (False, "")
    assert gd.update(-0.2, 0.0, 1.23, now=1.55) == (False, "")

    # Two deliberate slow shakes (~1.55g) trigger DOUBLE_SHAKE
    assert gd.update(0.5, 0.0, 1.48, now=2.00) == (False, "")
    assert gd.update(0.0, 0.0, 1.0, now=2.18) == (False, "")
    triggered, kind = gd.update(-0.5, 0.0, 1.48, now=2.40)
    assert triggered is True
    assert kind == "DOUBLE_SHAKE"

    # Firm drop to table (~2.45g) after debounce triggers HARD_DROP
    assert gd.update(0.0, 0.0, 1.0, now=3.50) == (False, "")
    triggered_drop, kind_drop = gd.update(0.0, 0.0, 2.45, now=3.55)
    assert triggered_drop is True
    assert kind_drop == "HARD_DROP"


def test_sleep_wake_controller_sleeps_on_inactivity_and_wakes_on_movement():
    """Verify device enters sleep after idle timeout and wakes when movement or INT1 occurs."""
    swc = SleepWakeController(idle_timeout_sec=30.0, motion_keepawake_g=0.08, wake_motion_g=0.12)

    # Initial check at t=10.0s initializes activity timestamp
    assert swc.check_motion_and_should_sleep(0.01, 0.01, now=10.0) is False
    assert swc.is_sleeping is False

    # Movement or click at t=25.0s keeps device awake
    swc.record_activity(now=25.0)
    assert swc.check_motion_and_should_sleep(0.01, 0.01, now=45.0) is False

    # Still stationary at t=55.5s (30.5s since last activity at 25.0s) -> enters sleep
    assert swc.check_motion_and_should_sleep(0.01, 0.01, now=55.5) is True
    assert swc.is_sleeping is True

    # Tiny sensor noise while sleeping does NOT wake
    assert swc.check_should_wake(0.02, 0.01, now=60.0) is False
    assert swc.is_sleeping is True

    # Picking up / nudging the board (dyn=0.18g >= 0.12g) wakes it up immediately
    assert swc.check_should_wake(0.18, 0.15, now=62.0) is True
    assert swc.is_sleeping is False
    assert swc.last_activity_time == 62.0
