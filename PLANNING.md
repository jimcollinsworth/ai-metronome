# `PLANNING.md` — Active Backlog & Sprint Milestones

Active backlog and task tracking for `ai-metronome`.

---

## Active Sprint: XIAO nRF52840 Sense — CircuitPython Click Detector POC & Mode Sequencer

- [x] Commit initial project scaffold and Puck.js BLE CLI/TUI prototype
- [x] Archive Puck.js code and tests into `archive/puck/`
- [x] Design & unit-test PDM microphone click detection algorithm (`src/ai_metronome/click_detector.py`, `tests/test_click_detector.py`):
  - [x] Single-pass first-difference high-pass filter ($H(z) = 1 - z^{-1}$) for DC cancellation and 1–6 kHz click emphasis
  - [x] Adaptive noise floor tracker + crest factor + sharp attack slope gate
  - [x] Refractory debounce window and rolling inter-onset interval BPM estimator
- [x] Build self-contained CircuitPython firmware POC (`src/xiao_nrf52840_sense/circuitpython/code.py`):
  - [x] Startup diagnostics (battery rail gate, charge state, CPU temperature, free RAM/flash)
  - [x] `board.MIC_PWR` power gate activation, `audiobusio.PDMIn` warmup, and signal health verification
  - [x] Active-low RGB LED state feedback (Blue = init/calibrating, Green = init OK, Red = real-time click pulse)
- [x] On-device verification of POC v1 by Jim ("ok, that worked great")
- [x] 5-Mode Visual Flash Engine & Accelerometer Shake Switcher:
  - [x] Mode 1: On-Beat ($1\times$ click, Red)
  - [x] Mode 2: In-Between / Upbeat ($t + \text{IOI}/2$, Blue)
  - [x] Mode 3: Double-Time ($2\times$ flashes per click: Red on beat + Blue on upbeat)
  - [x] Mode 4: 4/4 Meter (Green on beat 1, NO LED on beats 2, 3, 4)
  - [x] Mode 5: 3/4 Meter (Green on beat 1, NO LED on beats 2, 3)
  - [x] Onboard LSM6DS3TR-C shake gesture detection ($|a| > 2.3g$, 0.6s debounce) via `board.IMU_PWR` and `board.IMU_SCL` / `board.IMU_SDA`
  - [x] Cyan LED blink mode confirmation on shake
  - [x] Brighter LED flashes (extended pulse width from 45ms to 75ms)
  - [x] Comprehensive unit tests in `tests/test_mode_engine.py`
- [ ] On-device verification of POC v2 on XIAO nRF52840 Sense
- [ ] Phase 2 POC: Port click detector & mode engine firmware to C++ (`src/xiao_nrf52840_sense/cpp/`)
- [ ] Phase 3 POC: Port click detector & mode engine firmware to Rust (`src/xiao_nrf52840_sense/rust/`)

---

## Backlog

- [ ] [Backlog items in progress]
