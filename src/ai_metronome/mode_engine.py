"""Visual mode engine for AI Metronome.

Supports cycling through 5 visual flash modes:
1. ON_BEAT: Standard click synchronization (Red flash on every click).
2. UPBEAT: In-between click synchronization (Blue flash at t + IOI / 2).
3. DOUBLE_TIME: 2 flashes per click (Red on beat, Blue on upbeat).
4. METER_4_4: 4/4 meter accent (Green on beat 1, silent on beats 2, 3, 4).
5. METER_3_4: 3/4 meter accent (Green on beat 1, silent on beats 2, 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class MetronomeMode(IntEnum):
    """Metronome operational visual flash mode."""

    ON_BEAT = 1
    UPBEAT = 2
    DOUBLE_TIME = 3
    METER_4_4 = 4
    METER_3_4 = 5


MODE_NAMES: dict[MetronomeMode, str] = {
    MetronomeMode.ON_BEAT: "1: On Beat (1x)",
    MetronomeMode.UPBEAT: "2: In-Between / Upbeat (&)",
    MetronomeMode.DOUBLE_TIME: "3: Double Time (2x)",
    MetronomeMode.METER_4_4: "4: 4/4 Meter (Green on 1)",
    MetronomeMode.METER_3_4: "5: 3/4 Meter (Green on 1)",
}


@dataclass
class FlashEvent:
    """Scheduled or immediate LED flash event."""

    color: str
    target_time: float
    beat_num: int | None = None


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
        """Cycle to the next mode (1 -> 2 -> 3 -> 4 -> 5 -> 1)."""
        next_val = (self.current_mode.value % 5) + 1
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

        elif self.current_mode == MetronomeMode.DOUBLE_TIME:
            immediate_flashes.append(FlashEvent(color="RED", target_time=now, beat_num=self.beat_count))
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
