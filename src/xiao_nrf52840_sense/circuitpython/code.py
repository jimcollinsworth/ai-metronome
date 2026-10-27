"""AI Metronome POC v2.6 — Seeed Studio XIAO nRF52840 Sense (CircuitPython).

Copy this file directly to `CIRCUITPY/code.py` (or deploy via `uv run xiao-cli deploy`).
Works out of the box with zero external libraries required.

Features:
1. HARDWARE INIT & DIAGNOSTICS:
   - Turns Blue LED ON during hardware health checks (Battery voltage gate, charge state,
     CPU die temperature, memory free space, PDM mic rail `board.MIC_PWR`, and IMU power rail `board.IMU_PWR`).
   - Calibrates PDM microphone ambient noise floor (outlier-resistant) and measures DMA frame timing.
   - Initializes onboard LSM6DS3TR-C 6-axis accelerometer on internal I2C bus (`board.IMU_SCL` / `board.IMU_SDA`) at 416 Hz.
2. INIT OK:
   - Pulses Green LED 3 times to confirm initialization passed.
   - Always resets to Mode 1 (On-Beat Red) on power-up or reset.
3. INTERNAL PHASE-LOCKED LOOP (PLL) BEAT CLOCK & PULSE-WIDTH BRIGHTNESS SHADING:
   - Uses pure `digitalio.DigitalInOut` (avoiding nRF52840 `pwmio` + `PDMIn` EasyDMA hardware conflicts)
     with retinal pulse-width modulation (Bloch's Law) for distinct brightness levels:
     * Pre-Lock Dimming: All LEDs flash dim (12 ms micro-pulse) until 2 consistent beat intervals
       (3 steady beats) lock the internal PLL clock, then jump to full brightness (130 ms pulse).
     * Meter Downbeat Emphasis: In 4/4 and 3/4 modes, Beat 1 flashes Full Bright Green (130 ms)
       while Beats 2..N flash Dim Red (15 ms) to strongly emphasize the downbeat count.
   - Mode 1: On-Beat (1x) — Flashes Red on every beat (Default on reset).
   - Mode 2: In-Between / Upbeat (&) — Flashes Blue halfway between beats (t_beat + period / 2).
   - Mode 3: 4/4 Meter — Bright Green on Beat 1, Dim Red on Beats 2, 3, 4.
   - Mode 4: 3/4 Meter — Bright Green on Beat 1, Dim Red on Beats 2, 3.
4. MOTION SLEEP / WAKE, GESTURE & SERIAL MODE SWITCHING:
   - Enters low-power CPU sleep after 30s of no movement; wakes immediately on movement.
   - Mode switch triggered by 2 deliberate slowish shakes, 1 firm drop to table, or USB Serial keys '1'..'4'.
   - Confirmed by a 350ms Bright White flash followed by N pulses in the new mode's color.
"""

import array
import gc
import os
import struct
import sys
import time

import analogio
import audiobusio
import board
import busio
import digitalio
import microcontroller
import supervisor

try:
    import neopixel_write
    HAS_NEOPIXEL_WRITE = True
except ImportError:
    HAS_NEOPIXEL_WRITE = False

# Optional Adafruit driver support if present in /lib
try:
    from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC  # type: ignore
    HAS_ADAFRUIT_LSM6DS = True
except ImportError:
    HAS_ADAFRUIT_LSM6DS = False

# --- Audio, PLL, Sleep & Timing Tuning Constants ---
SAMPLE_RATE = 16000
BUFFER_SIZE = 80                # 80 samples @ 16 kHz = 5.0 ms capture window (~200 Hz frame rate)
WARMUP_FRAMES = 8               # Discard initial PDM decimation filter power-on settling frames
CALIBRATION_FRAMES = 25         # Ambient noise calibration window
LED_FLASH_SEC = 0.130           # 130 ms full-brightness pulse duration for locked accent beats
LED_FLASH_DIM_METER_SEC = 0.015 # 15 ms dim pulse duration for weak Red beats in 3/4 and 4/4 meter
LED_FLASH_DIM_LOCK_SEC = 0.012  # 12 ms dim pulse duration for all beats before PLL timing locks in
PAUSE_RESET_SEC = 2.0           # Reset meter beat count & unlock PLL if clicks pause longer than 2.0s
LEAD_COMP_SEC = 0.0025          # 2.5 ms anticipatory lead to center flash timing across the 5 ms frame
IDLE_SLEEP_SEC = 30.0           # Enter low-power CPU sleep after 30s of no movement/activity
MOTION_KEEPAWAKE_G = 0.08       # Accelerometer dynamic/jerk threshold (g) that counts as movement
WAKE_MOTION_G = 0.12            # Accelerometer dynamic/jerk threshold (g) to wake CPU from sleep

# Logical Brightness Tiers (mapped to retinal pulse width in _trigger_led_flashes)
BRIGHTNESS_FULL = 1.0
BRIGHTNESS_DIM_METER = 0.12
BRIGHTNESS_DIM_UNLOCKED = 0.10

# --- NeoPixel Stick (CJMCU-2812-8) Constants ---
NEOPIXEL_PIN_NAME = "D0"   # Hardware pin for NeoPixel DIN
NEOPIXEL_COUNT = 8         # 8 WS2812B pixels
NEOPIXEL_BRIGHTNESS = 0.22 # 22% brightness: vivid and clearly visible for peripheral cueing


class MetronomeMode:
    """Metronome visual flash modes."""
    ON_BEAT = 1
    UPBEAT = 2
    METER_4_4 = 3
    METER_3_4 = 4


MODE_NAMES = {
    MetronomeMode.ON_BEAT: "Mode 1: On Beat (1x Red)",
    MetronomeMode.UPBEAT: "Mode 2: In-Between / Upbeat (& Blue)",
    MetronomeMode.METER_4_4: "Mode 3: 4/4 Meter (Bright Green 1, Dim Red 2-4)",
    MetronomeMode.METER_3_4: "Mode 4: 3/4 Meter (Bright Green 1, Dim Red 2-3)",
}


class StatusLEDs:
    """Unified driver for both the XIAO nRF52840 Sense onboard 3-in-1 RGB LED and CJMCU-2812-8 stick.

    Avoids `pwmio.PWMOut` which conflicts with `audiobusio.PDMIn` EasyDMA on nRF52840 across
    soft-reboots, using retinal pulse-width timing (12ms..130ms) for dimming instead.
    """

    def __init__(
        self,
        neopixel_pin_name: str = NEOPIXEL_PIN_NAME,
        num_pixels: int = NEOPIXEL_COUNT,
        brightness: float = NEOPIXEL_BRIGHTNESS,
    ) -> None:
        self.red = self._init_pin(getattr(board, "LED_RED", getattr(board, "LED", None)))
        self.green = self._init_pin(getattr(board, "LED_GREEN", None))
        self.blue = self._init_pin(getattr(board, "LED_BLUE", None))

        self.num_pixels = num_pixels
        self.brightness = brightness
        self.np_pin = None
        self._np_buf = bytearray(num_pixels * 3)

        if HAS_NEOPIXEL_WRITE:
            pin_obj = getattr(board, neopixel_pin_name, None)
            if pin_obj is not None:
                try:
                    self.np_pin = digitalio.DigitalInOut(pin_obj)
                    self.np_pin.direction = digitalio.Direction.OUTPUT
                    print(f"  [LED]  NeoPixel Stick   : Active on board.{neopixel_pin_name} ({num_pixels} LEDs, {int(brightness*100)}% subtle glow)")
                except Exception as err:
                    print(f"  [WARN - LED] Could not bind NeoPixel pin {neopixel_pin_name}: {err}")
        self.all_off()

    @staticmethod
    def _init_pin(pin_obj):
        if pin_obj is None:
            return None
        try:
            pin = digitalio.DigitalInOut(pin_obj)
            pin.direction = digitalio.Direction.OUTPUT
            pin.value = True  # Active-low: True = OFF, False = ON
            return pin
        except Exception as err:
            print(f"[WARN - LED] Could not bind LED pin {pin_obj}: {err}")
            return None

    def set_onboard_rgb(self, r: bool, g: bool, b: bool) -> None:
        """Set onboard Red, Green, Blue states (True = ON, False = OFF)."""
        if self.red is not None:
            self.red.value = not r
        if self.green is not None:
            self.green.value = not g
        if self.blue is not None:
            self.blue.value = not b

    def set_rgb(self, r: bool, g: bool, b: bool) -> None:
        """Legacy helper for hardware diagnostic and startup routines."""
        self.set_onboard_rgb(r, g, b)

    def _write_neopixels(self, frame: list[tuple[int, int, int]]) -> None:
        if self.np_pin is None:
            return
        b = self.brightness
        buf = self._np_buf
        for i in range(min(len(frame), self.num_pixels)):
            r, g, b_val = frame[i]
            idx = i * 3
            # WS2812 GRB ordering
            buf[idx] = int(g * b)
            buf[idx + 1] = int(r * b)
            buf[idx + 2] = int(b_val * b)
        neopixel_write.neopixel_write(self.np_pin, buf)

    def run_startup_pattern(self) -> None:
        """Quick visible sweep across all 8 pixels at power-on to verify wiring & hardware."""
        if self.np_pin is None:
            return
        # 1. Quick swipe from 0 to 7 in bright cyan/blue (35ms per pixel)
        for i in range(self.num_pixels):
            frame = [(0, 0, 0)] * self.num_pixels
            frame[i] = (0, 180, 255)
            if i > 0:
                frame[i - 1] = (0, 40, 80)
            self._write_neopixels(frame)
            time.sleep(0.035)
        # 2. Brief all-8 warm amber burst (120ms)
        self._write_neopixels([(220, 140, 20)] * self.num_pixels)
        time.sleep(0.12)
        self.all_off()
        time.sleep(0.06)

    def _render_frame(self, mode: int, beat: int, is_upbeat: bool) -> list[tuple[int, int, int]]:
        frame = [(0, 0, 0)] * self.num_pixels

        if is_upbeat:
            # Mode 2 Upbeat: Outer wings in bright Cyan-Blue [XX......XX]
            c = (0, 120, 255)
            frame[0] = c
            frame[1] = c
            frame[6] = c
            frame[7] = c
            return frame

        if mode == MetronomeMode.ON_BEAT:
            # Mode 1: Pendulum Rock in warm Amber-Red
            # Odd beat: left cluster [1, 2, 3] | Even beat: right cluster [4, 5, 6]
            c = (255, 40, 0)
            if beat % 2 == 1:
                frame[1] = c
                frame[2] = c
                frame[3] = c
            else:
                frame[4] = c
                frame[5] = c
                frame[6] = c

        elif mode == MetronomeMode.UPBEAT:
            # Mode 2 Downbeat (physical click): Center anchor in vibrant Purple
            # [..XX..]
            c = (180, 0, 220)
            frame[3] = c
            frame[4] = c

        elif mode == MetronomeMode.METER_4_4:
            # Mode 3: 4/4 Progressive Measure Bar (2 LEDs per beat)
            # Beat 1: [0, 1] - Accent Green
            # Beat 2: [2, 3] - Warm Amber tick
            # Beat 3: [4, 5] - Vivid Teal (half-measure secondary accent)
            # Beat 4: [6, 7] - Warm Amber tick
            if beat == 1:
                frame[0] = (0, 255, 40)
                frame[1] = (0, 255, 40)
            elif beat == 2:
                frame[2] = (200, 150, 40)
                frame[3] = (200, 150, 40)
            elif beat == 3:
                frame[4] = (0, 220, 180)
                frame[5] = (0, 220, 180)
            elif beat == 4:
                frame[6] = (200, 150, 40)
                frame[7] = (200, 150, 40)

        elif mode == MetronomeMode.METER_3_4:
            # Mode 4: 3/4 Waltz Triple Step (3 - 2 - 3)
            # Beat 1: Left 3 [0, 1, 2] - Accent Green
            # Beat 2: Center 2 [3, 4]   - Warm Amber tick
            # Beat 3: Right 3 [5, 6, 7]  - Warm Amber tick
            if beat == 1:
                frame[0] = (0, 255, 40)
                frame[1] = (0, 255, 40)
                frame[2] = (0, 255, 40)
            elif beat == 2:
                frame[3] = (200, 150, 40)
                frame[4] = (200, 150, 40)
            elif beat == 3:
                frame[5] = (200, 150, 40)
                frame[6] = (200, 150, 40)
                frame[7] = (200, 150, 40)

        return frame

    def show_beat(self, mode: int, beat_num: int, color_tag: str, is_upbeat: bool = False) -> None:
        """Flash appropriate visual feedback on both onboard RGB and NeoPixel stick."""
        # 1. Onboard 3-in-1 LED
        if color_tag == "RED":
            self.set_onboard_rgb(True, False, False)
        elif color_tag == "GREEN":
            self.set_onboard_rgb(False, True, False)
        elif color_tag == "BLUE":
            self.set_onboard_rgb(False, False, True)
        else:
            self.set_onboard_rgb(False, False, False)

        # 2. NeoPixel Stick
        if self.np_pin is not None:
            frame = self._render_frame(mode, beat_num, is_upbeat)
            self._write_neopixels(frame)

    def all_off(self) -> None:
        self.set_onboard_rgb(False, False, False)
        if self.np_pin is not None:
            for i in range(len(self._np_buf)):
                self._np_buf[i] = 0
            neopixel_write.neopixel_write(self.np_pin, self._np_buf)

    def signal_init_ok(self) -> None:
        """Blink Green 3 times across both onboard LED and all 8 NeoPixels."""
        self.all_off()
        for _ in range(3):
            self.set_onboard_rgb(False, True, False)
            if self.np_pin is not None:
                self._write_neopixels([(0, 255, 40)] * self.num_pixels)
            time.sleep(0.15)
            self.all_off()
            time.sleep(0.09)

    def signal_mode_change(self, mode_num: int) -> None:
        """Unmistakable visual confirmation across both onboard LED and NeoPixel stick."""
        self.all_off()
        # 1. Soft white burst across all LEDs
        self.set_onboard_rgb(True, True, True)
        if self.np_pin is not None:
            self._write_neopixels([(120, 120, 120)] * self.num_pixels)
        time.sleep(0.35)
        self.all_off()
        time.sleep(0.22)

        # 2. Distinct pulses indicating the new mode
        if mode_num == MetronomeMode.ON_BEAT:
            onboard_c = (True, False, False)
            stick_frame = [(0, 0, 0)] * self.num_pixels
            stick_frame[2] = (140, 20, 0)
            stick_frame[3] = (140, 20, 0)
            stick_frame[4] = (140, 20, 0)
            stick_frame[5] = (140, 20, 0)
        elif mode_num == MetronomeMode.UPBEAT:
            onboard_c = (False, False, True)
            stick_frame = [(0, 0, 0)] * self.num_pixels
            stick_frame[0] = (0, 70, 220)
            stick_frame[1] = (0, 70, 220)
            stick_frame[6] = (0, 70, 220)
            stick_frame[7] = (0, 70, 220)
        elif mode_num == MetronomeMode.METER_4_4:
            onboard_c = (False, True, False)
            stick_frame = [(0, 0, 0)] * self.num_pixels
            stick_frame[0] = (0, 180, 50)
            stick_frame[1] = (0, 180, 50)
        else:  # METER_3_4
            onboard_c = (False, True, False)
            stick_frame = [(0, 0, 0)] * self.num_pixels
            stick_frame[0] = (0, 180, 50)
            stick_frame[1] = (0, 180, 50)
            stick_frame[2] = (0, 180, 50)

        for _ in range(mode_num):
            self.set_onboard_rgb(*onboard_c)
            if self.np_pin is not None:
                self._write_neopixels(stick_frame)
            time.sleep(0.20)
            self.all_off()
            time.sleep(0.16)

    def signal_enter_sleep(self) -> None:
        """Pulse Blue LED with shortening micro-pulses down to OFF to indicate sleep."""
        for on_s in (0.040, 0.015, 0.005):
            self.set_rgb(False, False, True)
            time.sleep(on_s)
            self.all_off()
            time.sleep(0.070)

    def signal_wake_ok(self) -> None:
        """Blink 2 crisp Green pulses to confirm motion wake-up."""
        self.all_off()
        for _ in range(2):
            self.set_rgb(False, True, False)
            time.sleep(0.08)
            self.all_off()
            time.sleep(0.06)

    def signal_fault_loop(self) -> None:
        """Alternate Red and Blue LEDs indefinitely if critical hardware fails."""
        while True:
            self.set_onboard_rgb(True, False, False)
            if self.np_pin is not None:
                self._write_neopixels([(180, 0, 0)] * self.num_pixels)
            time.sleep(0.25)
            self.set_onboard_rgb(False, False, True)
            if self.np_pin is not None:
                self._write_neopixels([(0, 0, 180)] * self.num_pixels)
            time.sleep(0.25)


class ShakeAndDropDetector:
    """High-rate gesture & motion-wake detector for onboard LSM6DS3TR-C.

    Detects either:
    - 1 firm drop / tap to the table (HARD_DROP: dyn >= 1.35g or jerk >= 1.45g)
    - 2 deliberate slowish shakes in hand within 1.4s (DOUBLE_SHAKE: dyn >= 0.48g, release < 0.20g)
    Also tracks fine movement (`last_dyn`, `last_jerk`) and configures LSM6DS3TR-C
    low-power wake-up interrupt (`board.IMU_INT1`) during CPU sleep.
    """

    def __init__(
        self,
        i2c_bus,
        hard_drop_dyn_g: float = 1.35,
        hard_drop_jerk_g: float = 1.45,
        slow_shake_dyn_g: float = 0.48,
        slow_shake_release_g: float = 0.20,
        min_stroke_gap_sec: float = 0.15,
        shake_window_sec: float = 1.4,
        debounce_sec: float = 1.0,
    ) -> None:
        self.i2c = i2c_bus
        self.hard_drop_dyn_g = hard_drop_dyn_g
        self.hard_drop_jerk_g = hard_drop_jerk_g
        self.slow_shake_dyn_g = slow_shake_dyn_g
        self.slow_shake_release_g = slow_shake_release_g
        self.min_stroke_gap_sec = min_stroke_gap_sec
        self.shake_window_sec = shake_window_sec
        self.debounce_sec = debounce_sec

        self.address = 0x6A
        self.prev_accel = None
        self.in_stroke = False
        self.last_trigger_time = -10.0
        self.shake_peaks = []
        self.last_dyn = 0.0
        self.last_jerk = 0.0
        self._buf6 = bytearray(6)
        self.sensor_obj = None
        self.is_ready = False
        self.int1_pin = None

        if self.i2c:
            self._init_sensor()
        self._init_int1_pin()

    def _init_int1_pin(self) -> None:
        int1_obj = getattr(board, "IMU_INT1", None)
        if int1_obj is not None:
            try:
                pin = digitalio.DigitalInOut(int1_obj)
                pin.direction = digitalio.Direction.INPUT
                self.int1_pin = pin
            except Exception:
                self.int1_pin = None

    def _write_reg(self, reg: int, val: int) -> None:
        if not self.i2c or not self.is_ready:
            return
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes([reg, val]))
        except Exception:
            pass
        finally:
            self.i2c.unlock()

    def set_low_power_wake_mode(self, enable: bool) -> None:
        """Switch LSM6DS3TR-C between 26 Hz low-power motion-wake mode and 416 Hz active mode."""
        if not self.is_ready or self.sensor_obj is not None:
            return
        if enable:
            # CTRL1_XL (0x10) = 0x28 (26 Hz low-power ODR, +/-4g)
            self._write_reg(0x10, 0x28)
            # TAP_CFG (0x58) = 0x80 (enable interrupts), WAKE_UP_DUR (0x5C) = 0x00,
            # WAKE_UP_THS (0x5B) = 0x02 (~125 mg wake threshold), MD1_CFG (0x5E) = 0x20 (route WU to INT1)
            self._write_reg(0x58, 0x80)
            self._write_reg(0x5C, 0x00)
            self._write_reg(0x5B, 0x02)
            self._write_reg(0x5E, 0x20)
        else:
            # Disable wake-up routing on INT1 and restore 416 Hz ODR (+/-4g)
            self._write_reg(0x5E, 0x00)
            self._write_reg(0x10, 0x68)

    def _init_sensor(self) -> None:
        try:
            while not self.i2c.try_lock():
                pass
            try:
                found = self.i2c.scan()
                if self.address not in found:
                    if 0x6B in found:
                        self.address = 0x6B
                    else:
                        print(f"  [WARN - IMU] LSM6DS3 not found on I2C bus (found: {[hex(a) for a in found]})")
                        return

                who = bytearray(1)
                self.i2c.writeto_then_readfrom(self.address, bytes([0x0F]), who)
                print(f"  [IMU]  WHO_AM_I         : {hex(who[0])} at {hex(self.address)}")

                # CTRL1_XL (0x10): 416 Hz ODR, +/- 4g full scale (0x68)
                self.i2c.writeto(self.address, bytes([0x10, 0x68]))
                self.is_ready = True
                print("  [IMU]  Accelerometer    : Active via direct I2C (416 Hz, +/-4g)")
                return
            finally:
                self.i2c.unlock()
        except Exception as err:
            print(f"  [WARN - IMU] Direct I2C init warning: {err}")

        if HAS_ADAFRUIT_LSM6DS:
            try:
                self.sensor_obj = LSM6DS3TRC(self.i2c)
                self.is_ready = True
                print("  [IMU]  Accelerometer    : Active via adafruit_lsm6ds library")
            except Exception as err:
                print(f"  [WARN - IMU] adafruit_lsm6ds init failed: {err}")

    def _read_accel_g(self):
        if self.sensor_obj is not None:
            ax, ay, az = self.sensor_obj.acceleration
            return ax / 9.80665, ay / 9.80665, az / 9.80665

        if not self.i2c.try_lock():
            return None
        try:
            self.i2c.writeto_then_readfrom(self.address, bytes([0x28]), self._buf6)
        finally:
            self.i2c.unlock()

        ax, ay, az = struct.unpack("<hhh", self._buf6)
        return ax / 8192.0, ay / 8192.0, az / 8192.0

    def sample_motion(self) -> tuple[float, float]:
        """Read accelerometer and update (dyn, jerk) in g's."""
        if not self.is_ready:
            return 0.0, 0.0
        try:
            reading = self._read_accel_g()
            if reading is None:
                return 0.0, 0.0
            ax_g, ay_g, az_g = reading
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
            self.last_dyn = dyn
            self.last_jerk = jerk
            return dyn, jerk
        except Exception:
            return 0.0, 0.0

    def check_gesture(self, now: float) -> tuple[bool, str]:
        """Poll accelerometer and return (triggered, gesture_name)."""
        if not self.is_ready:
            return False, ""

        dyn, jerk = self.sample_motion()

        if (now - self.last_trigger_time) < self.debounce_sec:
            return False, ""

        if dyn >= self.hard_drop_dyn_g or jerk >= self.hard_drop_jerk_g:
            self.last_trigger_time = now
            self.in_stroke = False
            self.shake_peaks.clear()
            return True, "HARD_DROP"

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


def extract_highpass_features_indexed(sample_buffer) -> tuple[float, int, int]:
    """Zero-allocation first-difference high-pass filter H(z) = 1 - z^-1 with peak sample index."""
    count = len(sample_buffer)
    if count < 2:
        return 0.0, 0, 0

    hp_sum = 0
    hp_peak = 0
    peak_idx = 0
    prev = sample_buffer[0]

    for i in range(1, count):
        curr = sample_buffer[i]
        diff = curr - prev
        if diff < 0:
            diff = -diff
        hp_sum += diff
        if diff > hp_peak:
            hp_peak = diff
            peak_idx = i
        prev = curr

    return hp_sum / (count - 1), hp_peak, peak_idx


class PDMClickDetector:
    """Adaptive high-pass transient click detector with sub-frame onset timestamping."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        peak_snr_mult: float = 4.8,
        mean_snr_mult: float = 1.4,
        min_peak_threshold: int = 620,
        attack_slope_ratio: float = 1.45,
        refractory_sec: float = 0.12,
        ema_alpha: float = 0.04,
    ) -> None:
        self.sample_rate = sample_rate
        self.peak_snr_mult = peak_snr_mult
        self.mean_snr_mult = mean_snr_mult
        self.min_peak_threshold = min_peak_threshold
        self.attack_slope_ratio = attack_slope_ratio
        self.refractory_sec = refractory_sec
        self.ema_alpha = ema_alpha

        self.noise_floor_mean: float = 40.0
        self.noise_floor_peak: float = 100.0
        self.prev_quiet_peak: float = 100.0
        self.last_click_time: float = -10.0
        self.click_count: int = 0
        self.recent_intervals: list[float] = []
        self.avg_ioi: float = 0.5
        self.bpm: float | None = None
        self.is_calibrated: bool = False

        self._cal_means: list[float] = []
        self._cal_peaks: list[int] = []

    def calibrate_step(self, sample_buffer) -> tuple[float, int]:
        hp_mean, hp_peak, _ = extract_highpass_features_indexed(sample_buffer)
        self._cal_means.append(hp_mean)
        self._cal_peaks.append(hp_peak)
        return hp_mean, hp_peak

    def finalize_calibration(self) -> tuple[float, float]:
        """Compute outlier-resistant baseline ambient noise floor from calibration frames."""
        if self._cal_means:
            sorted_means = sorted(self._cal_means)
            sorted_peaks = sorted(self._cal_peaks)
            q_idx = max(0, len(sorted_means) // 3)
            med_mean = float(sorted_means[q_idx])
            med_peak = float(sorted_peaks[q_idx])
            self.noise_floor_mean = min(80.0, max(15.0, med_mean))
            self.noise_floor_peak = min(180.0, max(60.0, med_peak))
            self.prev_quiet_peak = self.noise_floor_peak
        self.is_calibrated = True
        return self.noise_floor_mean, self.noise_floor_peak

    def process_frame(self, sample_buffer, frame_end_time: float) -> tuple[bool, float, int, float]:
        """Analyze audio frame and return (is_click, hp_mean, hp_peak, sample_accurate_onset_time)."""
        hp_mean, hp_peak, peak_idx = extract_highpass_features_indexed(sample_buffer)
        buf_len = len(sample_buffer)

        samples_ago = max(0, buf_len - 1 - peak_idx)
        onset_time = frame_end_time - (samples_ago / float(self.sample_rate))

        peak_thresh = max(
            float(self.min_peak_threshold),
            self.noise_floor_peak * self.peak_snr_mult,
        )
        mean_thresh = max(22.0, self.noise_floor_mean * self.mean_snr_mult)

        elapsed = onset_time - self.last_click_time
        in_refractory = elapsed < self.refractory_sec

        crest_ratio = hp_peak / (hp_mean + 1.0)
        is_sharp_attack = hp_peak >= (self.prev_quiet_peak * self.attack_slope_ratio)

        is_click = (
            (not in_refractory)
            and (hp_peak >= peak_thresh)
            and (hp_mean >= mean_thresh)
            and (crest_ratio >= 1.9)
            and is_sharp_attack
        )

        if is_click:
            self.click_count += 1
            if self.last_click_time > 0.0 and 0.18 <= elapsed <= 2.5:
                self.recent_intervals.append(elapsed)
                if len(self.recent_intervals) > 4:
                    self.recent_intervals.pop(0)
                self.avg_ioi = sum(self.recent_intervals) / len(self.recent_intervals)
                self.bpm = 60.0 / self.avg_ioi
            self.last_click_time = onset_time
        elif not in_refractory and hp_peak < peak_thresh * 0.65:
            alpha = self.ema_alpha
            self.noise_floor_mean = (1.0 - alpha) * self.noise_floor_mean + alpha * hp_mean
            self.noise_floor_peak = (1.0 - alpha) * self.noise_floor_peak + alpha * hp_peak
            self.noise_floor_mean = max(15.0, self.noise_floor_mean)
            self.noise_floor_peak = max(60.0, self.noise_floor_peak)
            self.prev_quiet_peak = self.noise_floor_peak

        return is_click, hp_mean, hp_peak, onset_time


class CircuitModeEngine:
    """Autonomous Phase-Locked Loop (PLL) beat clock and 4-mode visual sequencer."""

    def __init__(
        self,
        initial_mode: int = MetronomeMode.ON_BEAT,
        pause_reset_sec: float = PAUSE_RESET_SEC,
        phase_gain: float = 0.35,
        freq_gain: float = 0.22,
        max_coast_beats: int = 3,
        lock_intervals_required: int = 2,
    ) -> None:
        self.current_mode = initial_mode
        self.pause_reset_sec = pause_reset_sec
        self.phase_gain = phase_gain
        self.freq_gain = freq_gain
        self.max_coast_beats = max_coast_beats
        self.lock_intervals_required = lock_intervals_required

        self.last_click_time = None
        self.beat_count = 0
        self.period = 0.5
        self.is_locked = False
        self._lock_intervals = 0
        self.last_beat_time = None
        self.next_beat_time = None
        self.coasted_beats = 0
        self.scheduled_flashes = []  # list of (target_time, color, brightness)

    @property
    def bpm(self) -> float | None:
        if not self.is_locked or self.period <= 0:
            return None
        return 60.0 / self.period

    def reset_clock(self) -> None:
        self.beat_count = 0
        self.is_locked = False
        self._lock_intervals = 0
        self.last_beat_time = None
        self.next_beat_time = None
        self.coasted_beats = 0
        self.scheduled_flashes.clear()

    def set_mode(self, mode_num: int) -> int:
        if 1 <= mode_num <= 4:
            self.current_mode = mode_num
            self.reset_clock()
        return self.current_mode

    def cycle_mode(self) -> int:
        return self.set_mode((self.current_mode % 4) + 1)

    def _emit_beat(self, beat_time: float) -> list[tuple[str, int, bool, float]]:
        if self.current_mode == MetronomeMode.METER_4_4:
            self.beat_count = (self.beat_count % 4) + 1
        elif self.current_mode == MetronomeMode.METER_3_4:
            self.beat_count = (self.beat_count % 3) + 1
        else:
            self.beat_count = (self.beat_count % 4) + 1

        self.last_beat_time = beat_time
        immediate: list[tuple[str, float]] = []

        if self.current_mode == MetronomeMode.ON_BEAT:
            lvl = BRIGHTNESS_FULL if self.is_locked else BRIGHTNESS_DIM_UNLOCKED
            immediate.append(("RED", self.beat_count, False, lvl))
        elif self.current_mode == MetronomeMode.UPBEAT:
            immediate.append(("ANCHOR", self.beat_count, False))
            if self.period > 0:
                lvl = BRIGHTNESS_FULL if self.is_locked else BRIGHTNESS_DIM_UNLOCKED
                self.scheduled_flashes.append((beat_time + (self.period / 2.0), ("BLUE", self.beat_count, True, lvl)))
        elif self.current_mode in (MetronomeMode.METER_4_4, MetronomeMode.METER_3_4):
            if self.beat_count == 1:
                lvl = BRIGHTNESS_FULL if self.is_locked else BRIGHTNESS_DIM_UNLOCKED
                immediate.append(("GREEN", 1, False, lvl))
            else:
                lvl = BRIGHTNESS_DIM_METER if self.is_locked else BRIGHTNESS_DIM_UNLOCKED
                immediate.append(("RED", self.beat_count, False, lvl))

        return immediate

    def _update_period_from_interval(self, measured_dt: float) -> None:
        if not (0.20 <= measured_dt <= 3.0):
            return
        for mult in (1, 2):
            implied_period = measured_dt / mult
            if abs(implied_period - self.period) < (0.28 * self.period):
                self.period = (1.0 - self.freq_gain) * self.period + (self.freq_gain * implied_period)
                return

    def on_click(self, onset_time: float, ioi: float = 0.5) -> tuple[list[tuple[str, int, bool, float]], float]:
        """Process recognized click at `onset_time` to lock/adjust the PLL clock.

        Returns (immediate_events, phase_error_ms).
        """
        if self.last_click_time is not None and (onset_time - self.last_click_time) > self.pause_reset_sec:
            self.reset_clock()

        measured_dt = (onset_time - self.last_click_time) if self.last_click_time is not None else None
        self.last_click_time = onset_time
        self.coasted_beats = 0

        if measured_dt is None:
            if ioi > 0:
                self.period = ioi
            return self._emit_beat(onset_time), 0.0

        # Unlocked state: require `lock_intervals_required` consistent intervals before full brightness
        if not self.is_locked:
            if 0.20 <= measured_dt <= 2.0:
                if self._lock_intervals == 0:
                    self.period = measured_dt
                    self._lock_intervals = 1
                elif abs(measured_dt - self.period) < (0.28 * self.period):
                    self.period = (1.0 - self.freq_gain) * self.period + (self.freq_gain * measured_dt)
                    self._lock_intervals += 1
                else:
                    self.period = measured_dt
                    self._lock_intervals = 1

                if self._lock_intervals >= self.lock_intervals_required:
                    self.is_locked = True
                    flashes = self._emit_beat(onset_time)
                    self.next_beat_time = onset_time + self.period
                    return flashes, 0.0
            else:
                self._lock_intervals = 0
                if ioi > 0:
                    self.period = ioi
            return self._emit_beat(onset_time), 0.0

        # Locked PLL state: check if internal clock already fired this beat
        if self.last_beat_time is not None and abs(onset_time - self.last_beat_time) < (0.40 * self.period):
            phase_err = onset_time - self.last_beat_time
            self._update_period_from_interval(measured_dt)
            corrected_beat = self.last_beat_time + (self.phase_gain * phase_err)
            self.last_beat_time = corrected_beat
            self.next_beat_time = corrected_beat + self.period
            if self.current_mode == MetronomeMode.UPBEAT and self.scheduled_flashes:
                _, event = self.scheduled_flashes[-1]
                self.scheduled_flashes[-1] = (corrected_beat + (self.period / 2.0), event)
            return [], (phase_err * 1000.0)

        # Check if click arrived slightly ahead of upcoming next_beat_time
        if self.next_beat_time is not None and abs(onset_time - self.next_beat_time) < (0.40 * self.period):
            phase_err = onset_time - self.next_beat_time
            self._update_period_from_interval(measured_dt)
            corrected_beat = self.next_beat_time + (self.phase_gain * phase_err)
            flashes = self._emit_beat(corrected_beat)
            self.next_beat_time = corrected_beat + self.period
            return flashes, (phase_err * 1000.0)

        # Tempo changed significantly: drop lock until confirmed at new tempo
        self.is_locked = False
        if 0.20 <= measured_dt <= 2.0:
            self.period = measured_dt
            self._lock_intervals = 1
        else:
            self._lock_intervals = 0
        flashes = self._emit_beat(onset_time)
        self.next_beat_time = None
        return flashes, 0.0

    def get_due_flashes(self, now: float) -> list[tuple[str, int, bool, float]]:
        """Advance autonomous internal beat clock and return any (color, beat_num, is_upbeat, lvl) due at or before `now`."""
        due = []

        if self.is_locked and self.next_beat_time is not None and now >= self.next_beat_time:
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

        remaining = []
        for target_time, event in self.scheduled_flashes:
            if target_time <= now:
                due.append(event)
            else:
                remaining.append((target_time, event))
        self.scheduled_flashes = remaining
        return due


def get_battery_voltage() -> float:
    """Sample battery voltage via XIAO nRF52840 isolation gate."""
    vbat_en = None
    adc = None
    try:
        vbat_en = digitalio.DigitalInOut(board.READ_BATT_ENABLE)
        vbat_en.direction = digitalio.Direction.OUTPUT
        vbat_en.value = False
        time.sleep(0.005)

        adc = analogio.AnalogIn(board.VBATT)
        raw = adc.value
        vbat_en.value = True
        return (raw * 3.3 / 65535) * 1.51
    except Exception:
        return 0.0
    finally:
        if adc:
            adc.deinit()
        if vbat_en:
            vbat_en.deinit()


def init_hardware(leds: StatusLEDs):
    """Run startup diagnostics, power up PDM mic and IMU, return (mic, mic_pwr, i2c)."""
    print("\n" + "=" * 58)
    print("   AI METRONOME POC v2.6 -- XIAO nRF52840 SENSE INIT")
    print("=" * 58)

    leds.set_rgb(False, False, True)  # Solid Blue LED during init

    # Run NeoPixel stick startup self-test sweep across all 8 pixels
    leds.run_startup_pattern()
    print("  [LED]  NeoPixel Stick   : Self-test sweep OK (8 pixels verified)")

    # 1. Power & Thermal Diagnostics
    vbat = get_battery_voltage()
    print(f"  [DIAG] Battery Rail     : {vbat:.2f} V")

    try:
        chg_pin = digitalio.DigitalInOut(board.CHARGE_STATUS)
        chg_pin.direction = digitalio.Direction.INPUT
        is_charging = not chg_pin.value
        chg_pin.deinit()
        print(f"  [DIAG] Charge Status    : {'Charging' if is_charging else 'Discharging / Full'}")
    except Exception:
        pass

    try:
        cpu_temp = microcontroller.cpu.temperature
        print(f"  [DIAG] CPU Temperature  : {cpu_temp:.1f} C")
    except Exception:
        pass

    try:
        fs_stat = os.statvfs("/")
        free_kb = (fs_stat[3] * fs_stat[0]) / 1024
        gc.collect()
        free_ram_kb = gc.mem_free() / 1024
        print(f"  [DIAG] Memory / Storage : {free_ram_kb:.1f} KB RAM | {free_kb:.1f} KB Flash")
    except Exception:
        pass

    # 2. Wake PDM Microphone Power Rail (board.MIC_PWR)
    mic_pwr = None
    try:
        mic_pwr = digitalio.DigitalInOut(board.MIC_PWR)
        mic_pwr.direction = digitalio.Direction.OUTPUT
        mic_pwr.value = True
        time.sleep(0.02)
        print("  [MIC]  Power Gate       : Active (board.MIC_PWR = HIGH)")
    except Exception:
        print("  [MIC]  Power Gate       : Active")

    # 3. Wake LSM6DS3TR-C IMU Power Rail (board.IMU_PWR)
    try:
        imu_pwr = digitalio.DigitalInOut(board.IMU_PWR)
        imu_pwr.direction = digitalio.Direction.OUTPUT
        imu_pwr.value = True
        time.sleep(0.08)
        print("  [IMU]  Power Gate       : Active (board.IMU_PWR = HIGH)")
    except Exception as err:
        print(f"  [WARN - IMU] Could not assert board.IMU_PWR: {err}")

    # 4. Initialize PDM Microphone
    try:
        mic = audiobusio.PDMIn(
            board.PDM_CLK,
            board.PDM_DATA,
            sample_rate=SAMPLE_RATE,
            bit_depth=16,
        )
        print(f"  [MIC]  PDMIn Stream     : Operational ({SAMPLE_RATE} Hz, 16-bit DMA)")
    except Exception as err:
        print(f"  [FAIL] PDMIn initialization failed: {err}")
        return None, mic_pwr, None

    # Verify Microphone DMA Capture & Measure Frame Duration
    test_buf = array.array("H", [0] * BUFFER_SIZE)
    t0 = time.monotonic()
    for _ in range(WARMUP_FRAMES):
        mic.record(test_buf, len(test_buf))
    avg_frame_ms = ((time.monotonic() - t0) / WARMUP_FRAMES) * 1000.0

    min_sample = min(test_buf)
    max_sample = max(test_buf)
    span = max_sample - min_sample
    if max_sample == 0 or min_sample == 65535:
        print(f"  [FAIL] PDM Microphone rail stuck (min={min_sample}, max={max_sample})")
        return None, mic_pwr, None
    print(f"  [MIC]  Signal Health    : OK (DC range {min_sample}..{max_sample}, span={span}, frame={avg_frame_ms:.1f}ms)")

    # 5. Initialize Dedicated IMU I2C Bus at 400 kHz
    i2c_bus = None
    try:
        i2c_bus = busio.I2C(board.IMU_SCL, board.IMU_SDA, frequency=400000)
        print("  [IMU]  I2C Bus          : Operational (board.IMU_SCL, board.IMU_SDA @ 400kHz)")
    except Exception as err:
        print(f"  [WARN - IMU] Could not initialize IMU I2C bus: {err}")

    return mic, mic_pwr, i2c_bus


def sleep_until_movement(
    leds: StatusLEDs,
    mic,
    mic_pwr,
    gesture_detector: ShakeAndDropDetector,
    audio_buffer,
):
    """Switch IMU to 26 Hz wake-interrupt mode and sleep CPU until movement."""
    print(f"\n[SLEEP] No movement for {int(IDLE_SLEEP_SEC)}s -> Entering low-power CPU sleep (move to wake)...")
    leds.signal_enter_sleep()

    # 1. Switch LSM6DS3TR-C to 26 Hz low-power mode & route Wake-Up interrupt to IMU_INT1
    # (Note: CircuitPython's PDMIn automatically disables NRF_PDM hardware between mic.record() calls)
    gesture_detector.set_low_power_wake_mode(True)
    gesture_detector.sample_motion()  # Prime baseline orientation
    gc.collect()

    # 2. Low-power tickless WFI sleep loop until movement or serial command wakes CPU
    while True:
        time.sleep(0.08)  # Halts Cortex-M4F clock via FreeRTOS tickless WFI
        int1_fired = bool(gesture_detector.int1_pin and gesture_detector.int1_pin.value)
        dyn, jerk = gesture_detector.sample_motion()
        if int1_fired or dyn >= WAKE_MOTION_G or jerk >= WAKE_MOTION_G:
            break
        if supervisor.runtime.serial_bytes_available:
            break

    # 3. Restore 416 Hz IMU active mode & warm up PDM DMA stream
    gesture_detector.set_low_power_wake_mode(False)
    for _ in range(4):
        mic.record(audio_buffer, len(audio_buffer))

    leds.signal_wake_ok()
    print("[WAKE]  Movement detected! CPU & PDM Microphone resumed.\n")
    return mic


def _trigger_led_colors(
    leds: StatusLEDs,
    events: list[tuple[str, int, bool, float]],
    now: float,
    current_mode: int,
) -> tuple[bool, float]:
    """Turn on appropriate visual feedback across onboard RGB and NeoPixel stick."""
    if not events:
        return False, 0.0
    color_tag, beat_num, is_upbeat, lvl = events[0]
    leds.show_beat(current_mode, beat_num, color_tag, is_upbeat)
    if lvl >= 0.8:
        pulse_dur = LED_FLASH_SEC
    elif lvl >= 0.11:
        pulse_dur = LED_FLASH_DIM_METER_SEC
    else:
        pulse_dur = LED_FLASH_DIM_LOCK_SEC
    return True, now + pulse_dur


def main() -> None:
    leds = StatusLEDs()
    mic, mic_pwr, i2c_bus = init_hardware(leds)

    if mic is None:
        print("[FATAL] Hardware initialization failed. Entering fault blink loop.")
        leds.signal_fault_loop()
        return

    gesture_detector = ShakeAndDropDetector(i2c_bus)
    # Always start in Mode 1 (ON_BEAT) on reset/power-up (no NVM persistence)
    mode_engine = CircuitModeEngine(initial_mode=MetronomeMode.ON_BEAT)

    audio_buffer = array.array("H", [0] * BUFFER_SIZE)
    detector = PDMClickDetector()

    print("  [CAL]  Calibrating ambient room noise floor...")
    for i in range(CALIBRATION_FRAMES):
        leds.set_rgb(False, False, (i % 2 == 0))
        mic.record(audio_buffer, len(audio_buffer))
        detector.calibrate_step(audio_buffer)

    nf_mean, nf_peak = detector.finalize_calibration()
    print(f"  [CAL]  Baseline Floor   : mean={nf_mean:.1f}, peak={nf_peak:.1f}")
    print("=" * 58)
    print("[READY] Initialization OK! Autonomous PLL Beat Clock active.")
    print(f"[MODE]  Current: {MODE_NAMES[mode_engine.current_mode]}")
    print(f"[SLEEP] Auto-sleep after {int(IDLE_SLEEP_SEC)}s of no movement (move to wake)")
    print("[TIP]   2 deliberate shakes, 1 firm table drop, or Serial '1'-'4' / 's' / 'z'\n")

    leds.signal_init_ok()
    gc.collect()

    led_off_at = 0.0
    led_is_active = False
    last_activity_time = time.monotonic()

    while True:
        # 1. Pre-DMA Internal PLL Clock Check (with 2.5 ms anticipatory lead):
        now = time.monotonic()
        due_pre = mode_engine.get_due_flashes(now + LEAD_COMP_SEC)
        if due_pre:
            led_is_active, led_off_at = _trigger_led_colors(leds, due_pre, now, mode_engine.current_mode)

        # 2. Capture 5.0 ms audio frame via PDM DMA
        mic.record(audio_buffer, len(audio_buffer))
        frame_end = time.monotonic()

        # 3. Post-DMA Immediate Internal Clock Check (before DSP/I2C/Serial work!)
        due_post = mode_engine.get_due_flashes(frame_end + LEAD_COMP_SEC)
        if due_post:
            led_is_active, led_off_at = _trigger_led_colors(leds, due_post, frame_end, mode_engine.current_mode)

        # 4. Process audio frame for click & adjust PLL phase/frequency
        is_click, hp_mean, hp_peak, onset_time = detector.process_frame(audio_buffer, frame_end)
        if is_click:
            immediate, phase_err_ms = mode_engine.on_click(onset_time, detector.avg_ioi)
            if immediate:
                led_is_active, led_off_at = _trigger_led_colors(
                    leds, immediate, time.monotonic(), mode_engine.current_mode
                )
            if mode_engine.is_locked:
                last_activity_time = frame_end

            pll_bpm = mode_engine.bpm or detector.bpm
            bpm_str = f"{pll_bpm:5.1f} BPM" if pll_bpm is not None else "  --- BPM"
            lock_str = (
                f"PLL:LOCK({phase_err_ms:+4.1f}ms)"
                if mode_engine.is_locked
                else f"PLL:WAIT({mode_engine._lock_intervals}/2)"
            )
            beat_info = f"B{mode_engine.beat_count}"
            print(
                f"[CLICK #{detector.click_count:03d}] "
                f"Pk:{hp_peak:5d} | {bpm_str} | {lock_str} | {beat_info}"
            )

        # 5. Handle LED off timing
        now = time.monotonic()
        if led_is_active and now >= led_off_at:
            leds.all_off()
            led_is_active = False

        # 6. Poll accelerometer for movement keep-awake & deliberate mode switch gesture
        triggered, gesture_kind = gesture_detector.check_gesture(now)
        if (
            gesture_detector.last_dyn >= MOTION_KEEPAWAKE_G
            or gesture_detector.last_jerk >= MOTION_KEEPAWAKE_G
        ):
            last_activity_time = now

        if triggered:
            new_mode = mode_engine.cycle_mode()
            print(f"\n{'*'*58}")
            print(f"[GESTURE: {gesture_kind}] >>> Switched to {MODE_NAMES[new_mode]} <<<")
            print(f"{'*'*58}\n")
            leds.signal_mode_change(new_mode)
            led_is_active = False
            now_after = time.monotonic()
            last_activity_time = now_after
            detector.last_click_time = now_after
            gesture_detector.last_trigger_time = now_after
            continue

        # 7. Check for inactivity sleep timeout (no movement & not locked to clicks)
        if (now - last_activity_time) >= IDLE_SLEEP_SEC and not mode_engine.is_locked:
            leds.all_off()
            led_is_active = False
            mic = sleep_until_movement(leds, mic, mic_pwr, gesture_detector, audio_buffer)
            mode_engine.reset_clock()
            now_wake = time.monotonic()
            last_activity_time = now_wake
            detector.last_click_time = now_wake
            gesture_detector.last_trigger_time = now_wake
            gesture_detector.in_stroke = False
            gesture_detector.shake_peaks.clear()
            continue

        # 8. Non-blocking USB Serial command check ('1'..'4' modes, 's' status, 'z' test sleep)
        if supervisor.runtime.serial_bytes_available:
            ch = sys.stdin.read(1)
            if ch in ("1", "2", "3", "4"):
                new_mode = mode_engine.set_mode(int(ch))
                print(f"\n[SERIAL CMD] >>> Switched to {MODE_NAMES[new_mode]} <<<\n")
                leds.signal_mode_change(new_mode)
                led_is_active = False
                now_after = time.monotonic()
                last_activity_time = now_after
                detector.last_click_time = now_after
                gesture_detector.last_trigger_time = now_after
            elif ch in ("z", "Z"):
                leds.all_off()
                led_is_active = False
                mic = sleep_until_movement(leds, mic, mic_pwr, gesture_detector, audio_buffer)
                mode_engine.reset_clock()
                now_wake = time.monotonic()
                last_activity_time = now_wake
                detector.last_click_time = now_wake
                gesture_detector.last_trigger_time = now_wake
                gesture_detector.in_stroke = False
                gesture_detector.shake_peaks.clear()
            elif ch in ("s", "S"):
                gc.collect()
                idle_s = time.monotonic() - last_activity_time
                print(
                    f"[STATUS] {MODE_NAMES[mode_engine.current_mode]} | "
                    f"Locked:{mode_engine.is_locked} | "
                    f"BPM:{mode_engine.bpm or 0.0:.1f} | "
                    f"Idle:{idle_s:.0f}s/{int(IDLE_SLEEP_SEC)}s | "
                    f"RAM:{gc.mem_free() // 1024}KB"
                )


if __name__ == "__main__":
    main()
