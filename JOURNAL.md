# `JOURNAL.md` — Project History & Architectural Decision Records (ADRs)

Chronological record of milestones, architectural decisions, user steering, and technical refactorings for `ai-metronome`.

---

## 2026-10-21 — CJMCU-2812-8 (8x NeoPixel Stick) Integration & Subtle Multi-Mode Visualizer

> [!NOTE] User Instructions & Guidance:
> - *"ok leds work, lets add something very simple to the app now. each of the four modes should have some meaningful effect, keep things very subtle though"*

### ADR 009: Unified Multi-Mode Visualizer with Subtle Peripheral NeoPixel Cueing
- **Context**: The user wired an 8-LED WS2812B NeoPixel stick (CJMCU-2812-8) to `board.D0` on the XIAO nRF52840 Sense. Initial testing at 12% brightness with narrow 2-pixel clusters was too faint under ambient room light. The user requested a visual hardware self-test on startup to confirm LED stick operation.
- **Decision**:
  1. **Startup Hardware Self-Test & 3-Blink Green Ready Confirmation**:
     - Added `run_startup_pattern()` executing during `init_hardware`: a rapid cyan/blue sweep across pixels 0 through 7 (35ms per pixel) followed by a 120ms warm amber pulse.
     - Updated `signal_init_ok()` to blink all 8 NeoPixels in vivid green (`0, 255, 40`) 3 times in sync with the onboard Green LED.
  2. **Zero-Dependency Native Driver (`neopixel_write`)**:
     - Integrated unified `StatusLEDs` controller directly into `src/xiao_nrf52840_sense/circuitpython/code.py` using CircuitPython's built-in `neopixel_write` module, avoiding external `/lib` dependencies.
     - Pre-allocated 24-byte pixel buffer in `__init__` for zero heap allocations during the 5ms / ~147 Hz audio DMA loop.
  3. **Vivid Peripheral Visual Choreography (22% Base Brightness)**:
     - Boosted brightness from 12% to 22% (`NEOPIXEL_BRIGHTNESS = 0.22`) to match the working hardware demo level without harsh glare.
     - **Mode 1 (On-Beat 1x)**: Pendulum rock (tick-tock) alternating between left cluster `[1, 2, 3]` and right cluster `[4, 5, 6]` in warm amber-red `(255, 40, 0)`.
     - **Mode 2 (In-Between / Upbeat &)**: Rhythmic center anchor `[3, 4]` in deep purple `(180, 0, 220)` on physical clicks + cyan-blue outer wing pulse `[0, 1]` & `[6, 7]` on syncopated off-beats.
     - **Mode 3 (4/4 Meter)**: 2-LED progressive measure bar stepping across the 8 pixels: Beat 1 = `[0, 1]` (accent green), Beat 2 = `[2, 3]` (warm amber), Beat 3 = `[4, 5]` (vivid teal), Beat 4 = `[6, 7]` (warm amber).
     - **Mode 4 (3/4 Meter)**: Symmetrical waltz triple-step (3 - 2 - 3): Beat 1 = `[0, 1, 2]` (accent green), Beat 2 = `[3, 4]` (warm amber), Beat 3 = `[5, 6, 7]` (warm amber).
  4. **Verification**:
     - Deployed directly to hardware via `uv run xiao-cli deploy`.
     - Verified passing all 6 hardware checkpoints in `xiao-cli hil-test` (`COM5` / `F:\`). All 12 host unit tests continue to pass.

---

## 2026-10-21 — Architectural Review: Piano Acoustic Isolation, Transient Discrimination & Self-Sound Cancellation

> [!NOTE] User Instructions & Guidance:
> - *"reviewing readme - add project description and purpose, a few paragraphs. add how the modes are switched"*
> - *"reviewing rroadmap - "*
> - *"planning - issues/questions - the microphone and transient processing must work even if the metronome is on top of a playing piano - mic is inside metronome so that helps, but we might need to do more intelligent 'listening' of the sounds and actively (with filters/models) hear the click but drown out the other instruments (including our own sounds when a speaker is added)"*

### ADR 008: Hostile Acoustic Environment Strategy (Piano Isolation & Internal Speaker AEC)
- **Context**: The device is intended to sit directly on or inside a physical mechanical metronome positioned on top of a piano during live playing. This introduces extreme acoustic and mechanical noise: polyphonic piano chords across 27.5 Hz – 4,186+ Hz, percussive hammer strikes, pedal mechanical thumps, and acoustic feedback from any future onboard speaker.
- **Decision**:
  1. **Documentation Updates**:
     - Updated `README.md` with comprehensive project description, operational purpose, full breakdown of the 4-mode visual engine, and a complete reference for the `xiao-cli` developer tool (`status`, `deploy`, `hil-test`, `monitor`, `reset`, overrides).
     - Updated `ROADMAP.md` Section 1 with the multi-tiered acoustic isolation strategy (enclosure advantage, transient DSP, TinyML classification, active echo cancellation).
     - Expanded `PLANNING.md` with detailed Open Issues and Technical Questions covering piano hammer onset rejection, structural vibration coupling, and reference-based self-sound cancellation.
  2. **Technical Architecture Roadmap**:
     - *Physical Housing Advantage*: Take advantage of the microphone mounted inside the metronome casing for extreme near-field proximity to the escapement mechanism.
     - *Acoustic Discrimination Filterbank*: Investigate 2.5 kHz–5.5 kHz bandpass filtering, envelope attack-slope gating ($<1.5\,\text{ms}$ rise time), and crest factor metrics to isolate impulsive non-harmonic mechanical clicks from harmonic piano strings.
     - *TinyML / TFLite Micro Classification*: Plan for an on-device transient classifier running on the Cortex-M4F to identify authentic escapement clicks vs. musical instruments.
     - *Speaker Blanking / Echo Cancellation*: Design synchronous timing-gate blanking and NLMS reference-based acoustic echo cancellation (AEC) into the roadmap before adding onboard speaker hardware.

---

## 2026-10-20 — Autonomous Phase-Locked Loop (PLL) Beat Clock, Sensitivity Tuning & TFLite Micro Roadmap

> [!NOTE] User Instructions & Guidance:
> - *"ok, works ok, commit work. mode switch is a bit too sensitive now, back off a little. then work on improving accuracy of the flashing - the mechanical click is actually very accurate to my ears, but our software based interpretation of that click results in timing errors on the led flashing, maybe the led needs it's own internal accurate clock loop that is continuously adjusted by the click recognition. code, deploy and test these improvements. add future phase for optimized native code with voice input (tflite)"*

### ADR 007: Autonomous PLL Beat Clock (`BeatPLL`), Sub-Frame Click Indexing & TFLite Voice Roadmap
- **Context**: Reactive LED flashing driven directly by software frame detection suffered from variable buffer alignment jitter, boundary-straddling transient rejection, and serial I/O latency. Additionally, the accelerometer gesture thresholds (`0.26g` slow shake / `0.85g` drop) were slightly too sensitive during casual handling.
- **Decision**:
  1. **Autonomous Internal PLL Beat Clock (`ModeEngine` / `CircuitModeEngine`)**:
     - Decoupled LED flashing from raw frame-by-frame click triggers by introducing an internal Phase-Locked Loop oscillator (`period`, `next_beat_time`, `last_beat_time`).
     - Once 2 clicks establish tempo lock, the internal clock autonomously fires LED flashes on schedule (with a 3.0 ms anticipatory lead across 4.9 ms / 200 Hz audio frames) and coasts smoothly across up to 3 missed clicks before auto-unlocking.
     - Recognized clicks compute a **sub-frame sample-accurate timestamp** ($62.5\,\mu\text{s}$ resolution via `peak_idx` at 16 kHz) and apply proportional phase correction ($\alpha_{\phi} = 0.35$) and integral frequency correction ($\alpha_f = 0.22$) without double-flashing.
     - Fixed boundary-straddling click rejection by comparing `hp_peak` against `prev_quiet_peak` rather than the immediately preceding frame's peak.
  2. **Backed-Off Gesture Thresholds**:
     - Raised `slow_shake_dyn_g` from `0.26g` to `0.48g` (release `< 0.20g`, min stroke gap `0.15s`, debounce `1.0s`) and `hard_drop_dyn_g` from `0.85g` to `1.35g` (`hard_drop_jerk_g = 1.45g`).
  3. **Future Phase — Native Firmware with TFLite Micro Voice Input**:
     - Added Phase 4 to `PLANNING.md` and `ROADMAP.md` for native C++/Rust firmware incorporating TensorFlow Lite for Microcontrollers (TFLite Micro + CMSIS-NN) keyword spotting on the shared 16 kHz PDM DMA stream.

---

## 2026-10-20 — 4-Mode Streamlining, Dual-Gesture Detector & HIL CLI Test Runner

> [!NOTE] User Instructions & Guidance:
> - *"remove double time option. increase led blink flash length a bit, still not bright but probaby a limitation of the device. don't bother with mocked tests. add the cli test runner so we can do HIL for development (push code) and testing"*
> - *"also the shaking seemed unreliable. make it easier to trigger - i do 2 slowish shakes, or more of a harder drop to the table, add a clear confirmation"*

### ADR 006: 4-Mode Lineup, High-Rate Dual-Gesture Detection & `xiao-cli` HIL Tooling
- **Context**: Double-time mode was removed in favor of a cleaner 4-mode cycle (1: On-Beat, 2: Upbeat, 3: 4/4 Meter, 4: 3/4 Meter). Additionally, checking the accelerometer every 4th frame at a high $2.3g$ threshold missed both brief table drops (<10ms) and gentle slow shakes ($\sim 1.3g$). We also needed a fast CLI tool to push firmware and run automated Hardware-in-the-Loop (HIL) tests directly on the connected XIAO nRF52840 Sense.
- **Decision**:
  1. **4-Mode Sequencer & Extended 130ms Pulse Width**:
     - Modes: `1` = On-Beat (Red), `2` = Upbeat (Blue at $t + \frac{\text{IOI}}{2}$), `3` = 4/4 Meter (Green on 1, silent 2–4), `4` = 3/4 Meter (Green on 1, silent 2–3).
     - Increased `LED_FLASH_SEC` to `0.130` (130ms) for maximum perceived retinal brightness.
  2. **125 Hz Dual-Gesture Detection & Bright White Confirmation**:
     - Configured the LSM6DS3TR-C to 416 Hz ODR ($\pm 4g$, `CTRL1_XL = 0x68`) over a 400 kHz I2C bus and polled on every 8ms audio frame (125 Hz).
     - **Gesture A (`HARD_DROP`)**: Single firmer drop/knock onto the table ($||a| - 1g| \ge 0.85g$ or 3D jerk $\ge 0.90g$).
     - **Gesture B (`DOUBLE_SHAKE`)**: Two slowish hand shakes ($||a| - 1g| \ge 0.26g$ with hysteresis release below $0.14g$) within a 1.6s window.
     - **Clear Visual Confirmation**: Fires a 350ms **Bright White** burst (all 3 RGB diodes lit simultaneously), pauses 220ms, and then blinks $N$ distinct 200ms pulses (`1..4`) in the new mode's color while resetting the audio click refractory timer.
  3. **Automated HIL CLI Runner (`tools/xiao_cli.py`)**:
     - Built `uv run xiao-cli` with `status`, `deploy` (`push`), `hil-test` (`test`), `monitor` (`logs`), and `reset` commands.
     - Verified live on `D:\` (`CIRCUITPY`) and `COM9` (`2886:0045`), passing all 6 hardware checks (`POWER_DIAG`, `MIC_POWER`, `MIC_DMA_STREAM`, `IMU_BUS`, `IMU_ACCEL`, `CAL_AND_READY`).

---

## 2026-10-20 — 5-Mode Flash Sequencer, Accelerometer Shake Switching & Brightness Boost

> [!NOTE] User Instructions & Guidance:
> - *"i want to add some mode switching, like switch between on beat and inbetween the clicks for the flashing, or double time 2 flashes per click, or on every 3rd or 4 click. what are our easy options - shaking? speech commands? knock twice on table? don't want more hardware"*
> - *"option 1 please but mode 4 just green on 1 no led on others, and then add mode 5 for 3/4. make the leds brighter for the beat too"*

### ADR 005: 5-Mode Flash Sequencer, Onboard IMU Shake Switching & Pulse-Width Brightness
- **Context**: The metronome POC needed to support rhythm variations (on-beat, upbeat, double-time, 4/4 meter, and 3/4 meter) and interactive mode cycling without requiring extra hardware buttons or external components. LED visibility also needed to be noticeably brighter.
- **Decision**:
  1. **5 Visual Flash Modes**:
     - **Mode 1 (On-Beat)**: Red flash on every detected click ($1\times$).
     - **Mode 2 (Upbeat)**: Blue flash scheduled halfway between clicks ($t_{\text{click}} + \frac{\text{IOI}}{2}$).
     - **Mode 3 (Double-Time)**: $2\times$ flashes per click (Red on click, Blue on upbeat).
     - **Mode 4 (4/4 Meter)**: Green flash on Beat 1, silent (no LED) on Beats 2, 3, 4. Auto-resets to Beat 1 after 2-second silence.
     - **Mode 5 (3/4 Meter)**: Green flash on Beat 1, silent (no LED) on Beats 2, 3. Auto-resets to Beat 1 after 2-second silence.
  2. **Zero Extra Hardware Interaction**:
     - Utilized the onboard ST LSM6DS3TR-C 6-axis IMU on internal I2C bus (`board.IMU_SCL` / `board.IMU_SDA`) powered via `board.IMU_PWR`.
     - Supports both the official `adafruit_lsm6ds` library (if present in `/lib`) and direct hardware register access (`CTRL1_XL = 0x10`, `OUTX_L_XL = 0x28`) so `code.py` functions with zero external dependencies.
     - Configured a threshold of $|a| > 2.3g$ with a $0.6\text{s}$ debounce window. On shake, cycles mode and pulses Cyan LED $N$ times corresponding to the selected mode number.
  3. **Visual Brightness Enhancement**:
     - Increased flash duration from $45\text{ms}$ to $75\text{ms}$ (`LED_FLASH_SEC = 0.075`), nearly doubling retinal photon integration and perceived brightness while remaining crisp up to 240+ BPM.

---

## 2026-10-20 — Hardware Pivot to XIAO nRF52840 Sense & CircuitPython Click Detector POC

> [!NOTE] User Instructions & Guidance:
> - *"ok, the puck was a good first attemp, but not worth it without a mic. instead we will use my xiao nrf52840 sense mcu - with microphone. commit all the current work. next we do a new poc using the nrf, initially lets code in circuit python, but then try c++ and or rust. all the puck code/tests can be moved into an archive directory. create the first version of our app in circuit python, init code checks microphone, anything else important, uses onboard led to indicate init and ok. then listens for the click, and blinks the led red to go along. use a good algorythm for the type of microphone and chip we have."*

### ADR 004: Hardware Pivot to Seeed Studio XIAO nRF52840 Sense & High-Pass PDM Onset Detection
- **Context**: Puck.js lacks an onboard microphone, making acoustic metronome click detection impractical without external circuitry. The Seeed Studio XIAO nRF52840 Sense features an integrated digital PDM MEMS microphone (`MSM261D3526H1CPM`), 64 MHz Cortex-M4F DSP, and active-low RGB LED.
- **Decision**:
  1. Committed and archived all Puck.js BLE CLI/TUI code and tests under `archive/puck/`.
  2. Implemented a single-pass first-difference high-pass filter ($H(z) = 1 - z^{-1}$) over 128-sample (`8 ms` @ 16 kHz) unsigned 16-bit DMA buffers (`src/ai_metronome/click_detector.py` and embedded in `src/xiao_nrf52840_sense/circuitpython/code.py`). This cancels DC bias in one pass, rejects low-frequency room rumble/hum, and isolates sharp 1–6 kHz percussive click transients using integer arithmetic inside the sample loop.
  3. Combined adaptive EMA noise-floor tracking, crest-factor verification, rising-edge attack slope detection, and a 120 ms refractory window to prevent false triggers and echo double-blinks while estimating live BPM.
  4. Configured onboard active-low RGB LED status feedback: Blue during hardware init & ambient noise calibration, 3 Green blinks on init OK, and a 45 ms Red flash synchronized with each detected click.

---

## 2026-10-19 — Refactoring Puck.js BLE Tooling to Lightweight Operational CLI

> [!NOTE] User Instructions & Guidance:
> - Removed the heavy JavaScript Intellisense engine and the large 460KB JSON reference file.
> - Resolved Windows console ANSI display character corruption (`?[36m`).
> - Fixed command exit inconsistency so `q`, `quit`, and `exit` cleanly terminate the console across all prompts.
> - Streamlined the TUI to a lean, bulletproof terminal console focused strictly on operational commands (`scan`, `connect`, `status`, `reset`, `diag`, `upload`) and direct REPL execution.

### ADR 003: Lean Windows BLE Tooling & Windows Console Processing
- **Decision**: Purged `prompt-toolkit`, `rich`, and the static JSON reference, enabled Windows Virtual Terminal processing, and unified console commands.

---

## 2026-10-18 — Project Scaffolding & Initial Toolchain Setup

### ADR 001: Modern Python Toolchain with `uv`
- **Decision**: Adopt Astral `uv` for package management, virtual environment isolation, and script execution.
