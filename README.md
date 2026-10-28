# ai-metronome

`ai-metronome` is an embedded acoustic-synchronizing companion for musicians running on the **Seeed Studio XIAO nRF52840 Sense** in **Embedded Rust (`no_std`)**. Rather than replacing a traditional physical metronome, it augments it: listening to physical escapement clicks via the onboard 16 kHz digital PDM MEMS microphone, locking onto the tempo with an autonomous Phase-Locked Loop (PLL) beat clock, flashing synchronized visual cues across 4 rhythm modes, and broadcasting real-time tempo telemetry over **Bluetooth Low Energy (BLE BTHome v2)** to Android **Sensor Logger**.

---

## Core Features & Operating Modes

### 1. Continuous Freewheeling (Flywheel) PLL Beat Clock
- **Outlier-Resistant Noise Floor Calibration**: Samples 25 startup frames and uses the lower-tertile peak so ambient sounds during boot never blind the detector.
- **Sub-Frame Onset Accuracy**: First-difference high-pass filter ($H(z)=1-z^{-1}$) with $62.5\,\mu\text{s}$ sample-index localization, crest-factor verification ($\ge 1.9$), and attack-slope gating.
- **Continuous Flywheel Coasting**: Once locked (3 steady clicks / 2 consistent intervals), the internal PLL clock continues flashing at the exact tempo indefinitely even after sound stops, and immediately resynchronizes phase and downbeat when sound returns.
- **Dynamic Acceleration & Deceleration**: Tracks two-click interval transitions (`prev_dt_sec`) so slowing down or speeding up adapts immediately without harmonic trapping.

### 2. 4 Visual Rhythm Modes & Seamless Mode Switching
Switching modes (via physical IMU gestures or USB serial commands) preserves the locked flywheel tempo and phase without pausing the beat clock:
- **Mode 1 — On-Beat (`RED`)**: Flashes Red on every beat ($1\times$); always the default mode on reset.
- **Mode 2 — Upbeat / In-Between (`BLUE`)**: Flashes Blue halfway between beats ($t + 0.5 \times \text{period}$).
- **Mode 3 — 4/4 Meter (`GREEN` = 1, `RED` = 2, 3, 4)**: Bright Green downbeat on Beat 1, dimmed Red (`20%`) on Beats 2, 3, and 4.
- **Mode 4 — 3/4 Meter (`GREEN` = 1, `RED` = 2, 3)**: Bright Green downbeat on Beat 1, dimmed Red (`20%`) on Beats 2 and 3.
- **Pre-Lock Dimming**: All flashes are dimmed (`18%` / `12 ms` pulse) until the PLL locks onto a steady tempo.

### 3. Dual-Gesture IMU Mode Switching & 30s Inactivity Sleep
Polled at 50 Hz over 400 kHz I2C (`LSM6DS3TR-C` @ 416 Hz ODR):
- **Double Shake**: Two back-and-forth hand shakes cycle to the next mode.
- **Firm Table Tap / Drop**: A single firm tap/drop onto a table cycles to the next mode.
- **30s Low-Power Motion Sleep**: After 30 seconds without movement or locked beats, the firmware fades the Blue LED down, powers off the PDM microphone, puts the IMU into 26 Hz low-power mode, and sleeps until movement wakes it (`2x Green` blink confirmation).

### 4. BLE Tempo Broadcast (`AI-METRO` / BTHome v2 `0xFCD2`)
- Bare-metal `NRF_RADIO` 2.4 GHz `Ble_1Mbit` (+4 dBm) advertiser broadcasting across primary BLE channels **37 (2402 MHz)**, **38 (2426 MHz)**, and **39 (2480 MHz)**.
- Transmits **BTHome v2** (`UUID = 0xFCD2`) service data packets at 5 Hz (`200 ms`) and immediately on every beat, encoding fractional BPM (`0.01 BPM` resolution via Object `0x02`) and integer BPM (Object `0x3D`) for zero-configuration graphing in Android **Sensor Logger** and **nRF Connect**.

---

## Repository Structure

```text
ai-metronome/
├── .agents/skills/                 # MCU & hardware skills (nrf52840-mcu, xiao-nrf52840-sense)
├── archive/puck/                   # Archived Puck.js prototype
├── build/                          # Compiled UF2 & official Nordic DFU .zip images
├── src/
│   ├── ai_metronome/               # Python reference algorithms for unit testing
│   └── xiao_nrf52840_sense/
│       ├── rust/                   # Primary Embedded Rust Firmware (no_std, Cortex-M4F)
│       │   ├── src/
│       │   │   ├── bin/
│       │   │   │   └── deploy_test.rs # Minimal USB CDC + Green LED smoke-test binary (--smoke-test)
│       │   │   ├── lib.rs          # Platform-independent no_std library root
│       │   │   ├── main.rs         # Bare-metal entry, clean-boot trampoline, USB CDC & 200Hz loop
│       │   │   ├── hardware.rs     # Direct PAC drivers (PDM, TWIM0, RADIO, SAADC, TIMER0, WDT)
│       │   │   ├── ble_advertiser.rs # Pure-Rust BLE PDU & BTHome v2 packet builder
│       │   │   ├── click_detector.rs # First-difference HPF & outlier-resistant click detector
│       │   │   ├── mode_engine.rs  # 4-mode continuous flywheel PLL sequencer
│       │   │   ├── gesture.rs      # Shake/drop gesture classifier & 30s sleep controller
│       │   │   └── crash_log.rs    # Retained SRAM (0x2003FF00) panic & HardFault logger
│       │   ├── Cargo.toml
│       │   └── memory.x            # S140 v7.3.0 flash (0x27000) & RAM (0x20006000) linker map
│       └── circuitpython/          # Archived CircuitPython prototype (code.py)
├── tests/                          # Python & UF2 packer unit tests
├── tools/
│   ├── xiao_cli.py                 # Rust-only build, deploy, HIL test & monitor CLI
│   └── restore_circuitpython.py    # Standalone emergency recovery for CircuitPython prototype
├── AGENTS.md                       # Operational rules & governance boundaries
├── JOURNAL.md                      # Architectural Decision Records (ADRs) & project log
├── PLANNING.md                     # Active sprint milestones & backlog
├── ROADMAP.md                      # Long-term acoustic isolation & TinyML vision
└── TESTING.md                      # Verification pyramid & test execution guide
```

---

## Rust Development & Hardware Workflow (`xiao-cli`)

All commands run in standard Windows `cmd.exe` via `uv run xiao-cli`:

```cmd
:: 1. Check XIAO-SENSE bootloader drive or Rust USB CDC serial port
uv run xiao-cli status

:: 2. Compile Rust firmware (thumbv7em-none-eabihf) and pack build\ai-metronome-rust.uf2
uv run xiao-cli build

:: 3. Build, flash to XIAO-SENSE, and run 7-point on-device HIL verification
uv run xiao-cli deploy --test

:: 3b. (Optional) Build, flash, and verify minimal USB serial smoke-test binary
uv run xiao-cli deploy --smoke-test

:: 4. Run 7-point HIL verification against currently running Rust firmware
uv run xiao-cli test

:: 5. Open interactive live serial console (keys: 1..4, m, d/s, r, z, b)
uv run xiao-cli monitor
```

### Interactive Serial Console Keys (`xiao-cli monitor`)
- **`1`..`4`**: Switch directly to Mode 1 (On-Beat), Mode 2 (Upbeat), Mode 3 (4/4), or Mode 4 (3/4).
- **`m`**: Cycle to the next mode seamlessly.
- **`d` / `s`**: Dump internal state (DSP noise floor, PLL lock/BPM, BLE broadcast counter, IMU $g$/jerk, battery voltage, CPU die temp).
- **`r`**: Replay the full 7-point hardware self-test banner (`[DIAG]`, `[MIC]`, `[IMU]`, `[BLE]`, `[CAL]`, `[READY]`).
- **`z`**: Trigger immediate low-power sleep mode test (move board to wake).
- **`b`**: Reboot directly into the `XIAO-SENSE` UF2 bootloader drive (`D:\`).

---

## Running Unit Tests

```cmd
:: Run Rust no_std core library unit tests (12 tests: BLE, PLL, DSP, Gesture, CrashLog)
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc

:: Run Python UF2 packer & reference algorithm tests (17 tests)
uv run pytest -v
```

*(Note: If you ever need to restore the archived CircuitPython prototype onto the board, run `uv run python tools/restore_circuitpython.py`.)*
