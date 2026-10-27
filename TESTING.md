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
| `tests/test_uf2_packer.py` | Pure-Python ELF32 `PT_LOAD` parser & UF2 block generator (`0xADA52840`) |
| `src/xiao_nrf52840_sense/rust/` | Rust host unit tests (`click_detector`, `mode_engine`, `gesture`, `crash_log`) |
| `tools/xiao_cli.py` | Hardware-in-the-Loop (HIL) deployment, serial reset, live log streaming, and automated 6-point hardware verification |

*(Archived Puck.js BLE tests are preserved under `archive/puck/tests/`.)*

---

## 3. Environment & Test Execution Commands (Windows `cmd.exe`)

### Toolchain Versions & Requirements
* **Environment & Package Manager**: `uv` (`.venv/`)
* **Python Runtime**: Python 3.12+
* **Rust Toolchain**: `rustc 1.97.1+` (`x86_64-pc-windows-msvc` and `thumbv7em-none-eabihf`)
* **Test Framework**: `pytest` (v9.0+)

### Running Python Host Unit Tests (`cmd.exe`)
```cmd
uv run pytest -v
```

### Running Rust Host Unit Tests (`cmd.exe`)
```cmd
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc
```

### Building & Deploying Rust UF2 Firmware (`cmd.exe`)
```cmd
:: Build release binary and pack build\ai-metronome-rust.uf2
uv run xiao-cli rust-build

:: Flash UF2 image to XIAO-SENSE and wait for serial port
uv run xiao-cli rust-deploy

:: Flash UF2 image and immediately run 6-point HIL verification
uv run xiao-cli rust-deploy --test
```

### Running Hardware-in-the-Loop (HIL) Commands (`xiao-cli`)
```cmd
:: Detect connected XIAO drive and COM port
uv run xiao-cli status

:: Deploy CircuitPython code.py and run automated 6-point HIL hardware test
uv run xiao-cli python-deploy --test

:: Run HIL test against currently running firmware (CircuitPython or Rust)
uv run xiao-cli hil-test --port COM9

:: Live serial console & interactive debug keys ('d', 'r', 'b', 'z', '1'..'4')
uv run xiao-cli monitor --port COM9
```
