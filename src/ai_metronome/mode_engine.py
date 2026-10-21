"""Visual mode engine and accelerometer gesture detector for AI Metronome.

Supports cycling through 4 visual flash modes:
1. ON_BEAT: Standard click synchronization (Red flash on every click).
2. UPBEAT: In-between click synchronization (Blue flash at t + IOI / 2).
3. METER_4_4: 4/4 meter accent (Green on beat 1, silent on beats 2, 3, 4).
4. METER_3_4: 3/4 meter accent (Green on beat 1, silent on beats 2, 3).
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
    """Detects either 2 slow shakes or 1 firm drop/tap to the table from 3-axis g values."""

    def __init__(
        self,
        hard_drop_dyn_g: float = 0.85,
        hard_drop_jerk_g: float = 0.90,
        slow_shake_dyn_g: float = 0.26,
        slow_shake_release_g: float = 0.14,
        min_stroke_gap_sec: float = 0.12,
        shake_window_sec: float = 1.6,
        debounce_sec: float = 0.8,
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

        # 1. Single harder drop / knock to the table
        if dyn >= self.hard_drop_dyn_g or jerk >= self.hard_drop_jerk_g:
            self.last_trigger_time = now
            self.in_stroke = False
            self.shake_peaks.clear()
            return True, "HARD_DROP"

        # 2. Two slowish shakes within shake_window_sec (with hysteresis release)
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
    """Manages visual flash modes, meter beat counting, and upbeat scheduling."""

    def __init__(
        self,
        initial_mode: MetronomeMode = MetronomeMode.ON_BEAT,
        pause_reset_sec: float = 2.0,
    ) -> None:
        self.current_mode: MetronomeMode = initial_mode
        self.pause_reset_sec: float = pause_reset_sec
        self.last_click_time: float | None = None
        self.beat_count: int = 0
        self._scheduled_flashes: list[FlashEvent] = []

    def cycle_mode(self) -> MetronomeMode:
        """Cycle to the next mode (1 -> 2 -> 3 -> 4 -> 1)."""
        next_val = (self.current_mode.value % 4) + 1
        self.current_mode = MetronomeMode(next_val)
        self.beat_count = 0
        self._scheduled_flashes.clear()
        return self.current_mode

    def on_click(self, now: float, ioi: float) -> list[FlashEvent]:
        """Process a detected audio click at timestamp `now` with estimated IOI.

        Returns any immediate flash events for this click.
        """
        # Reset meter counting if metronome paused
        if self.last_click_time is not None and (now - self.last_click_time) > self.pause_reset_sec:
            self.beat_count = 0
        self.last_click_time = now

        # Update meter beat counter
        if self.current_mode == MetronomeMode.METER_4_4:
            self.beat_count = (self.beat_count % 4) + 1
        elif self.current_mode == MetronomeMode.METER_3_4:
            self.beat_count = (self.beat_count % 3) + 1
        else:
            self.beat_count = (self.beat_count % 4) + 1

        immediate_flashes: list[FlashEvent] = []

        if self.current_mode == MetronomeMode.ON_BEAT:
            immediate_flashes.append(FlashEvent(color="RED", target_time=now, beat_num=self.beat_count))

        elif self.current_mode == MetronomeMode.UPBEAT:
            if ioi > 0:
                self._scheduled_flashes.append(
                    FlashEvent(color="BLUE", target_time=now + (ioi / 2.0))
                )

        elif self.current_mode in (MetronomeMode.METER_4_4, MetronomeMode.METER_3_4):
            if self.beat_count == 1:
                immediate_flashes.append(FlashEvent(color="GREEN", target_time=now, beat_num=1))

        return immediate_flashes

    def get_due_flashes(self, now: float) -> list[FlashEvent]:
        """Retrieve and dequeue any scheduled flashes that are due at or before `now`."""
        due: list[FlashEvent] = []
        remaining: list[FlashEvent] = []
        for event in self._scheduled_flashes:
            if event.target_time <= now:
                due.append(event)
            else:
                remaining.append(event)
        self._scheduled_flashes = remaining
        return due
