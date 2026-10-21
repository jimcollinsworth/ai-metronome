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
- [x] 4-Mode Visual Flash Engine, Dual-Gesture Switcher & HIL CLI Runner:
  - [x] Mode 1: On-Beat ($1\times$ click, Red)
  - [x] Mode 2: In-Between / Upbeat ($t + \text{IOI}/2$, Blue)
  - [x] Mode 3: 4/4 Meter (Green on beat 1, NO LED on beats 2, 3, 4)
  - [x] Mode 4: 3/4 Meter (Green on beat 1, NO LED on beats 2, 3)
  - [x] High-rate (125 Hz poll / 416 Hz ODR) LSM6DS3TR-C gesture detection supporting either **2 slowish shakes** or **1 harder drop to the table**
  - [x] Unmistakable visual mode confirmation: 350ms Bright White burst (all 3 RGB diodes) followed by $N$ slow pulses in the new mode's color
  - [x] Extended LED pulse width to 130ms (`LED_FLASH_SEC = 0.130`)
  - [x] Hardware-in-the-Loop (HIL) CLI tool (`tools/xiao_cli.py` / `uv run xiao-cli`) for automated code push (`deploy`) and 6-point hardware verification (`hil-test`)
  - [x] Comprehensive unit tests in `tests/test_mode_engine.py`
- [x] Automated HIL verification of POC v2 on physical XIAO nRF52840 Sense (`COM9` / `D:\`)
- [x] Autonomous Phase-Locked Loop (PLL) Beat Clock & Gesture Sensitivity Tuning (POC v2.1):
  - [x] Backed off accelerometer gesture thresholds (`slow_shake_dyn_g = 0.48g`, `hard_drop_dyn_g = 1.35g`, `debounce_sec = 1.0s`) to prevent accidental mode switches from minor handling
  - [x] Sub-frame sample-index click onset localization (`62.5 µs` resolution inside 80-sample / `4.9 ms` DMA frames at ~200 Hz)
  - [x] Fixed boundary-straddling click rejection (`prev_quiet_peak` tracking)
  - [x] Autonomous internal PLL Beat Clock (`period`, `next_beat_time`, proportional phase gain `0.35`, integral frequency gain `0.22`, 3-beat coasting) driving LED timing independently of single-frame click detection jitter
  - [x] Deployed and verified on physical XIAO nRF52840 Sense via `uv run xiao-cli hil-test --deploy`
- [ ] Phase 2 POC: Port click detector, PLL beat clock & mode engine firmware to C++ (`src/xiao_nrf52840_sense/cpp/`)
- [ ] Phase 3 POC: Port click detector, PLL beat clock & mode engine firmware to Rust (`src/xiao_nrf52840_sense/rust/`)
- [ ] Phase 4: Optimized Native Firmware (C++ / Rust) with On-Device Voice Input via TensorFlow Lite for Microcontrollers (TFLite Micro / CMSIS-NN keyword spotting on shared 16 kHz PDM DMA stream)

---

## Backlog

- [ ] [Backlog items in progress]
