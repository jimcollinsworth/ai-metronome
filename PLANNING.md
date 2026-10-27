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
  - [x] Mode 1: On-Beat ($1\times$ click, Red — always default on reset)
  - [x] Mode 2: In-Between / Upbeat ($t + \text{IOI}/2$, Blue)
  - [x] Mode 3: 4/4 Meter (Bright Green on beat 1, Dim Red on beats 2, 3, 4)
  - [x] Mode 4: 3/4 Meter (Bright Green on beat 1, Dim Red on beats 2, 3)
  - [x] Hardware PWM (`pwmio.PWMOut`) brightness shading: all LEDs dimmed (`10%` duty, `60 ms`) until PLL locks in (2 consistent beat intervals / 3 steady clicks), and Red weak beats dimmed (`12%` duty, `60 ms`) in 3/4 & 4/4 meter to emphasize the Bright Green (`100%` duty, `130 ms`) downbeat
  - [x] High-rate (200 Hz poll / 416 Hz ODR) LSM6DS3TR-C gesture detection supporting either **2 slowish shakes** or **1 harder drop to the table**
  - [x] Unmistakable visual mode confirmation: 350ms Bright White burst (all 3 RGB diodes) followed by $N$ slow pulses in the new mode's color
  - [x] Extended LED pulse width to 130ms (`LED_FLASH_SEC = 0.130`)
  - [x] Hardware-in-the-Loop (HIL) CLI tool (`tools/xiao_cli.py` / `uv run xiao-cli`) for automated code push (`deploy`) and 6-point hardware verification (`hil-test`)
  - [x] Comprehensive unit tests in `tests/test_mode_engine.py`
- [x] Automated HIL verification of POC v2 on physical XIAO nRF52840 Sense (`COM9` / `D:\`)
- [x] Autonomous Phase-Locked Loop (PLL) Beat Clock & Gesture Sensitivity Tuning (POC v2.1 / v2.3):
  - [x] Backed off accelerometer gesture thresholds (`slow_shake_dyn_g = 0.48g`, `hard_drop_dyn_g = 1.35g`, `debounce_sec = 1.0s`) to prevent accidental mode switches from minor handling
  - [x] Sub-frame sample-index click onset localization (`62.5 µs` resolution inside 80-sample / `4.9 ms` DMA frames at ~200 Hz)
  - [x] Fixed boundary-straddling click rejection (`prev_quiet_peak` tracking) and added outlier-resistant baseline noise floor calibration
  - [x] Autonomous internal PLL Beat Clock (`period`, `next_beat_time`, proportional phase gain `0.35`, integral frequency gain `0.22`, 3-beat coasting) driving LED timing independently of single-frame click detection jitter
  - [x] Low-power motion sleep/wake (`IDLE_SLEEP_SEC = 30.0s`): powers down PDM microphone (`MIC_PWR = LOW`, `mic.deinit()`), switches LSM6DS3TR-C to `26 Hz` low-power wake-interrupt mode (`board.IMU_INT1`), and sleeps the Cortex-M4F CPU (`WFI`) until awakened by movement (`WAKE_MOTION_G = 0.12g` or `IMU_INT1`)
  - [x] Non-blocking USB Serial runtime mode control (`1`–`4`, `s` status, `z` sleep test) via `supervisor.runtime.serial_bytes_available`
  - [x] Installed project agent skills under `.agents/skills/` (`circuitpython-tricks`, `xiao-nrf52840-sense`, `nrf52840-mcu`)
  - [x] Deployed and verified on physical XIAO nRF52840 Sense via `uv run xiao-cli hil-test --deploy`
- [x] Phase 2 POC: Port click detector, PLL beat clock, 4 modes, gestures, and sleep/wake firmware to Embedded Rust (`src/xiao_nrf52840_sense/rust/`):
  - [x] Platform-independent `no_std` core library (`click_detector.rs`, `mode_engine.rs`, `gesture.rs`, `crash_log.rs`) with 100% feature parity to Python v2.6.
  - [x] Host unit tests passed on Windows x86_64 (`cargo test --lib --target x86_64-pc-windows-msvc`).
  - [x] Bare-metal ARM Cortex-M4F firmware (`main.rs`, `hardware.rs`) with EasyDMA PDM (16 kHz), TWIM (400 kHz), active-low RGB LED retinal pulse dimming, 5.0s watchdog (`NRF_WDT`), retained RAM crash log (`.uninit`), and native USB CDC serial with 1200-baud DFU reset touch.
  - [x] Windows `cmd.exe` toolchain and pure-Python ELF32-to-UF2 packer (`0xADA52840`) in `tools/xiao_cli.py` (`uv run xiao-cli rust-build` and `uv run xiao-cli rust-deploy`).
  - [x] Cross-compilation to `thumbv7em-none-eabihf` verified (`56.0 KB` flash, `4 bytes` static RAM, 219 UF2 blocks, 0 compiler warnings).
  - [ ] On-device validation of Rust firmware: investigate bootloader app validation / vector table jump from DFU mode.
- [ ] Phase 3 POC: Port click detector, PLL beat clock & mode engine firmware to C++ (`src/xiao_nrf52840_sense/cpp/`)
- [ ] Phase 4: Optimized Native Firmware (C++ / Rust) with Timbre/Harmonicity Rhythm Locking, Instrument Rejection & Custom-Phrase Voice Input (TFLite Micro / CMSIS-NN):
  - [ ] Multi-cluster rhythm locking via 7D onset fingerprint (4-band $L_2$-normalized timbre, Spectral Flatness, autocorrelation Harmonicity, and `20–35 ms` tail decay): listen first for repeated sounds of the same type across candidate clusters and lock onto the strongest periodic click stream
  - [ ] Musical instrument discrimination (e.g. piano rejection): reject transients with sustained string decay (`> 20 ms`), high pitch harmonicity, or low cosine similarity to the locked click centroid
  - [ ] On-device **custom-phrase** voice command control (e.g., *"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"sleep"*) via quantized `int8` DS-CNN in TFLite Micro + CMSIS-NN on the shared 16 kHz PDM DMA stream

---

## Backlog

- [ ] [Backlog items in progress]
