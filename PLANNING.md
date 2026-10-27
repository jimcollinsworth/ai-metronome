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
- [x] CJMCU-2812-8 (8x WS2812B NeoPixel Stick) Integration & Subtle Multi-Mode Visualizer:
  - [x] Built standalone CLI verification tool (`tools/test_neopixel.py`) with automatic backup, non-destructive deployment, and live monitoring
  - [x] Integrated unified LED driver into `src/xiao_nrf52840_sense/circuitpython/code.py` driving onboard RGB and NeoPixel stick simultaneously via zero-dependency `neopixel_write`
  - [x] Added startup hardware self-test pattern (cyan sweep + amber pulse) and 3-pulse green confirmation across all 8 pixels
  - [x] Boosted base brightness to 22% (`NEOPIXEL_BRIGHTNESS = 0.22`) with vivid color grading for clearly visible peripheral cues across all 4 modes:
    - Mode 1: Pendulum rock (tick-tock) alternating between left cluster `[1, 2, 3]` and right cluster `[4, 5, 6]` in warm amber-red
    - Mode 2: Rhythmic center anchor `[3, 4]` on downbeat + cyan-blue outer wing pulse `[0, 1]` & `[6, 7]` on syncopated upbeat (&)
    - Mode 3 (4/4): 2-LED progressive measure bar stepping across `[0,1]` (green accent) -> `[2,3]` (warm amber) -> `[4,5]` (teal) -> `[6,7]` (warm amber)
    - Mode 4 (3/4): Symmetrical waltz triple-step stepping across `[0,1,2]` (green accent) -> `[3,4]` (warm amber) -> `[5,6,7]` (warm amber)
  - [x] Verified 100% pass on physical hardware via `xiao-cli hil-test` (COM5 / F:\)
- [x] Phase 2 POC: Port click detector, PLL beat clock, 4 modes, gestures, and sleep/wake firmware to Embedded Rust (`src/xiao_nrf52840_sense/rust/`):
  - [x] Platform-independent `no_std` core library (`click_detector.rs`, `mode_engine.rs`, `gesture.rs`, `crash_log.rs`) with 100% feature parity to Python v2.6.
  - [x] Host unit tests passed on Windows x86_64 (`cargo test --lib --target x86_64-pc-windows-msvc`).
  - [x] Bare-metal ARM Cortex-M4F firmware (`main.rs`, `hardware.rs`) with EasyDMA PDM (16 kHz), TWIM (400 kHz), active-low RGB LED retinal pulse dimming, 5.0s watchdog (`NRF_WDT`), retained RAM crash log (`.uninit`), and native USB CDC serial with 1200-baud DFU reset touch.
  - [x] Windows `cmd.exe` toolchain and pure-Python ELF32-to-UF2 packer (`0xADA52840`) in `tools/xiao_cli.py` (`uv run xiao-cli rust-build` and `uv run xiao-cli rust-deploy`).
  - [x] Cross-compilation to `thumbv7em-none-eabihf` verified (`56.0 KB` flash, `4 bytes` static RAM, 219 UF2 blocks, 0 compiler warnings).
  - [x] On-device validation of Rust firmware: verified EasyDMA PDM microphone (span=2849), LSM6DS3TR-C IMU (WHO_AM_I=0x6A, -0.98g), battery rail, CPU thermal, noise floor calibration, and PLL beat clock.
  - [x] Bare-Metal Rust / CircuitPython Dual-Boot & Recovery Package:
    - [x] Discovered bare-metal Rust flashing at `0x1000` erases Nordic SoftDevice S140 (`0x1000`–`0x27000`), preventing standard CircuitPython (`0x27000`) from booting.
    - [x] Generated `build/circuitpython-with-softdevice-xiao-sense.uf2` combining SoftDevice S140 v7.3.0 and CircuitPython 9.2.4 for single-step restoration.
    - [x] Added `uv run xiao-cli python-restore` (aliased `restore`) to restore the `CIRCUITPY` filesystem and automatically deploy `code.py`.
    - [x] Fixed CircuitPython MicroPython-parser syntax errors with adjacent f-strings.
    - [x] Verified full on-device operation via `uv run xiao-cli hil-test`: all 6 hardware checkpoints passed (100% pass) and CJMCU-2812-8 (8-LED NeoPixel stick) verified with startup sweep.
    - [x] Upgraded `xiao-cli monitor` with interactive real-time unbuffered keyboard input (`1`–`4`, `m`, `s`, `z`, `r`) and tuned gesture detection thresholds for natural hand-shaking and table tapping.
    - [x] Continuous Freewheeling (Flywheel) Metronome & Mode 2 Downbeat Tuple Fix: visual flashes continue at exact tempo indefinitely after sound stops, resyncs phase and Beat 1 on sound return, and fixed Mode 2 `"ANCHOR"` 4-tuple unpacking crash.
    - [x] Seamless Mode Switching with Preserved Flywheel Tempo & PLL Lock: changing modes via gestures or serial commands maintains active flywheel tempo and lock with zero timing pause, seamlessly transitioning visual choreography on the next beat.
- [ ] Phase 3 POC: Port click detector, PLL beat clock & mode engine firmware to C++ (`src/xiao_nrf52840_sense/cpp/`)
- [ ] Phase 4: Optimized Native Firmware (C++ / Rust) with Timbre/Harmonicity Rhythm Locking, Instrument Rejection & Custom-Phrase Voice Input (TFLite Micro / CMSIS-NN):
  - [ ] Multi-cluster rhythm locking via 7D onset fingerprint (4-band $L_2$-normalized timbre, Spectral Flatness, autocorrelation Harmonicity, and `20–35 ms` tail decay): listen first for repeated sounds of the same type across candidate clusters and lock onto the strongest periodic click stream
  - [ ] Musical instrument discrimination (e.g. piano rejection): reject transients with sustained string decay (`> 20 ms`), high pitch harmonicity, or low cosine similarity to the locked click centroid
  - [ ] On-device **custom-phrase** voice command control (e.g., *"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"sleep"*) via quantized `int8` DS-CNN in TFLite Micro + CMSIS-NN on the shared 16 kHz PDM DMA stream

---

## Open Issues & Technical Questions

### 1. Acoustic Isolation on Top of a Playing Piano
- **The Challenge**: When the metronome sits directly on the piano, the microphone is subjected to massive acoustic and mechanical vibration:
  - High SPL polyphonic piano chords across 27.5 Hz – 4,186+ Hz.
  - Percussive piano hammer-strike transients that can resemble mechanical clicks.
  - Strong structural vibrations conducted through the piano lid/body directly into the MCU board and IMU.
  - Damper pedal thumps and sympathetic string resonance.
- **Enclosure Advantage**: The microphone is mounted *inside* the metronome housing:
  - The physical escapement click is in extreme near-field proximity to the mic ($<5\text{ cm}$).
  - The wooden/plastic enclosure acts as an acoustic shield against external diffuse sound fields.
  - Can we optimize internal microphone placement and acoustic porting/gasketing to maximize internal-to-external SNR?
- **Intelligent Transient Discrimination**:
  - *DSP Filtering*: First-difference high-pass ($H(z) = 1 - z^{-1}$) cancels low-frequency piano fundamentals, but piano hammer strikes have high-frequency content. Needs evaluation of higher-order bandpass filters (e.g., 2.5 kHz–5.5 kHz) where mechanical escapement clicks have peak spectral density.
  - *Transient Shape Analysis*: Mechanical escapement clicks feature near-instantaneous attack ($< 1\,\text{ms}$) and very rapid decay ($< 5\,\text{ms}$), whereas piano hammer transients have distinctive decay envelopes and immediate harmonic overtone structures.
  - *TinyML / TFLite Micro Classification*: Evaluate a tiny 1D-CNN or spectrogram-based classifier running under CMSIS-NN to distinguish mechanical escapement clicks from piano strikes, room clatter, and voice.
  - *PLL Coasting Resilience*: The autonomous PLL clock already coasts through up to 3 missed beats; can it be tuned to reject out-of-phase spurious piano transients that don't match the active tempo grid?

### 2. Self-Sound Cancellation (Internal Speaker Integration)
- **The Challenge**: When an onboard audio speaker or piezo transducer is added in a future phase (e.g., for audio metronome clicks, voice feedback, or count-in prompts), the microphone will pick up the device's own audio at extreme SPL ($>80\text{ dB}$).
- **Mitigation Architecture**:
  - *Synchronous Blanking / Ducking Gate*: Since the MCU timing engine knows exact sub-millisecond playback timestamps, the click detection input can be momentarily blanked or refractory-suppressed during outbound speaker pulses.
  - *Acoustic Echo Cancellation (AEC)*: For continuous or voice audio, feed the digital playback reference signal into a normalized least-mean-squares (NLMS) filter to subtract self-sound from the microphone stream before transient detection.

---

---

## Backlog

- [ ] [Backlog items in progress]
