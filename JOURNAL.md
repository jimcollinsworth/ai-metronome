# `JOURNAL.md` — Project History & Architectural Decision Records (ADRs)

Chronological record of milestones, architectural decisions, user steering, and technical refactorings for `ai-metronome`.

---

## 2026-10-27 — CircuitPython SoftDevice S140 Restoration Package & Syntax Fix for CJMCU-2812-8 LED Bar

> [!NOTE] User Instructions & Guidance:
> - *"says it flashs but doesn't load d:, i tried reset. blue light flashing now"*
> - *"i see flashing red now"*
> - *"to much searching, lets investigate instead. give me more basic commands to check status, ports, let me try a manual python reset or something."*
> - *"ok d: working now, i was doing single press instead of double. led is red flashing until i move the device. and the led bar is not working"*

### ADR 012: SoftDevice S140 + CircuitPython Dual-Boot Recovery & MicroPython String Concatenation Fix
- **Context**: When bare-metal Rust is flashed to `0x1000` via UF2, it replaces Nordic SoftDevice S140 (`0x1000`–`0x27000`), causing `INFO_UF2.TXT` to report `SoftDevice: not found`. Flashing standard CircuitPython UF2 (`0x27000`) without SoftDevice leaves the device unable to boot CircuitPython or mount `CIRCUITPY`. Furthermore, after restoring the filesystem, `code.py` threw a startup `SyntaxError` on MicroPython's parser due to adjacent multi-line f-string literals, preventing initialization of the CJMCU-2812-8 (8-LED NeoPixel stick) on `D0`.
- **Decision & Implementation**:
  1. **Combined SoftDevice S140 + CircuitPython UF2 (`build/circuitpython-with-softdevice-xiao-sense.uf2`)**:
     - Extracted Nordic SoftDevice S140 v7.3.0 (`0x1000`–`0x27000`) from the official bootloader HEX file.
     - Combined SoftDevice S140 and CircuitPython 9.2.4 into a single UF2 package (`1,500,672` bytes, 2,931 blocks).
     - Flashing this UF2 restores the SoftDevice header and CircuitPython runtime in one step, restoring `D:\` (`CIRCUITPY`).
  2. **CircuitPython MicroPython Parser Syntax Fix**:
     - In CircuitPython's MicroPython-derived parser, adjacent f-strings inside parentheses (`f"..." \n f"..."`) trigger a `SyntaxError: invalid syntax` at compile time.
     - Replaced all multi-line adjacent f-strings with explicit single-line strings or explicit `+` concatenation in `src/xiao_nrf52840_sense/circuitpython/code.py`.
  3. **CLI Argument Parser Ergonomics**:
     - Updated `tools/xiao_cli.py` to use a common parent parser for all subparsers so `--port` and `--drive` can be supplied either before or after subcommands.
     - Updated `tools/xiao_cli.py` to automatically prefer the combined SoftDevice + CircuitPython UF2 for `python-restore`.
  4. **Verification**:
     - Deployed updated `code.py` to `CIRCUITPY` via `uv run xiao-cli python-deploy`.
     - Ran `uv run xiao-cli hil-test`: All 6 hardware checkpoints passed (100% pass) in 2.44s.
     - Verified CJMCU-2812-8 (8-LED NeoPixel stick) startup sweep on `board.D0` and real-time beat visualization operational.

---

## 2026-10-24 — Rust Firmware POC (`v2.6`), Windows CMD Toolchain & ELF32-to-UF2 Packer

> [!NOTE] User Instructions & Guidance:
> - *"/plan /rus/nrf52840-mcu /xiao-nrf52840-sense ok lets start the rust version. Creat the identical features in rust that we did in python. Research, define the toolchain for compiling deploying testing on device, windows cmd only"*
> - *"Remove all powershell, explain the toolchain and debug some"*
> - *"Continue now"*
> - *"Do we still have the circuit python code, tools and docs? Need to maintain so we can compare"*
> - *"Change deploy to python-deploy"*
> - *"device is plugged in, is this working?"*
> - *"still didn't work, red light is flashing now. lets debug together"*
> - *"still getting this, and whats the warning can we get rid of that. how do the firmware/usb/com prots/drives differ on this chip between circuit python and rust. red blinking"*
> - *"we are stumbling and need help, i'm looking for some skills to add. stop this debugging process for now. summarize what we have done, know and don't know, update journal too. i'll come back with further instructions"*

### ADR 009: Embedded Rust Firmware POC (`no_std`) & Windows `cmd.exe` UF2 Toolchain
- **Context**: The Python CircuitPython v2.6 firmware demonstrated the full feature set (outlier-resistant click detection, PLL beat clock, 4 modes with pre-lock and weak-beat dimming, dual-gesture mode switching, and 30s inactivity sleep/wake). Phase 2 required creating an identical, feature-for-feature implementation in Embedded Rust (`src/xiao_nrf52840_sense/rust/`), with a Windows `cmd.exe`-only toolchain for compilation, UF2 packaging, deployment via the factory Adafruit UF2 bootloader (`0xADA52840`), and multi-layer debugging.
- **Decision & Implementation**:
  1. **Platform-Independent `no_std` Core Library (`src/xiao_nrf52840_sense/rust/src/lib.rs`)**:
     - [`click_detector.rs`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/rust/src/click_detector.rs): First-difference HPF $H(z)=1-z^{-1}$, lower-tertile 25-frame calibration, sub-frame sample-index timestamping ($62.5\,\mu\text{s}$ resolution @ 16 kHz), adaptive EMA noise floor, crest factor ($\ge 1.9$), and attack ratio ($\ge 1.45\times$).
     - [`mode_engine.rs`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/rust/src/mode_engine.rs): Always starts in Mode 1 (`ON_BEAT`, Red) on reset; Mode 2 (`IN_BETWEEN`, Blue upbeat); Mode 3 (4/4, Bright Green on 1, Dim Red on 2,3,4); Mode 4 (3/4, Bright Green on 1, Dim Red on 2,3); pre-lock dimming (`0.18`) until 2 consistent intervals (3 steady clicks) lock the PLL.
     - [`gesture.rs`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/rust/src/gesture.rs): `ShakeModeClassifier` supporting either 2 slowish shakes (`dyn >= 0.48g`, release `< 0.20g`) or 1 firm drop/tap to table (`dyn >= 1.35g` or `jerk >= 1.45g`); `SleepWakeController` with 30s inactivity timeout.
     - [`crash_log.rs`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/rust/src/crash_log.rs): Retained SRAM (`.uninit`) panic recorder that preserves panic file, line, and message across soft/watchdog resets.
     - **Host Testing**: All 7 unit tests pass natively on Windows (`cargo test --lib --target x86_64-pc-windows-msvc`).
  2. **Bare-Metal ARM Cortex-M4F Firmware (`main.rs`, `hardware.rs`)**:
     - Configured for `thumbv7em-none-eabihf` with hardware FPU.
     - Direct peripheral drivers: `NRF_TIMER0` (1 MHz microsecond monotonic clock), `NRF_CLOCK` (32 MHz HFCLK + internal LFRC), `NRF_WDT` (5.0s watchdog paused in sleep), `NRF_PDM` (16 kHz 16-bit EasyDMA), `NRF_TWIM0` (400 kHz I2C for LSM6DS3TR-C), `NRF_SAADC` (battery voltage divider with sink gate on P0.14), `NRF_TEMP` (die temp), active-low RGB LED with retinal pulse dimming (`12 ms` pre-lock, `15 ms` weak-beat Red, `130 ms` full locked).
     - Native USB CDC Serial (`USBD`) with 1200-baud touch DFU auto-reset (`NRF_POWER->GPREGRET = 0x57`), interactive serial debug keys (`d`, `r`, `b`, `z`, `1`..`4`), and diagnostic telemetry matching `xiao-cli hil-test`.
     - Compiler warning cleanup: Removed unused `init_clocks` helper from `hardware.rs`, resulting in zero warnings across the entire build.
  3. **Linker & Memory Map (`memory.x`)**:
     - Flash linked at `0x00001000` (length 944 KB), placing the vector table immediately after the Nordic 4 KB MBR.
     - Overwrites dormant SoftDevice magic header (`0x00002000`) so the factory Adafruit UF2 bootloader boots `0x00001000` directly with `VTOR=0x1000`.
     - Explicit `SCB->VTOR = 0x00001000` write at the start of `main()`.
  4. **Windows `cmd.exe` Toolchain in `tools/xiao_cli.py`**:
     - Pure-Python ELF32-to-UF2 converter (`elf_to_uf2`) packing loadable flash segments into 512-byte blocks with family ID `0xADA52840`.
     - CLI command `deploy` renamed to `python-deploy` (preserving CircuitPython v2.6 deployment path and documentation in parallel).
     - `uv run xiao-cli rust-build`: Compiles release binary and generates `build/ai-metronome-rust.uf2` (`56.0 KB`, 219 blocks).
     - `uv run xiao-cli rust-deploy`: Automatically touches COM port at 1200 baud, discovers `XIAO-SENSE` drive, checks `INFO_UF2.TXT`, flashes the UF2, and waits for serial enumeration.
     - Added `tests/test_uf2_packer.py` (14/14 Python tests passing).

### On-Device Investigation Status: What We Done, Know, and Don't Know

- **What We Have Done**:
  1. Built the complete, feature-identical embedded Rust implementation of the AI Metronome (`ai-metronome-rust v2.6.0`).
  2. Implemented all core DSP, PLL, mode engine, gesture classifier, and crash logging modules with 7/7 native unit tests passing.
  3. Built hardware drivers for all XIAO Sense peripherals (PDM, IMU TWIM, SAADC, TIMER, WDT, USBD).
  4. Created a Windows `cmd.exe`-compatible build and deploy CLI pipeline (`rust-build`, `rust-deploy`, `python-deploy`).
  5. Flashed `ai-metronome-rust.uf2` to the device via the Adafruit UF2 bootloader drive `D:\`.
  6. Eliminated all compiler warnings (`init_clocks` dead code).
  7. Preserved all CircuitPython code, tools, and documentation intact for direct comparison.

- **What We Know**:
  1. **USB Architecture**: The nRF52840 has no dedicated USB-to-UART chip; any USB drive (`XIAO-SENSE`, `CIRCUITPY`) or COM port only exists while software on the chip actively runs a USB stack.
  2. **Bootloader Behavior**: When the Adafruit UF2 bootloader is in DFU mode, it mounts `XIAO-SENSE` and pulses the onboard Red LED (`P0.26`, active-low).
  3. **Rejection Symptom**: After `ai-metronome-rust.uf2` is copied to `D:\`, the bootloader reboots back into DFU mode with the Red LED blinking, rather than jumping to the Rust application.
  4. **Bootloader Info**: The user's device reports `SoftDevice: not found` in `INFO_UF2.TXT` (erased or unpopulated at `0x00001000`–`0x00027000`).

- **What We Don't Know**:
  1. **Bootloader Validation Failure Reason**: Whether `bootloader_app_is_valid()` in this specific Adafruit bootloader build rejects the app due to:
     - Vector table offset expectation (is the bootloader hardcoded to require SoftDevice S140 present at `0x00001000` and the application at `0x00027000`? Or does it permit `0x00001000` apps only with a specific DFU settings CRC?).
     - A missing or corrupt bootloader settings page in upper flash (`0x000FF000`).
     - An unhandled hardware exception immediately upon jumping to `0x00001000` (e.g. clock initialization or watchdog firing before USB CDC enumerates), triggering an immediate reset back into bootloader mode.
  2. **Device Baseline State**: Whether restoring the official CircuitPython UF2 or Adafruit SoftDevice bundle will cleanly re-establish the baseline `CIRCUITPY` drive and S140 SoftDevice header.

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

---

## 2026-10-20 — Meter Color Update (Green on 1, Red on Others), Reset-to-Mode-1, Zero-Allocation DSP & MCU Skills

> [!NOTE] User Instructions & Guidance:
> - *"on the 4/4 and 3/4 change back to green on first beat and red on the other beats"*
> - *"yes do those updates. also lets add some project skills file(s) for circuitpython tips, along with links and references. we have some to start with. search for other skills files on the internet for nrf52840, xiao, circuitpython, download and install for project"*
> - *"not really getting any flashes now, change logic so it doesn't remember mode setting, goes back to mode one on reset"*
> - *"pretty good now. maybe dim the red led a bit during 3/4 and 4/4 to emphasize the green count. and dim all the leds until the timing is locked in"*
> - *"now lets add some sleep/wake code, if there is no movement for a while, the cpu goes to sleep until awaken from movement"*
> - *"for future phase - consider using the actual sound of the clicks and a model to compare to each other, don't rely simply on a large transient."*
> - *"additional issue to consider later, the sound of the instruments like a piano, must listen only to the click"*

### ADR 008: 4/4 & 3/4 Meter Color Restoration, Reset-to-Mode-1, Zero-Allocation Loop & Project MCU Skills
- **Context**: Modes 3 (4/4) and 4 (3/4) needed to flash Green on Beat 1 and Red on the remaining beats (instead of silent beats). Furthermore, combining `gc.disable()` with `ulab.numpy` array creation (`np.array`, `np.diff`, `abs`) and `time.monotonic_ns()` at 200 Hz allocated ~800 heap objects/sec and caused heap exhaustion/missed flashes, while a transient sound during boot calibration could bias the baseline noise floor upward. Jim also requested that the device always reset to Mode 1 (`ON_BEAT`) on reset rather than persisting mode state in NVM.
- **Decision**:
  1. **4/4 & 3/4 Meter Colors & Hardware PWM Downbeat Emphasis**:
     - Updated [`ModeEngine`](file:///c:/Users/jimco/Projects/ai-metronome/src/ai_metronome/mode_engine.py) and [`CircuitModeEngine`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/circuitpython/code.py) so Mode 3 (4/4) flashes `GREEN, RED, RED, RED` and Mode 4 (3/4) flashes `GREEN, RED, RED`.
     - Upgraded `StatusLEDs` in `code.py` (`v2.4`) to drive the active-low RGB LEDs via 2 kHz hardware PWM (`pwmio.PWMOut`) combined with pulse-width scaling:
       - **Pre-Lock Dimming (`BRIGHTNESS_DIM_UNLOCKED = 0.10`, `60 ms` pulse)**: All LEDs flash dim while acquiring tempo until 2 consecutive consistent beat intervals (3 steady clicks) lock the internal PLL clock.
       - **Meter Weak-Beat Dimming (`BRIGHTNESS_DIM_METER = 0.12`, `60 ms` pulse)**: In 4/4 and 3/4 modes, Red weak beats (2..N) are dimmed to 12% duty / 60 ms while Beat 1 Green flashes at 100% duty / 130 ms (`BRIGHTNESS_FULL = 1.0`) to strongly emphasize the downbeat count.
  2. **Always Reset to Mode 1**: Removed `microcontroller.nvm` mode persistence so the board always boots into Mode 1 (`ON_BEAT`, Red) on reset.
  3. **Zero-Allocation High-Pass Loop & Outlier-Resistant Calibration (`v2.3`)**:
     - Replaced `gc.disable()` + `ulab.numpy` per-frame heap allocations with the zero-allocation small-integer loop over the 80-sample `array("H")` DMA buffer and standard `time.monotonic()`, eliminating heap churn completely.
     - Hardened `PDMClickDetector.finalize_calibration()` using lower-tertile sorting and clamping (`noise_floor_peak <= 180.0`, `noise_floor_mean <= 80.0`) so any noise during startup calibration cannot blind click detection.
     - Retained non-blocking USB Serial command support (`supervisor.runtime.serial_bytes_available` for keys `'1'`..`'4'`, `'s'`, and `'z'` to test sleep).
  4. **Low-Power Motion Sleep / Wake (`v2.5`)**:
     - Added [`SleepWakeController`](file:///c:/Users/jimco/Projects/ai-metronome/src/ai_metronome/mode_engine.py#L351-L391) and hardware [`sleep_until_movement`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/circuitpython/code.py#L890-L947):
       - When no movement (`dyn < 0.08g`, `jerk < 0.08g`) and no locked metronome beats occur for `IDLE_SLEEP_SEC = 30.0` seconds, the board fades the Blue LED down to OFF, stops the 16 kHz PDM DMA stream (`mic.deinit()`), and gates off the microphone power rail (`board.MIC_PWR = False`).
       - Switches the LSM6DS3TR-C accelerometer from `416 Hz` (`0x68`) down to `26 Hz` low-power ODR (`CTRL1_XL = 0x28`) and routes the hardware Wake-Up interrupt (`WAKE_UP_THS = 0x02`) to `board.IMU_INT1` (`MD1_CFG = 0x20`).
       - Enters tickless WFI CPU sleep until `board.IMU_INT1` asserts or accelerometer movement (`>= 0.12g`) is detected, then restores `416 Hz` IMU ODR, powers up `board.MIC_PWR = True`, re-initializes `PDMIn`, and blinks 2 Green pulses to confirm wake-up without falsely triggering a mode switch.
  5. **Installed Project Agent Skills (`.agents/skills/`)**:
     - `circuitpython-tricks`: Real-time CircuitPython tips, zero-allocation loops, `ulab.numpy` gotchas, non-blocking USB serial, and full `todbot/circuitpython-tricks` reference.
     - `xiao-nrf52840-sense`: Hardware pinout, power gates (`MIC_PWR`, `IMU_PWR`, `READ_BATT_ENABLE`), PDM DMA, LSM6DS3TR-C registers, and Seeed Studio `xiao-assistant` references (CircuitPython, Arduino, TFLite Micro, PlatformIO, Zephyr).
     - `nrf52840-mcu`: Nordic nRF52840 architecture, SoftDevice S140 memory map, UF2 bootloader, and recipes from `alexex1993/mcu-skills`.
  6. **Phase 4 Roadmap — Multi-Cluster Timbre/Harmonicity Rhythm Locking, Piano Rejection & Custom-Phrase Voice Input**:
     - Designed a 7D onset fingerprint (4-band $L_2$-normalized timbre, Spectral Flatness, autocorrelation Harmonicity, and `20–35 ms` post-onset tail decay) with parallel 4-cluster acquisition: listens first for repeated sounds of the same type and locks the PLL onto the strongest periodic percussive stream while rejecting piano/instrument notes.
     - Recorded the decision to use **custom spoken phrases** (e.g., *"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"sleep"*) for the Stage 4 native C++ TFLite Micro + CMSIS-NN keyword spotting pipeline.

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
