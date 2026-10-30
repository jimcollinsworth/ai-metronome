# `PLANNING.md` — Active Backlog & Sprint Milestones

Active backlog and task tracking for `ai-metronome` (Embedded Rust Firmware on Seeed Studio XIAO nRF52840 Sense).

---

## Completed Milestones

### Phase 1: Acoustic Click Detector & 4-Mode PLL Prototype (Archived Reference)
- [x] Archive initial Puck.js BLE prototype under `archive/puck/`
- [x] Design & unit-test PDM high-pass click detection (`H(z) = 1 - z^-1`), adaptive noise floor, crest-factor gate, and autonomous Phase-Locked Loop (PLL) beat clock
- [x] Validate 4-Mode Visual Engine (On-Beat Red, Upbeat Blue, 4/4 Meter, 3/4 Meter), dual-gesture IMU switching (`DOUBLE_SHAKE` & `HARD_DROP`), and 30s inactivity sleep/wake
- [x] Isolate CircuitPython recovery into standalone `tools/restore_circuitpython.py` so daily development is 100% Rust

### Phase 2: Embedded Rust Production Firmware & BLE Tempo Broadcaster (`src/xiao_nrf52840_sense/rust/`)
- [x] Platform-independent `no_std` core library (`click_detector.rs`, `mode_engine.rs`, `gesture.rs`, `crash_log.rs`, `ble_advertiser.rs`):
  - [x] Continuous Freewheeling (Flywheel) coasting after sound stops & phase/downbeat resync on sound return
  - [x] Seamless mode switching (`1`..`4`, `m`, or IMU gesture) preserving locked tempo & phase
  - [x] Dynamic tempo acceleration & deceleration (`prev_dt_sec` two-click transition tracking)
  - [x] Pure-Rust BLE `ADV_NONCONN_IND` PDU builder & **BTHome v2** (`UUID = 0xFCD2`, `Name = "AI-METRO"`) tempo encoder (`0.01 BPM` fractional + integer BPM) for Android **Sensor Logger**
  - [x] 12/12 Rust host unit tests passing (`cargo test --lib --target x86_64-pc-windows-msvc`)
- [x] Bare-Metal ARM Cortex-M4F Hardware Drivers & Fault Hardening (`main.rs`, `hardware.rs`, `memory.x`):
  - [x] Linked at `0x00027000` (above Nordic SoftDevice S140 v7.3.0) with `RAM = 0x20006000..0x2003FEF0` and `_stack_start = 0x2003FEF0` (protecting MBR/S140 low RAM, clean-boot flag at `0x2003FEFC`, and the top 256-byte retained crash log at `0x2003FF00`)
  - [x] Startup FreeRTOS `SysTick` stop, NVIC IRQ masking/clearing (`ICER`/`ICPR`), `SCB->VTOR = 0x00027000`, custom `HardFault` exception frame logger, and non-blocking `DefaultHandler`
  - [x] One-shot `SCB::sys_reset()` clean-boot trampoline (`0x2003FEFC`) after UF2 jump + explicit `.max_packet_size_0(64)` so `NRF_USBD` enumerates on freshly reset silicon every time
  - [x] Direct PAC drivers for `NRF_PDM` (16 kHz EasyDMA), `NRF_TWIM0` (400 kHz I2C for LSM6DS3TR-C), `NRF_RADIO` (2.4 GHz BLE 1 Mbps advertiser on channels 37/38/39), `NRF_SAADC` (battery divider), `NRF_TEMP`, `NRF_TIMER0` (1 MHz monotonic timer), and `NRF_WDT` (5.0s watchdog)
- [x] Streamlined Rust-Only CLI (`tools/xiao_cli.py`):
  - [x] Deterministic commands: `status`, `build`, `deploy`, `test` (7-point HIL verification including `[BLE]`), `monitor`, and `reset`
  - [x] Minimal smoke-test target (`--smoke-test` / `src/bin/deploy_test.rs`) and official `adafruit-nrfutil` S140 v7.3.0 DFU package generation (`build/*.zip` / `--dfu`)
- [x] On-Device HIL Verification (`COM10`):
  - [x] Verified hands-free `uv run xiao-cli deploy --test` passing all 7/7 hardware checkpoints (`POWER_DIAG`, `MIC_POWER`, `MIC_DMA_STREAM`, `IMU_BUS`, `IMU_ACCEL`, `BLE_ADVERTISER` `MAC=EB:E5:CF:40:4D:4A`, `CAL_AND_READY`) in `0.83s`

---

## Active Sprint: Stabilize Core Firmware, Serial Output Optimization & Wake Pattern Reset

- [x] Port CJMCU-2812-8 (8x WS2812B NeoPixel stick on `D0` / `P0.02`) driver to Rust (`RgbLedController` 800 kHz WS2812B driver with startup sweep, 3x green ready blink, and all 4 mode choreographies)
- [x] Put MIDI Bluetooth exploration (`ble_midi.rs`, `btmidi_test.rs`) ON HOLD to focus on core firmware stabilization
- [x] Pare down monitor debug output (eliminate high-frequency beat spam; report only clean locks, tempo adjustments, mode switches, and gestures)
- [x] Fix serial monitor responsiveness (guarantee USB CDC RX reads drain buffered keystrokes regardless of USB poll state)
- [x] Implement clean wake-up reset: wipe tempo/phase/detector state on wake to listen fresh for a new acoustic pattern
- [x] Add quick, low-brightness rainbow sweep across the 8 NeoPixels on boot and wake-up
- [x] Audit embedded Rust codebase for unused code, dead variables, and memory overhead
- [x] Fix PDM microphone continuous streaming (removed per-frame `tasks_stop` that caused 32-sample FIR filter restart transients, reducing span from 3,565 to 107 and noise floor from 320 to 35-58)
- [x] Implement silence coasting timeout (`max_coast_beats = 8`) and fresh tempo onset on sound return after silence gap (>2.0s)
- [x] Implement distinct Cyan radar listening indication on the 8 NeoPixels (`update_listening_bar`) to clearly show when the device is listening for metronome clicks
- [x] Enhance beat scanning telemetry visibility (1/3, 2/3 candidate beats, raw peak, crest factor, noise floor, and threshold in serial output)
- [x] Extend coasting duration from 8 to 24 beats (~12.0s @ 120 BPM) with real-time bridge telemetry (`c` cycle key)
- [x] Add configurable PDM hardware digital gain (`0dB`, `+4.5dB`, `+9dB`, `+13.5dB`, `+18dB`) via `g` cycle key for sensitive distant acoustic pickup
- [x] Filter out accidental desk bumps while locked and require deliberate triple shake (`TripleShake`)
- [x] Build standalone real-time Web Serial visualizer and diagnostics dashboard (`tools/metronome_live.html`)

---

## Next Tasks & Backlog

- [ ] Shake-to-sleep and shake-to-wake gesture recognition (triple shake)
- [ ] Time-limited BLE advertising on wake-up (minimal 1 Hz broadcast for 2–3 minutes after wake, then turn off radio for acoustic SNR)
- [ ] Verify tempo lock accuracy across various tempos (60, 90, 120, 160 BPM) with Jim's acoustic metronome

---

## On-Hold / Future Backlog

1. **BLE-MIDI / Web Bluetooth Dashboard**:
   - On hold. Standalone proof-of-concept files (`ble_midi.rs`, `btmidi_test.rs`, `tools/btmidi_config.html`, `tools/test_btmidi.py`) preserved for future reference but excluded from active builds.
2. **Acoustic Isolation on Top of a Playing Piano**:
   - Evaluate 2.5–5.5 kHz bandpass filtering and 7D onset fingerprinting (Spectral Flatness, autocorrelation Harmonicity, and 20–35 ms tail decay) in Rust to reject sustained piano string notes while locking onto dry mechanical escapement clicks.
3. **Self-Sound Cancellation (Future Speaker Output)**:
   - Implement synchronous playback blanking gates when an onboard piezo/speaker is added.
4. **On-Device Voice Command Control**:
   - Evaluate quantized `int8` keyword spotting (*"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"sleep"*) on the shared 16 kHz PDM DMA stream.
