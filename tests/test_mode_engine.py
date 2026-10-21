"""Unit tests for AI Metronome visual mode engine and gesture detector."""

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


def test_gesture_two_slowish_shakes():
    """Verify 2 slowish shakes (~1.35g swings separated by 350ms) trigger DOUBLE_SHAKE."""
    gd = GestureDetector()
    # Resting on table
    assert gd.update(0.0, 0.0, 1.0, now=1.0) == (False, "")

    # First slow shake stroke (~1.35g)
    assert gd.update(0.4, 0.0, 1.3, now=1.20) == (False, "")
    # Return toward rest
    assert gd.update(0.0, 0.0, 1.0, now=1.35) == (False, "")
    # Second slow shake stroke (~1.35g) 350ms after first
    triggered, kind = gd.update(-0.4, 0.0, 1.3, now=1.55)
    assert triggered is True
    assert kind == "DOUBLE_SHAKE"


def test_gesture_harder_drop_to_table():
    """Verify a single firmer drop/tap to the table triggers HARD_DROP immediately."""
    gd = GestureDetector()
    assert gd.update(0.0, 0.0, 1.0, now=1.0) == (False, "")

    # Table drop impact (~2.0g)
    triggered, kind = gd.update(0.0, 0.0, 2.0, now=1.08)
    assert triggered is True
    assert kind == "HARD_DROP"
