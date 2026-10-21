"""Unit tests for AI Metronome visual mode engine, PLL beat clock, and gesture detector."""

from ai_metronome.mode_engine import (
    GestureDetector,
    MetronomeMode,
    ModeEngine,
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


def test_mode_3_meter_4_4_green_on_1_silent_on_others():
    """Mode 3: 4/4 meter — Green on beat 1, NO LED on beats 2, 3, 4."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_4_4)

    # Beat 1: Green
    b1 = engine.on_click(now=1.0, ioi=0.5)
    assert len(b1) == 1
    assert b1[0].color == "GREEN"
    assert b1[0].beat_num == 1

    # Beat 2: Silent
    b2 = engine.on_click(now=1.5, ioi=0.5)
    assert len(b2) == 0

    # Beat 3: Silent
    b3 = engine.on_click(now=2.0, ioi=0.5)
    assert len(b3) == 0

    # Beat 4: Silent
    b4 = engine.on_click(now=2.5, ioi=0.5)
    assert len(b4) == 0

    # Beat 1 (next measure): Green
    b1_next = engine.on_click(now=3.0, ioi=0.5)
    assert len(b1_next) == 1
    assert b1_next[0].color == "GREEN"
    assert b1_next[0].beat_num == 1


def test_mode_4_meter_3_4_green_on_1_silent_on_others():
    """Mode 4: 3/4 meter — Green on beat 1, NO LED on beats 2, 3."""
    engine = ModeEngine(initial_mode=MetronomeMode.METER_3_4)

    # Beat 1: Green
    b1 = engine.on_click(now=1.0, ioi=0.5)
    assert len(b1) == 1
    assert b1[0].color == "GREEN"
    assert b1[0].beat_num == 1

    # Beat 2: Silent
    b2 = engine.on_click(now=1.5, ioi=0.5)
    assert len(b2) == 0

    # Beat 3: Silent
    b3 = engine.on_click(now=2.0, ioi=0.5)
    assert len(b3) == 0

    # Beat 1 (next measure): Green
    b1_next = engine.on_click(now=2.5, ioi=0.5)
    assert len(b1_next) == 1
    assert b1_next[0].color == "GREEN"
    assert b1_next[0].beat_num == 1


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


def test_pll_internal_clock_fires_on_schedule_and_filters_jitter():
    """Verify internal PLL clock fires autonomously on time and avoids double-flashing when late click arrives."""
    engine = ModeEngine(initial_mode=MetronomeMode.ON_BEAT)

    # Click 1 at t=1.000s, Click 2 at t=1.500s -> locks PLL at period=0.500s (120 BPM)
    assert len(engine.on_click(now=1.000)) == 1
    assert len(engine.on_click(now=1.500)) == 1
    assert engine.is_locked is True
    assert abs(engine.period - 0.500) < 1e-6

    # Beat 3 is due at t=2.000s on the internal clock BEFORE the delayed click recognition at t=2.018s
    auto_flashes = engine.get_due_flashes(now=2.001)
    assert len(auto_flashes) == 1
    assert auto_flashes[0].color == "RED"
    assert abs(auto_flashes[0].target_time - 2.000) < 1e-6

    # Now the delayed click recognition arrives 18ms late at t=2.018s:
    # Should NOT double-flash, and should gently nudge phase & period rather than jumping +18ms
    late_click_flashes = engine.on_click(now=2.018)
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
