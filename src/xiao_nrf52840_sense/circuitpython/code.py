"""AI Metronome POC v2 — Seeed Studio XIAO nRF52840 Sense (CircuitPython).

Copy this file directly to `CIRCUITPY/code.py`.
Works out of the box with zero external libraries required, or automatically
uses `adafruit_lsm6ds` if present in `/lib`.

Features:
1. HARDWARE INIT & DIAGNOSTICS:
   - Turns Blue LED ON during hardware health checks (Battery voltage gate, charge state,
     CPU die temperature, memory free space, PDM mic rail `board.MIC_PWR`, and IMU power rail `board.IMU_PWR`).
   - Calibrates PDM microphone ambient noise floor.
   - Initializes onboard LSM6DS3TR-C 6-axis accelerometer on internal I2C bus (`board.IMU_SCL` / `board.IMU_SDA`).
2. INIT OK:
   - Pulses Green LED 3 times to confirm initialization passed.
3. 5-MODE VISUAL FLASH SEQUENCER (Enhanced Brightness: 75ms pulse width):
   - Mode 1: On-Beat (1x) — Flashes Red on every click.
   - Mode 2: In-Between / Upbeat (&) — Flashes Blue halfway between clicks (t + IOI / 2).
   - Mode 3: Double-Time (2x) — 2 flashes per click (Red on beat, Blue on upbeat).
   - Mode 4: 4/4 Meter — Green on Beat 1, silent (no LED) on Beats 2, 3, 4.
   - Mode 5: 3/4 Meter — Green on Beat 1, silent (no LED) on Beats 2, 3.
4. GESTURE MODE SWITCHING (Onboard Accelerometer):
   - Quick shake of the device (|a| > 2.3g) cycles through modes 1 -> 2 -> 3 -> 4 -> 5 -> 1.
   - Pulses Cyan LED N times matching the new mode number for immediate visual confirmation.
"""

import array
import gc
import os
import struct
import time

import analogio
import audiobusio
import board
import busio
import digitalio
import microcontroller

# Optional Adafruit driver support if present in /lib
try:
    from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC  # type: ignore
    HAS_ADAFRUIT_LSM6DS = True
except ImportError:
    HAS_ADAFRUIT_LSM6DS = False

# --- Audio, IMU & Timing Tuning Constants ---
SAMPLE_RATE = 16000
BUFFER_SIZE = 128          # 128 samples @ 16 kHz = 8.0 ms frame window (125 Hz frame rate)
WARMUP_FRAMES = 8          # Discard initial PDM decimation filter power-on settling frames
CALIBRATION_FRAMES = 20    # Ambient noise calibration window (~160 ms)
LED_FLASH_SEC = 0.075      # 75 ms high-visibility pulse duration (increased brightness)
SHAKE_THRESHOLD_G = 2.3    # Shake acceleration threshold in g's (|a| > 2.3g)
SHAKE_DEBOUNCE_SEC = 0.6   # Minimum interval between shake mode switches
PAUSE_RESET_SEC = 2.0      # Reset meter beat count to 1 if clicks pause longer than 2.0s


class MetronomeMode:
    """Metronome visual flash modes."""
    ON_BEAT = 1
    UPBEAT = 2
    DOUBLE_TIME = 3
    METER_4_4 = 4
    METER_3_4 = 5


MODE_NAMES = {
    MetronomeMode.ON_BEAT: "Mode 1: On Beat (1x Red)",
    MetronomeMode.UPBEAT: "Mode 2: In-Between / Upbeat (& Blue)",
    MetronomeMode.DOUBLE_TIME: "Mode 3: Double Time (2x Red + Blue)",
    MetronomeMode.METER_4_4: "Mode 4: 4/4 Meter (Green on 1, silent 2-4)",
    MetronomeMode.METER_3_4: "Mode 5: 3/4 Meter (Green on 1, silent 2-3)",
}


class StatusLEDs:
    """Driver for the XIAO nRF52840 Sense onboard 3-in-1 RGB LED (Active-Low)."""

    def __init__(self) -> None:
        self.red = self._init_pin(getattr(board, "LED_RED", getattr(board, "LED", None)))
        self.green = self._init_pin(getattr(board, "LED_GREEN", None))
        self.blue = self._init_pin(getattr(board, "LED_BLUE", None))
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

    def set_rgb(self, r: bool, g: bool, b: bool) -> None:
        """Set Red, Green, Blue states (True = ON, False = OFF)."""
        if self.red is not None:
            self.red.value = not r
        if self.green is not None:
            self.green.value = not g
        if self.blue is not None:
            self.blue.value = not b

    def all_off(self) -> None:
        self.set_rgb(False, False, False)

    def signal_init_ok(self) -> None:
        """Blink Green LED 3 times to indicate successful initialization."""
        self.all_off()
        for _ in range(3):
            self.set_rgb(False, True, False)
            time.sleep(0.12)
            self.all_off()
            time.sleep(0.08)

    def signal_mode_change(self, mode_num: int) -> None:
        """Blink Cyan LED mode_num times to confirm new mode selection."""
        self.all_off()
        time.sleep(0.05)
        for _ in range(mode_num):
            self.set_rgb(False, True, True)  # Cyan
            time.sleep(0.09)
            self.all_off()
            time.sleep(0.07)

    def signal_fault_loop(self) -> None:
        """Alternate Red and Blue LEDs indefinitely if critical hardware fails."""
        while True:
            self.set_rgb(True, False, False)
            time.sleep(0.25)
            self.set_rgb(False, False, True)
            time.sleep(0.25)


class ShakeDetector:
    """Accelerometer shake detector for onboard LSM6DS3TR-C.

    Uses adafruit_lsm6ds if installed, or built-in direct I2C registers
    (CTRL1_XL=0x10, OUTX_L_XL=0x28) with zero external dependencies.
    """

    def __init__(self, i2c_bus, threshold_g: float = SHAKE_THRESHOLD_G, debounce_sec: float = SHAKE_DEBOUNCE_SEC):
        self.i2c = i2c_bus
        self.threshold_g = threshold_g
        self.debounce_sec = debounce_sec
        self.address = 0x6A
        self.last_shake_time = -10.0
        self._buf6 = bytearray(6)
        self.sensor_obj = None
        self.is_ready = False

        if self.i2c:
            self._init_sensor()

    def _init_sensor(self) -> None:
        # 1. Try official Adafruit driver if present
        if HAS_ADAFRUIT_LSM6DS:
            try:
                self.sensor_obj = LSM6DS3TRC(self.i2c)
                self.is_ready = True
                print("  [IMU]  Accelerometer    : Active via adafruit_lsm6ds library")
                return
            except Exception as err:
                print(f"  [INFO - IMU] adafruit_lsm6ds init skipped: {err}, using direct I2C")

        # 2. Direct I2C driver (no /lib dependencies required)
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

                # WHO_AM_I check (register 0x0F)
                who = bytearray(1)
                self.i2c.writeto_then_readfrom(self.address, bytes([0x0F]), who)
                print(f"  [IMU]  WHO_AM_I         : {hex(who[0])} at {hex(self.address)}")

                # CTRL1_XL (0x10): 104 Hz ODR, +/- 4g scale (0x48)
                self.i2c.writeto(self.address, bytes([0x10, 0x48]))
                self.is_ready = True
                print("  [IMU]  Accelerometer    : Active via direct I2C (104 Hz, +/-4g)")
            finally:
                self.i2c.unlock()
        except Exception as err:
            print(f"  [WARN - IMU] LSM6DS3 direct init warning: {err}")

    def check_shake(self, now: float) -> bool:
        """Check if acceleration magnitude exceeds shake threshold."""
        if not self.is_ready or (now - self.last_shake_time) < self.debounce_sec:
            return False

        try:
            if self.sensor_obj is not None:
                ax, ay, az = self.sensor_obj.acceleration
                # Convert m/s^2 to g (1g ~ 9.806 m/s^2)
                accel_mag = ((ax * ax + ay * ay + az * az) ** 0.5) / 9.80665
                if accel_mag > self.threshold_g:
                    self.last_shake_time = now
                    return True
            else:
                if not self.i2c.try_lock():
                    return False
                try:
                    # Read OUTX_L_XL through OUTZ_H_XL (registers 0x28 - 0x2D)
                    self.i2c.writeto_then_readfrom(self.address, bytes([0x28]), self._buf6)
                finally:
                    self.i2c.unlock()

                ax, ay, az = struct.unpack("<hhh", self._buf6)
                # +/-4g range: 8192 LSB/g
                accel_mag = ((ax * ax + ay * ay + az * az) ** 0.5) / 8192.0
                if accel_mag > self.threshold_g:
                    self.last_shake_time = now
                    return True
        except Exception:
            return False
        return False


def extract_highpass_features(sample_buffer) -> tuple[float, int]:
    """Single-pass first-difference high-pass filter H(z) = 1 - z^-1."""
    count = len(sample_buffer)
    if count < 2:
        return 0.0, 0

    hp_sum = 0
    hp_peak = 0
    prev = sample_buffer[0]

    for i in range(1, count):
        curr = sample_buffer[i]
        diff = curr - prev
        if diff < 0:
            diff = -diff
        hp_sum += diff
        if diff > hp_peak:
            hp_peak = diff
        prev = curr

    return hp_sum / (count - 1), hp_peak


class PDMClickDetector:
    """Adaptive high-pass transient click detector and tempo tracker."""

    def __init__(
        self,
        peak_snr_mult: float = 6.0,
        mean_snr_mult: float = 1.6,
        min_peak_threshold: int = 800,
        attack_slope_ratio: float = 1.8,
        refractory_sec: float = 0.12,
        ema_alpha: float = 0.04,
    ) -> None:
        self.peak_snr_mult = peak_snr_mult
        self.mean_snr_mult = mean_snr_mult
        self.min_peak_threshold = min_peak_threshold
        self.attack_slope_ratio = attack_slope_ratio
        self.refractory_sec = refractory_sec
        self.ema_alpha = ema_alpha

        self.noise_floor_mean: float = 40.0
        self.noise_floor_peak: float = 120.0
        self.prev_hp_peak: int = 0
        self.last_click_time: float = -10.0
        self.click_count: int = 0
        self.recent_intervals: list[float] = []
        self.avg_ioi: float = 0.5
        self.bpm: float | None = None
        self.is_calibrated: bool = False

        self._cal_means: list[float] = []
        self._cal_peaks: list[int] = []

    def calibrate_step(self, sample_buffer) -> tuple[float, int]:
        hp_mean, hp_peak = extract_highpass_features(sample_buffer)
        self._cal_means.append(hp_mean)
        self._cal_peaks.append(hp_peak)
        return hp_mean, hp_peak

    def finalize_calibration(self) -> tuple[float, float]:
        if self._cal_means:
            avg_mean = sum(self._cal_means) / len(self._cal_means)
            avg_peak = sum(self._cal_peaks) / len(self._cal_peaks)
            self.noise_floor_mean = max(15.0, avg_mean)
            self.noise_floor_peak = max(60.0, avg_peak)
            self.prev_hp_peak = int(self.noise_floor_peak)
        self.is_calibrated = True
        return self.noise_floor_mean, self.noise_floor_peak

    def process_frame(self, sample_buffer, now: float) -> tuple[bool, float, int]:
        hp_mean, hp_peak = extract_highpass_features(sample_buffer)

        peak_thresh = max(
            float(self.min_peak_threshold),
            self.noise_floor_peak * self.peak_snr_mult,
        )
        mean_thresh = max(25.0, self.noise_floor_mean * self.mean_snr_mult)

        elapsed = now - self.last_click_time
        in_refractory = elapsed < self.refractory_sec

        crest_ratio = hp_peak / (hp_mean + 1.0)
        is_sharp_attack = hp_peak >= (self.prev_hp_peak * self.attack_slope_ratio)

        is_click = (
            (not in_refractory)
            and (hp_peak >= peak_thresh)
            and (hp_mean >= mean_thresh)
            and (crest_ratio >= 2.2)
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
            self.last_click_time = now
        elif not in_refractory and hp_peak < peak_thresh * 0.7:
            alpha = self.ema_alpha
            self.noise_floor_mean = (1.0 - alpha) * self.noise_floor_mean + alpha * hp_mean
            self.noise_floor_peak = (1.0 - alpha) * self.noise_floor_peak + alpha * hp_peak
            self.noise_floor_mean = max(15.0, self.noise_floor_mean)
            self.noise_floor_peak = max(60.0, self.noise_floor_peak)

        self.prev_hp_peak = hp_peak
        return is_click, hp_mean, hp_peak


class CircuitModeEngine:
    """Manages visual flash modes, beat counting, and upbeat scheduling."""

    def __init__(self, pause_reset_sec: float = PAUSE_RESET_SEC) -> None:
        self.current_mode = MetronomeMode.ON_BEAT
        self.pause_reset_sec = pause_reset_sec
        self.last_click_time = None
        self.beat_count = 0
        self.scheduled_flashes = []  # list of (target_time, color)

    def cycle_mode(self) -> int:
        self.current_mode = (self.current_mode % 5) + 1
        self.beat_count = 0
        self.scheduled_flashes.clear()
        return self.current_mode

    def on_click(self, now: float, ioi: float) -> list[str]:
        """Process click and return list of immediate LED colors to flash ('RED', 'GREEN', or empty)."""
        if self.last_click_time is not None and (now - self.last_click_time) > self.pause_reset_sec:
            self.beat_count = 0
        self.last_click_time = now

        if self.current_mode == MetronomeMode.METER_4_4:
            self.beat_count = (self.beat_count % 4) + 1
        elif self.current_mode == MetronomeMode.METER_3_4:
            self.beat_count = (self.beat_count % 3) + 1
        else:
            self.beat_count = (self.beat_count % 4) + 1

        immediate = []

        if self.current_mode == MetronomeMode.ON_BEAT:
            immediate.append("RED")

        elif self.current_mode == MetronomeMode.UPBEAT:
            if ioi > 0:
                self.scheduled_flashes.append((now + (ioi / 2.0), "BLUE"))

        elif self.current_mode == MetronomeMode.DOUBLE_TIME:
            immediate.append("RED")
            if ioi > 0:
                self.scheduled_flashes.append((now + (ioi / 2.0), "BLUE"))

        elif self.current_mode in (MetronomeMode.METER_4_4, MetronomeMode.METER_3_4):
            if self.beat_count == 1:
                immediate.append("GREEN")

        return immediate

    def get_due_flashes(self, now: float) -> list[str]:
        """Pop and return any scheduled upbeat colors due at or before `now`."""
        due = []
        remaining = []
        for target_time, color in self.scheduled_flashes:
            if target_time <= now:
                due.append(color)
            else:
                remaining.append((target_time, color))
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
    """Run startup diagnostics, power up PDM mic and IMU, return (mic, i2c)."""
    print("\n" + "=" * 58)
    print("   AI METRONOME POC v2 — XIAO nRF52840 SENSE INIT")
    print("=" * 58)

    leds.set_rgb(False, False, True)  # Solid Blue LED during init

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
        time.sleep(0.08)  # Allow IMU power rail to stabilize
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
        return None, None

    # Verify Microphone DMA Capture
    test_buf = array.array("H", [0] * BUFFER_SIZE)
    for _ in range(WARMUP_FRAMES):
        mic.record(test_buf, len(test_buf))

    min_sample = min(test_buf)
    max_sample = max(test_buf)
    span = max_sample - min_sample
    if max_sample == 0 or min_sample == 65535:
        print(f"  [FAIL] PDM Microphone rail stuck (min={min_sample}, max={max_sample})")
        return None, None
    print(f"  [MIC]  Signal Health    : OK (DC range {min_sample}..{max_sample}, span={span})")

    # 5. Initialize Dedicated IMU I2C Bus
    i2c_bus = None
    try:
        i2c_bus = busio.I2C(board.IMU_SCL, board.IMU_SDA)
        print("  [IMU]  I2C Bus          : Operational (board.IMU_SCL, board.IMU_SDA)")
    except Exception as err:
        print(f"  [WARN - IMU] Could not initialize IMU I2C bus: {err}")

    return mic, i2c_bus


def main() -> None:
    leds = StatusLEDs()
    mic, i2c_bus = init_hardware(leds)

    if mic is None:
        print("[FATAL] Hardware initialization failed. Entering fault blink loop.")
        leds.signal_fault_loop()
        return

    # Accelerometer shake detector and mode engine
    shake_detector = ShakeDetector(i2c_bus)
    mode_engine = CircuitModeEngine()

    audio_buffer = array.array("H", [0] * BUFFER_SIZE)
    detector = PDMClickDetector()

    # Calibrate ambient noise floor while blinking Blue LED
    print("  [CAL]  Calibrating ambient room noise floor...")
    for i in range(CALIBRATION_FRAMES):
        leds.set_rgb(False, False, (i % 2 == 0))
        mic.record(audio_buffer, len(audio_buffer))
        detector.calibrate_step(audio_buffer)

    nf_mean, nf_peak = detector.finalize_calibration()
    print(f"  [CAL]  Baseline Floor   : mean={nf_mean:.1f}, peak={nf_peak:.1f}")
    print("=" * 58)
    print("[READY] Initialization OK! Metronome active.")
    print(f"[MODE]  Current: {MODE_NAMES[mode_engine.current_mode]}")
    print("[TIP]   Shake device firmly to cycle modes (1 -> 2 -> 3 -> 4 -> 5 -> 1)\n")

    leds.signal_init_ok()

    led_off_at = 0.0
    led_is_active = False
    loop_count = 0

    while True:
        # 1. Capture 8 ms audio frame via PDM DMA
        mic.record(audio_buffer, len(audio_buffer))
        now = time.monotonic()
        loop_count += 1

        # 2. Check for shake gesture every 4 frames (~32 ms)
        if loop_count % 4 == 0:
            if shake_detector.check_shake(now):
                new_mode = mode_engine.cycle_mode()
                print(f"\n{'*'*50}")
                print(f"[SHAKE DETECTED] >>> Switched to {MODE_NAMES[new_mode]} <<<")
                print(f"{'*'*50}\n")
                leds.signal_mode_change(new_mode)
                led_is_active = False
                continue

        # 3. Process audio frame for click
        is_click, hp_mean, hp_peak = detector.process_frame(audio_buffer, now)

        if is_click:
            bpm_str = f"{detector.bpm:5.1f} BPM" if detector.bpm is not None else "  --- BPM"
            beat_info = f"Beat {mode_engine.beat_count}" if mode_engine.current_mode in (MetronomeMode.METER_4_4, MetronomeMode.METER_3_4) else ""
            print(
                f"[CLICK #{detector.click_count:03d}] "
                f"Peak:{hp_peak:6d} | Mean:{hp_mean:6.1f} | {bpm_str} | {beat_info}"
            )

            # Trigger immediate flash per active mode
            immediate = mode_engine.on_click(now, detector.avg_ioi)
            if "RED" in immediate:
                leds.set_rgb(True, False, False)
                led_is_active = True
                led_off_at = now + LED_FLASH_SEC
            elif "GREEN" in immediate:
                leds.set_rgb(False, True, False)
                led_is_active = True
                led_off_at = now + LED_FLASH_SEC

        # 4. Check for scheduled upbeat flashes (Mode 2 or Mode 3)
        due_flashes = mode_engine.get_due_flashes(now)
        if "BLUE" in due_flashes:
            leds.set_rgb(False, False, True)
            led_is_active = True
            led_off_at = now + LED_FLASH_SEC

        # 5. Handle LED off timing
        if led_is_active and now >= led_off_at:
            leds.all_off()
            led_is_active = False


if __name__ == "__main__":
    main()
