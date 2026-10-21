# `JOURNAL.md` — Project History & Architectural Decision Records (ADRs)

Chronological record of milestones, architectural decisions, user steering, and technical refactorings for `ai-metronome`.

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
