"""Unit tests for the XIAO nRF52840 Sense PDM Click Detector algorithm."""

import array
import math
import random

from ai_metronome.click_detector import (
    PDMClickDetector,
    extract_highpass_features,
)


def make_ambient_buffer(
    length: int = 128,
    dc_bias: int = 32768,
    noise_amp: int = 40,
    seed: int = 42,
) -> array.array:
    """Generate a synthetic 16-bit unsigned PDM buffer representing quiet room noise."""
    rng = random.Random(seed)
    samples = [
        max(0, min(65535, dc_bias + rng.randint(-noise_amp, noise_amp)))
        for _ in range(length)
    ]
    return array.array("H", samples)


def make_click_buffer(
    length: int = 128,
    dc_bias: int = 32768,
    click_amp: int = 4500,
    noise_amp: int = 40,
) -> array.array:
    """Generate a synthetic 16-bit unsigned PDM buffer containing a sharp percussive click transient."""
    buf = make_ambient_buffer(length=length, dc_bias=dc_bias, noise_amp=noise_amp)
    # Inject a damped high-frequency impulse/click starting at sample 32
    for i in range(24):
        idx = 32 + i
        if idx < length:
            envelope = math.exp(-i / 6.0)
            sign = 1 if (i % 2 == 0) else -1
            val = int(dc_bias + sign * click_amp * envelope)
            buf[idx] = max(0, min(65535, val))
    return buf


def make_low_freq_hum_buffer(
    length: int = 128,
    dc_bias: int = 32768,
    hum_amp: int = 1200,
    freq_hz: float = 100.0,
    sample_rate: int = 16000,
) -> array.array:
    """Generate a low-frequency hum/rumble buffer to verify high-pass rejection."""
    samples = []
    for n in range(length):
        val = int(dc_bias + hum_amp * math.sin(2.0 * math.pi * freq_hz * n / sample_rate))
        samples.append(max(0, min(65535, val)))
    return array.array("H", samples)


def test_extract_highpass_features_cancels_dc_and_highlights_click():
    """Verify first-difference high-pass feature extraction cancels DC offset and isolates clicks."""
    quiet = make_ambient_buffer(dc_bias=31000, noise_amp=35)
    click = make_click_buffer(dc_bias=31000, click_amp=4000, noise_amp=35)

    q_mean, q_peak = extract_highpass_features(quiet)
    c_mean, c_peak = extract_highpass_features(click)

    assert q_mean < 60
    assert q_peak < 100
    assert c_peak > 4000
    assert c_mean > q_mean * 3.0


def test_detector_calibration_and_click_detection():
    """Verify detector calibrates on ambient noise, triggers on a click, and respects refractory cooldown."""
    detector = PDMClickDetector(refractory_sec=0.12)
    quiet = make_ambient_buffer()
    click = make_click_buffer()

    # Calibrate with ambient buffers
    for i in range(10):
        detector.calibrate_step(make_ambient_buffer(seed=100 + i))
    detector.finalize_calibration()
    assert detector.is_calibrated is True

    # Quiet frames should not trigger
    assert detector.process_frame(quiet, now=1.000).is_click is False
    assert detector.process_frame(quiet, now=1.008).is_click is False

    # Sharp click at t=1.500s should trigger
    res1 = detector.process_frame(click, now=1.500)
    assert res1.is_click is True
    assert res1.click_count == 1

    # Immediate echo within refractory window (t=1.540s, +40ms < 120ms) MUST NOT double-trigger
    res_echo = detector.process_frame(click, now=1.540)
    assert res_echo.is_click is False
    assert res_echo.click_count == 1

    # Quiet frame in between resets envelope slope
    detector.process_frame(quiet, now=1.800)

    # Next beat at 120 BPM (t=2.000s, +500ms) SHOULD trigger and compute ~120 BPM
    res2 = detector.process_frame(click, now=2.000)
    assert res2.is_click is True
    assert res2.click_count == 2
    assert res2.bpm is not None
    assert abs(res2.bpm - 120.0) < 1.0


def test_detector_rejects_low_frequency_hum():
    """Verify steady low-frequency hum does not falsely trigger click detection."""
    detector = PDMClickDetector()
    for i in range(8):
        detector.calibrate_step(make_ambient_buffer(seed=200 + i))
    detector.finalize_calibration()

    hum = make_low_freq_hum_buffer(hum_amp=800, freq_hz=80.0)
    res = detector.process_frame(hum, now=3.000)
    assert res.is_click is False
