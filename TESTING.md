# Testing Documentation & Verification Guide: ai-metronome

This document defines the testing strategy, test suites, execution commands, and operational standards for `ai-metronome`.

---

## 1. Testing Architecture & Verification Pyramid

Testing for this project operates across defined tiers:

- **Host Unit Testing (DSP & Algorithms)**: Isolated verification of the PDM high-pass feature extractor, adaptive click detector, refractory debounce, low-frequency hum rejection, and BPM estimator on synthetic 16-bit unsigned PCM buffers.
- **Hardware-in-the-Loop (On-Device Diagnostics)**: Startup self-tests on the XIAO nRF52840 Sense verifying battery rail voltage, die temperature, `board.MIC_PWR` power gate activation, and `audiobusio.PDMIn` DMA sample health before entering the main loop.
- **Smoke Testing**: Package importability sanity checks.

---

## 2. Active Test Suites

| Test File | Scope |
|-----------|-------|
| `tests/test_smoke.py` | Package importability sanity check |
| `tests/test_click_detector.py` | First-difference high-pass filter DC cancellation, transient click detection, refractory echo rejection, low-frequency hum immunity, and 120 BPM tempo calculation |

*(Archived Puck.js BLE tests are preserved under `archive/puck/tests/`.)*

---

## 3. Environment & Test Tooling Setup

### Toolchain Versions & Requirements
* **Environment & Package Manager**: `uv` (`.venv/`)
* **Python Runtime**: Python 3.12+
* **Test Framework**: `pytest` (v8.0+)

### Running Tests

Execute the active test suite with:
```bash
uv run pytest -v
```
