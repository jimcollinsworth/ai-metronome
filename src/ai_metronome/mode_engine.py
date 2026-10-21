"""Visual mode engine, Phase-Locked Loop (PLL) beat clock, and gesture detector.

Supports cycling through 4 visual flash modes:
1. ON_BEAT: Standard click synchronization (Red flash on every beat).
2. UPBEAT: In-between click synchronization (Blue flash at t_beat + period / 2).
3. METER_4_4: 4/4 meter accent (Green on beat 1, silent on beats 2, 3, 4).
4. METER_3_4: 3/4 meter accent (Green on beat 1, silent on beats 2, 3).

Includes an autonomous internal Phase-Locked Loop (`BeatPLL`) oscillator that
drives LED flashing from a steady internal clock continuously phase- and
frequency-adjusted by recognized clicks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class MetronomeMode(IntEnum):
    """Metronome operational visual flash mode."""

    ON_BEAT = 1
    UPBEAT = 2
    METER_4_4 = 3
    METER_3_4 = 4


MODE_NAMES: dict[MetronomeMode, str] = {
    MetronomeMode.ON_BEAT: "1: On Beat (1x)",
    MetronomeMode.UPBEAT: "2: In-Between / Upbeat (&)",
    MetronomeMode.METER_4_4: "3: 4/4 Meter (Green on 1)",
    MetronomeMode.METER_3_4: "4: 3/4 Meter (Green on 1)",
}


@dataclass
class FlashEvent:
    """Scheduled or immediate LED flash event."""

    color: str
    target_time: float
    beat_num: int | None = None


class GestureDetector:
    """Detects either 2 deliberate slow shakes or 1 firm drop/tap to the table.

    Thresholds are tuned to avoid accidental triggers from normal handling or
    table vibrations while remaining easy to trigger intentionally.
    """

    def __init__(
        self,
        hard_drop_dyn_g: float = 1.35,
        hard_drop_jerk_g: float = 1.45,
        slow_shake_dyn_g: float = 0.48,
        slow_shake_release_g: float = 0.20,
        min_stroke_gap_sec: float = 0.15,
        shake_window_sec: float = 1.4,
        debounce_sec: float = 1.0,
    ) -> None:
        self.hard_drop_dyn_g = hard_drop_dyn_g
        self.hard_drop_jerk_g = hard_drop_jerk_g
        self.slow_shake_dyn_g = slow_shake_dyn_g
        self.slow_shake_release_g = slow_shake_release_g
        self.min_stroke_gap_sec = min_stroke_gap_sec
        self.shake_window_sec = shake_window_sec
        self.debounce_sec = debounce_sec

        self.prev_accel: tuple[float, float, float] | None = None
        self.in_stroke: bool = False
        self.last_trigger_time: float = -10.0
        self.shake_peaks: list[float] = []

    def update(self, ax_g: float, ay_g: float, az_g: float, now: float) -> tuple[bool, str]:
        """Process a 3-axis accelerometer reading in g's at timestamp `now`.

        Returns (triggered, gesture_type) where gesture_type is 'HARD_DROP', 'DOUBLE_SHAKE', or ''.
        """
        mag = (ax_g * ax_g + ay_g * ay_g + az_g * az_g) ** 0.5
        dyn = abs(mag - 1.0)

        if self.prev_accel is not None:
            px, py, pz = self.prev_accel
            dx = ax_g - px
            dy = ay_g - py
            dz = az_g - pz
            jerk = (dx * dx + dy * dy + dz * dz) ** 0.5
        else:
            jerk = 0.0

        self.prev_accel = (ax_g, ay_g, az_g)

        if (now - self.last_trigger_time) < self.debounce_sec:
            return False, ""

        # 1. Single firmer drop / knock to the table
        if dyn >= self.hard_drop_dyn_g or jerk >= self.hard_drop_jerk_g:
            self.last_trigger_time = now
            self.in_stroke = False
            self.shake_peaks.clear()
            return True, "HARD_DROP"

        # 2. Two deliberate slowish shakes within shake_window_sec (with hysteresis release)
        if dyn < self.slow_shake_release_g:
            self.in_stroke = False
        elif dyn >= self.slow_shake_dyn_g and not self.in_stroke:
            self.in_stroke = True
            self.shake_peaks = [t for t in self.shake_peaks if (now - t) <= self.shake_window_sec]
            if not self.shake_peaks or (now - self.shake_peaks[-1]) >= self.min_stroke_gap_sec:
                self.shake_peaks.append(now)
                if len(self.shake_peaks) >= 2:
                    self.last_trigger_time = now
                    self.in_stroke = False
                    self.shake_peaks.clear()
                    return True, "DOUBLE_SHAKE"

        return False, ""


class ModeEngine:
    """Autonomous Phase-Locked Loop (PLL) beat clock and 4-mode visual sequencer.

    Maintains an internal beat oscillator (`period`, `next_beat_time`) that fires
    LED flashes on a rock-steady internal schedule and smoothly adjusts phase and
    tempo as acoustic clicks are recognized.
    """

    def __init__(
        self,
        initial_mode: MetronomeMode = MetronomeMode.ON_BEAT,
        pause_reset_sec: float = 2.0,
        phase_gain: float = 0.35,
        freq_gain: float = 0.22,
        max_coast_beats: int = 3,
    ) -> None:
        self.current_mode: MetronomeMode = initial_mode
        self.pause_reset_sec: float = pause_reset_sec
        self.phase_gain: float = phase_gain
        self.freq_gain: float = freq_gain
        self.max_coast_beats: int = max_coast_beats

        self.last_click_time: float | None = None
        self.beat_count: int = 0
        self.period: float = 0.5
        self.is_locked: bool = False
        self.last_beat_time: float | None = None
        self.next_beat_time: float | None = None
        self.coasted_beats: int = 0
        self._scheduled_flashes: list[FlashEvent] = []

    @property
    def bpm(self) -> float | None:
        """Return the PLL-smoothed tempo in BPM once locked."""
        if not self.is_locked or self.period <= 0:
            return None
        return 60.0 / self.period

    def reset_clock(self) -> None:
        """Reset beat counter and unlock internal PLL oscillator."""
        self.beat_count = 0
        self.is_locked = False
        self.last_beat_time = None
        self.next_beat_time = None
        self.coasted_beats = 0
        self._scheduled_flashes.clear()

    def cycle_mode(self) -> MetronomeMode:
        """Cycle to the next mode (1 -> 2 -> 3 -> 4 -> 1)."""
        next_val = (self.current_mode.value % 4) + 1
        self.current_mode = MetronomeMode(next_val)
        self.reset_clock()
        return self.current_mode

    def _emit_beat(self, beat_time: float) -> list[FlashEvent]:
        """Advance meter beat counter and generate flash events for a beat at `beat_time`."""
        if self.current_mode == MetronomeMode.METER_4_4:
            self.beat_count = (self.beat_count % 4) + 1
        elif self.current_mode == MetronomeMode.METER_3_4:
            self.beat_count = (self.beat_count % 3) + 1
        else:
            self.beat_count = (self.beat_count % 4) + 1

        self.last_beat_time = beat_time
        immediate: list[FlashEvent] = []

        if self.current_mode == MetronomeMode.ON_BEAT:
            immediate.append(FlashEvent(color="RED", target_time=beat_time, beat_num=self.beat_count))

        elif self.current_mode == MetronomeMode.UPBEAT:
            if self.period > 0:
                self._scheduled_flashes.append(
                    FlashEvent(color="BLUE", target_time=beat_time + (self.period / 2.0), beat_num=self.beat_count)
                )

        elif self.current_mode in (MetronomeMode.METER_4_4, MetronomeMode.METER_3_4):
            if self.beat_count == 1:
                immediate.append(FlashEvent(color="GREEN", target_time=beat_time, beat_num=1))

        return immediate

    def on_click(self, now: float, ioi: float = 0.5) -> list[FlashEvent]:
        """Process a recognized audio click at timestamp `now` to lock/adjust the PLL clock.

        If the internal clock has not yet fired the current beat, fires it immediately;
        if the internal clock already fired this beat autonomously, adjusts the PLL phase
        and period without double-flashing.
        """
        # 1. Check for long pause reset
        if self.last_click_time is not None and (now - self.last_click_time) > self.pause_reset_sec:
            self.reset_clock()

        measured_dt = (now - self.last_click_time) if self.last_click_time is not None else None
        self.last_click_time = now
        self.coasted_beats = 0

        # 2. First click after silence: initialize beat 1 immediately
        if measured_dt is None:
            if ioi > 0:
                self.period = ioi
            return self._emit_beat(now)

        # 3. Second click (or unlocked state): acquire lock if interval is musical (30..300 BPM)
        if not self.is_locked:
            if 0.20 <= measured_dt <= 2.0:
                self.period = measured_dt
                self.is_locked = True
                flashes = self._emit_beat(now)
                self.next_beat_time = now + self.period
                return flashes
            if ioi > 0:
                self.period = ioi
            return self._emit_beat(now)

        # 4. Locked PLL state: compare click timestamp against internal clock beats
        # Check if the internal clock already fired this beat recently via get_due_flashes()
        if self.last_beat_time is not None and abs(now - self.last_beat_time) < (0.40 * self.period):
            phase_err = now - self.last_beat_time
            self._update_period_from_interval(measured_dt)
            corrected_beat = self.last_beat_time + (self.phase_gain * phase_err)
            self.last_beat_time = corrected_beat
            self.next_beat_time = corrected_beat + self.period
            # Do not emit a duplicate flash since the internal clock already fired this beat
            return []

        # Check if click aligns with the upcoming scheduled `next_beat_time`
        if self.next_beat_time is not None and abs(now - self.next_beat_time) < (0.40 * self.period):
            phase_err = now - self.next_beat_time
            self._update_period_from_interval(measured_dt)
            corrected_beat = self.next_beat_time + (self.phase_gain * phase_err)
            flashes = self._emit_beat(corrected_beat)
            self.next_beat_time = corrected_beat + self.period
            return flashes

        # Otherwise, tempo changed significantly: re-lock onto new interval
        if 0.20 <= measured_dt <= 2.0:
            self.period = measured_dt
        flashes = self._emit_beat(now)
        self.next_beat_time = now + self.period
        return flashes

    def _update_period_from_interval(self, measured_dt: float) -> None:
        """Smoothly adjust internal oscillator period from 1-beat or 2-beat click interval."""
        if not (0.20 <= measured_dt <= 3.0):
            return
        # Check if measured_dt is ~1 beat or ~2 beats (in case 1 click was missed)
        for mult in (1, 2):
            implied_period = measured_dt / mult
            if abs(implied_period - self.period) < (0.28 * self.period):
                self.period = (1.0 - self.freq_gain) * self.period + (self.freq_gain * implied_period)
                return

    def get_due_flashes(self, now: float) -> list[FlashEvent]:
        """Advance the autonomous internal beat clock and return any flashes due at or before `now`."""
        due: list[FlashEvent] = []

        # 1. Autonomous internal PLL beat generation
        if self.is_locked and self.next_beat_time is not None and now >= self.next_beat_time:
            # Check if clicks stopped completely (exceeded pause_reset_sec or max_coast_beats)
            if (
                self.last_click_time is not None
                and (now - self.last_click_time) > self.pause_reset_sec
            ) or self.coasted_beats >= self.max_coast_beats:
                self.reset_clock()
            else:
                beat_t = self.next_beat_time
                self.coasted_beats += 1
                self.next_beat_time = beat_t + self.period
                due.extend(self._emit_beat(beat_t))

        # 2. Scheduled upbeat flashes
        remaining: list[FlashEvent] = []
        for event in self._scheduled_flashes:
            if event.target_time <= now:
                due.append(event)
            else:
                remaining.append(event)
        self._scheduled_flashes = remaining
        return due
