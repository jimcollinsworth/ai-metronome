"""AI Metronome POC v1 — Seeed Studio XIAO nRF52840 Sense (CircuitPython).

Copy this file directly to `CIRCUITPY/code.py`.
Requires NO external `/lib` dependencies (uses only built-in CircuitPython core modules).

Hardware behavior:
1. INIT & DIAGNOSTICS (BLUE LED):
   - Turns Blue LED ON during hardware health checks (Battery voltage gate, charge state,
     CPU die temperature, flash/RAM free space, PDM microphone power rail `board.MIC_PWR`,
     and `audiobusio.PDMIn` DMA stream verification).
   - Warms up the PDM decimation filter and calibrates the ambient room noise floor.
2. INIT OK (GREEN LED):
   - Pulses Green LED 3 times to confirm microphone & system initialization passed.
   - (If microphone init fails, alternates Red/Blue LED and prints diagnostics).
3. CLICK DETECTION LOOP (RED LED):
   - Continuously samples 8 ms (128-sample @ 16 kHz) unsigned 16-bit PDM DMA frames.
   - Uses a single-pass first-difference high-pass filter H(z) = 1 - z^-1 with adaptive
     noise floor tracking, crest factor verification, and sharp attack slope detection.
   - Flashes the onboard Red LED in real time on every detected click and logs live BPM.
"""

import array
import gc
import os
import time

import analogio
import audiobusio
import board
import digitalio
import microcontroller

# --- Audio & Click Detection Tuning Constants ---
SAMPLE_RATE = 16000
BUFFER_SIZE = 128          # 128 samples @ 16 kHz = 8.0 ms frame window (125 Hz frame rate)
WARMUP_FRAMES = 8          # Discard initial PDM decimation filter power-on settling frames
CALIBRATION_FRAMES = 20    # Ambient noise calibration window (~160 ms)
LED_FLASH_SEC = 0.045      # 45 ms crisp red LED pulse duration on each click


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

    def signal_fault_loop(self) -> None:
        """Alternate Red and Blue LEDs indefinitely if critical hardware fails."""
        while True:
            self.set_rgb(True, False, False)
            time.sleep(0.25)
            self.set_rgb(False, False, True)
            time.sleep(0.25)


def extract_highpass_features(sample_buffer) -> tuple[float, int]:
    """Single-pass first-difference high-pass filter H(z) = 1 - z^-1.

    Eliminates DC offset in one pass and amplifies 1-6 kHz click transients
    while rejecting low-frequency room rumble and mains hum.
    """
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
    """Adaptive high-pass transient click detector and tempo (BPM) tracker."""

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
                avg_ioi = sum(self.recent_intervals) / len(self.recent_intervals)
                self.bpm = 60.0 / avg_ioi
            self.last_click_time = now
        elif not in_refractory and hp_peak < peak_thresh * 0.7:
            alpha = self.ema_alpha
            self.noise_floor_mean = (1.0 - alpha) * self.noise_floor_mean + alpha * hp_mean
            self.noise_floor_peak = (1.0 - alpha) * self.noise_floor_peak + alpha * hp_peak
            self.noise_floor_mean = max(15.0, self.noise_floor_mean)
            self.noise_floor_peak = max(60.0, self.noise_floor_peak)

        self.prev_hp_peak = hp_peak
        return is_click, hp_mean, hp_peak


def get_battery_voltage() -> float:
    """Sample battery voltage via XIAO nRF52840 isolation gate (`READ_BATT_ENABLE` & `VBATT`)."""
    vbat_en = None
    adc = None
    try:
        vbat_en = digitalio.DigitalInOut(board.READ_BATT_ENABLE)
        vbat_en.direction = digitalio.Direction.OUTPUT
        vbat_en.value = False  # Close isolation gate
        time.sleep(0.005)

        adc = analogio.AnalogIn(board.VBATT)
        raw = adc.value
        vbat_en.value = True   # Open gate immediately to prevent battery drain
        return (raw * 3.3 / 65535) * 1.51
    except Exception as err:
        print(f"  [WARN - BATTERY] Voltage read skipped: {err}")
        return 0.0
    finally:
        if adc:
            adc.deinit()
        if vbat_en:
            vbat_en.deinit()


def init_hardware(leds: StatusLEDs):
    """Run startup diagnostics, power up PDM microphone, and verify audio DMA capture."""
    print("\n" + "=" * 54)
    print("   AI METRONOME POC — XIAO nRF52840 SENSE INIT")
    print("=" * 54)

    # Indicate INIT in progress with solid Blue LED
    leds.set_rgb(False, False, True)

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
        print(f"  [DIAG] Memory / Storage : {free_ram_kb:.1f} KB RAM free | {free_kb:.1f} KB Flash free")
    except Exception:
        pass

    # 2. Wake PDM Microphone Power Gate (`board.MIC_PWR`)
    mic_pwr = None
    try:
        mic_pwr = digitalio.DigitalInOut(board.MIC_PWR)
        mic_pwr.direction = digitalio.Direction.OUTPUT
        mic_pwr.value = True
        time.sleep(0.02)
        print("  [MIC]  Power Gate       : Active (board.MIC_PWR = HIGH)")
    except ValueError:
        print("  [MIC]  Power Gate       : Recycled active rail (soft-reboot)")
    except Exception as err:
        print(f"  [FAIL] Microphone power gate failed: {err}")
        return None, None

    # 3. Initialize PDM Microphone (`audiobusio.PDMIn`)
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
        return None, mic_pwr

    # 4. Verify Microphone DMA Capture & Settling
    test_buf = array.array("H", [0] * BUFFER_SIZE)
    for _ in range(WARMUP_FRAMES):
        mic.record(test_buf, len(test_buf))

    min_sample = min(test_buf)
    max_sample = max(test_buf)
    span = max_sample - min_sample
    if max_sample == 0 or min_sample == 65535:
        print(f"  [FAIL] PDM Microphone rail stuck (min={min_sample}, max={max_sample})")
        return None, mic_pwr

    print(f"  [MIC]  Signal Health    : OK (DC range {min_sample}..{max_sample}, span={span})")
    return mic, mic_pwr


def main() -> None:
    leds = StatusLEDs()
    mic, _mic_pwr = init_hardware(leds)

    if mic is None:
        print("[FATAL] Hardware initialization failed. Entering fault blink loop.")
        leds.signal_fault_loop()
        return

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
    print("=" * 54)
    print("[READY] Initialization OK! Listening for clicks (Red LED blinks on click)...\n")

    # Blink Green LED 3 times to signal Init & Mic Check OK
    leds.signal_init_ok()

    red_led_off_at = 0.0
    red_led_active = False

    while True:
        mic.record(audio_buffer, len(audio_buffer))
        now = time.monotonic()

        is_click, hp_mean, hp_peak = detector.process_frame(audio_buffer, now)

        if is_click:
            leds.set_rgb(True, False, False)  # Turn RED LED ON immediately
            red_led_active = True
            red_led_off_at = now + LED_FLASH_SEC

            bpm_str = f"{detector.bpm:5.1f} BPM" if detector.bpm is not None else "  --- BPM"
            print(
                f"[CLICK #{detector.click_count:03d}] "
                f"Peak:{hp_peak:6d} | Mean:{hp_mean:6.1f} | "
                f"Floor:{detector.noise_floor_peak:5.0f} | {bpm_str}"
            )
        elif red_led_active and now >= red_led_off_at:
            leds.all_off()
            red_led_active = False


if __name__ == "__main__":
    main()
