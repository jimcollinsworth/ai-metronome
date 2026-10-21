# Testing Documentation & Verification Guide: ai-metronome

This document defines the testing strategy, test suites, execution commands, and operational standards for `ai-metronome`.

---

## 1. Testing Architecture & Verification Pyramid

Testing for this project operates across defined tiers:

- **Host Unit Testing (DSP, Mode Engine & Gesture Math)**: Isolated verification of the PDM high-pass feature extractor, adaptive click detector, 4-mode visual flash sequencer, and 3-axis accelerometer gesture detector (2 slow shakes or 1 harder drop to table).
- **Hardware-in-the-Loop (HIL CLI Test Runner — `xiao-cli`)**: Automated on-device deployment and verification over USB (`CIRCUITPY` drive + USB CDC serial port). Soft-reboots the XIAO nRF52840 Sense and validates all 6 hardware initialization milestones (`POWER_DIAG`, `MIC_POWER`, `MIC_DMA_STREAM`, `IMU_BUS`, `IMU_ACCEL`, `CAL_AND_READY`).
- **Smoke Testing**: Package importability sanity checks.

---

## 2. Active Test Suites

| Test File / Tool | Scope |
|-----------|-------|
| `tests/test_smoke.py` | Package importability sanity check |
| `tests/test_click_detector.py` | First-difference high-pass filter DC cancellation, transient click detection, refractory echo rejection, low-frequency hum immunity, and 120 BPM tempo calculation |
| `tests/test_mode_engine.py` | 4-mode visual flash sequencing (On-Beat, Upbeat, 4/4 Meter, 3/4 Meter), pause reset timeout, and 3-axis accelerometer gesture detection (`DOUBLE_SHAKE` & `HARD_DROP`) |
| `tools/xiao_cli.py` | Hardware-in-the-Loop (HIL) deployment, serial reset, live log streaming, and automated 6-point hardware verification |

*(Archived Puck.js BLE tests are preserved under `archive/puck/tests/`.)*

---

## 3. Environment & Test Execution Commands

### Toolchain Versions & Requirements
* **Environment & Package Manager**: `uv` (`.venv/`)
* **Python Runtime**: Python 3.12+
* **Test Framework**: `pytest` (v8.0+)

### Running Host Unit Tests
```bash
uv run pytest -v
```

### Running Hardware-in-the-Loop (HIL) Commands (`xiao-cli`)
```bash
# Detect mounted CIRCUITPY drive and COM port
uv run xiao-cli status

# Push code.py to CIRCUITPY and run automated 6-point HIL hardware test
uv run xiao-cli hil-test --deploy

# Run HIL test + listen 10 seconds for live clicks/gestures
uv run xiao-cli hil-test --listen-sec 10

# Stream live serial console output
uv run xiao-cli monitor
```
