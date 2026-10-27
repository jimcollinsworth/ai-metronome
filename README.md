# ai-metronome

`ai-metronome` is an intelligent, embedded acoustic-synchronizing companion designed for musicians. Rather than replacing the beloved mechanical presence and tactile rhythm of a traditional physical metronome, `ai-metronome` augments it: listening to physical escapement clicks in real time through an onboard digital MEMS microphone, locking onto the tempo with an autonomous Phase-Locked Loop (PLL) beat clock, and providing precise, jitter-free visual and meter feedback.

The system is engineered to sit directly on or inside a physical metronome enclosure—even when perched atop an actively played piano. By leveraging physical proximity, enclosure resonance advantages, and intelligent digital signal processing (band-limited transient filtering, attack-slope gating, and adaptive noise tracking), the firmware isolates sharp mechanical tick transients from ambient music, room reverberation, and polyphonic piano chords.

With an internal PLL oscillator driving LED timing, visual pulses remain rock-solid and impervious to frame-level software latency or occasional acoustic dropouts. The device supports multiple musical timing modes—such as on-beat synchronization, upbeat/in-between pulses, and measure downbeat accents for 4/4 and 3/4 meters—all without requiring screens, menus, or external buttons.

---

## Operating Modes & Gesture Switching

The metronome features a streamlined 4-mode visual timing engine. It requires zero extra hardware, wires, or pushbuttons—mode selection is controlled entirely through the onboard 6-axis inertial measurement unit (IMU).

### How Modes Are Switched
Mode cycling uses intuitive physical gestures detected by the onboard accelerometer:
1. **Two Slowish Shakes**: Pick up the unit and shake it back and forth twice.
2. **Single Firm Drop / Table Knock**: Set or tap the unit down firmly onto the table or piano surface.

### Mode Confirmation
Upon recognizing either gesture, the device signals an unmistakable confirmation:
- A **350 ms Bright White burst** (all RGB diodes illuminated simultaneously).
- A brief pause, followed by **$N$ distinct pulses** in the new mode's color to indicate the active mode number ($1$ to $4$).
- Refractory audio timers reset automatically so the switch gesture never causes a false beat trigger.

### Active Mode Lineup
- **Mode 1 — On-Beat (Red)**: Emits a crisp Red flash synchronized directly with every physical click ($1\times$).
- **Mode 2 — Upbeat / In-Between (Blue)**: Emits a Blue flash precisely halfway between beats ($t + \frac{\text{IOI}}{2}$), ideal for practicing syncopation and subdividing time.
- **Mode 3 — 4/4 Meter (Green)**: Emits a Green flash on Beat 1 (downbeat) and remains dark on Beats 2, 3, and 4. Auto-resets to Beat 1 after 2 seconds of silence.
- **Mode 4 — 3/4 Meter (Green)**: Emits a Green flash on Beat 1 (downbeat) and remains dark on Beats 2 and 3. Auto-resets to Beat 1 after 2 seconds of silence.

---

## Architecture & Layout

```text
ai-metronome/
├── .agents/                        # Agent operating rules and workflow specifications
│   └── skills/                     # Domain MCU skills (circuitpython, xiao, nrf52840)
├── archive/
│   └── puck/                       # Archived Puck.js BLE CLI/TUI prototype & tests
├── docs/                           # Documentation and architecture design specifications
├── src/
│   ├── ai_metronome/               # Host-testable core algorithms (PDM click detector)
│   └── xiao_nrf52840_sense/        # Target MCU firmware implementations
│       ├── circuitpython/
│       │   └── code.py             # Self-contained CircuitPython click detector POC
│       ├── cpp/                    # Planned C++ firmware implementation
│       └── rust/                   # Embedded Rust firmware implementation (no_std)
├── tests/                          # Automated unit test suites
├── tools/                          # Developer, CLI, and deployment utilities
├── AGENTS.md                       # Universal agent operating guidelines
├── JOURNAL.md                      # Chronological log & Architectural Decision Records (ADRs)
├── PLANNING.md                     # Active backlog & sprint task tracking
├── ROADMAP.md                      # Long-term vision and feature backlog
├── TESTING.md                      # Testing strategy and execution guide
├── pyproject.toml                  # Project metadata and dependencies
└── main.py                         # Application entry point
```

---

## Development & Hardware Tooling (`xiao-cli`)

The repository includes a dedicated Hardware-in-the-Loop (HIL) command-line utility ([`tools/xiao_cli.py`](file:///d:/projects/ai-metronome/tools/xiao_cli.py)) registered as `xiao-cli`. It automatically auto-discovers mounted `CIRCUITPY` USB drives and XIAO serial COM ports without requiring manual configuration.

Execute via `uv run xiao-cli <command>`:

### 1. Device Discovery & Health Check (`status`)
Inspect connected hardware, mounted flash drives, CircuitPython runtime version, and USB serial endpoints:
```bash
uv run xiao-cli status
```
*Outputs drive mount path (e.g. `D:\`), volume label, `boot_out.txt` build info, COM port (e.g. `COM9`), and USB VID/PID.*

### 2. Deploying CircuitPython Firmware (`python-deploy`)
Copies `code.py` to the mounted `CIRCUITPY` flash drive. CircuitPython automatically reloads upon file write:
```bash
# Push default firmware (src/xiao_nrf52840_sense/circuitpython/code.py)
uv run xiao-cli python-deploy

# Push and immediately trigger automated hardware-in-the-loop verification
uv run xiao-cli python-deploy --test

# Deploy a specific custom source file
uv run xiao-cli python-deploy --file path/to/my_code.py
```
*(Aliases `deploy` and `push` are also supported for convenience: `uv run xiao-cli deploy`.)*

### 3. Restoring CircuitPython from Rust (`python-restore`)
When running bare-metal Rust, the `CIRCUITPY` USB drive is replaced by native Rust execution. To switch back to CircuitPython and restore the `CIRCUITPY` (`D:\`) filesystem in one step:
```bash
# Restore CircuitPython runtime and automatically deploy latest code.py
uv run xiao-cli python-restore

# Restore, deploy, and immediately run automated hardware verification
uv run xiao-cli python-restore --test
```
*What this automated command does:*
1. Automatically triggers the 1200-baud DFU bootloader (or prompts to double-tap Reset) so `XIAO-SENSE` mounts on `D:\`.
2. Flashes the official CircuitPython runtime UF2 (cached locally in `build/`).
3. Waits for CircuitPython to format/mount the onboard SPI flash filesystem as `CIRCUITPY` (`D:\`).
4. Copies `src/xiao_nrf52840_sense/circuitpython/code.py` to `CIRCUITPY/code.py`.

### 4. Automated On-Device Verification (`hil-test` / `test`)
Connects to the board over serial, issues a clean soft-reboot, and validates the 6-point hardware diagnostic test suite in real time:
```bash
# Run HIL tests against currently flashed firmware
uv run xiao-cli hil-test

# Deploy latest code first, then run tests
uv run xiao-cli hil-test --deploy

# Run verification and keep listening to live clicks & IMU gestures for 15 seconds
uv run xiao-cli hil-test --listen-sec 15
```
**Automated Hardware Checks Performed:**
1. `POWER_DIAG`: Battery voltage, charge state, CPU temperature, and free RAM/heap.
2. `MIC_POWER`: `board.MIC_PWR` pin activation and power rail stabilization.
3. `MIC_DMA_STREAM`: `audiobusio.PDMIn` DMA ring buffer allocation and live sample acquisition.
4. `IMU_BUS`: LSM6DS3TR-C power rail (`board.IMU_PWR`) and internal I2C communication.
5. `IMU_ACCEL`: Accelerometer initialization and static 3-axis gravity readings (~1.0g vector magnitude).
6. `CAL_AND_READY`: Dynamic ambient noise floor calibration and ready state transition.

### 5. Real-Time Telemetry Monitor (`monitor` / `logs`)
Streams live serial diagnostics at 115200 baud, showing click detections, noise floor shifts, BPM calculations, and IMU gestures:
```bash
# Stream continuously (exit with Ctrl+C)
uv run xiao-cli monitor

# Soft-reset the board upon connecting and stream live logs
uv run xiao-cli monitor --reset

# Stream logs for a fixed duration (e.g. 10 seconds)
uv run xiao-cli monitor --duration 10
```

### 6. Board Soft-Reset (`reset`)
Triggers a programmatic soft-reboot over USB CDC Serial (`Ctrl+C` interrupt followed by `Ctrl+D` software restart) and displays the bootloader output:
```bash
uv run xiao-cli reset
```

### 7. Explicit Port / Drive Overrides
If multiple boards or drives are attached, override the auto-discovery by specifying `--drive` or `--port`:
```bash
uv run xiao-cli --drive E:\ --port COM4 status
uv run xiao-cli --port COM9 monitor
```

---

## Switching Between CircuitPython and Rust

| Step | To Switch to Embedded Rust | To Switch back to CircuitPython |
| :--- | :--- | :--- |
| **One-Command CLI** | `uv run xiao-cli rust-deploy` | `uv run xiao-cli python-restore` |
| **Target Drive** | `D:\` (`XIAO-SENSE` UF2 Bootloader) | `D:\` (`CIRCUITPY` FAT Filesystem) |
| **Serial Protocol** | `usbd-serial` CDC-ACM (`115200` baud) | CircuitPython REPL CDC (`115200` baud) |
| **Firmware File** | `build/ai-metronome-rust.uf2` | `build/adafruit-circuitpython-....uf2` + `code.py` |

---

## Low-Level Toolchain Commands (`cmd.exe`)

In addition to the unified `xiao-cli` automation, developers can execute standard lower-level toolchain commands directly in Windows Command Prompt (`cmd.exe`):

### 1. Embedded Rust Commands (`cargo`)

```cmd
:: A. Run host Rust unit tests natively on Windows (x86_64)
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc

:: B. Cross-compile bare-metal ARM Cortex-M4F release binary (ELF)
cargo build --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --release --target thumbv7em-none-eabihf

:: C. Convert ELF binary to Nordic nRF52840 UF2 format
python -c "from tools.xiao_cli import elf_to_uf2; from pathlib import Path; elf_to_uf2(Path('src/xiao_nrf52840_sense/rust/target/thumbv7em-none-eabihf/release/ai-metronome-rust'), Path('build/ai-metronome-rust.uf2'))"

:: D. Trigger 1200-baud DFU bootloader reset over serial (without touching board)
python -c "import serial; s=serial.Serial('COM9', 1200); s.dtr=False; s.close()"

:: E. Copy UF2 binary to bootloader drive (manual flash)
copy /Y build\ai-metronome-rust.uf2 D:\ai-metronome-rust.uf2
```

### 2. CircuitPython Commands (`python` & OS commands)

```cmd
:: A. Copy code directly to the mounted CIRCUITPY flash drive
copy /Y src\xiao_nrf52840_sense\circuitpython\code.py D:\code.py

:: B. Connect to raw serial console / REPL stream
python -m serial.tools.miniterm COM9 115200

:: C. Soft-reboot the board over USB CDC serial (Ctrl-C + Ctrl-D)
python -c "import serial, time; s=serial.Serial('COM9', 115200); s.write(b''); s.close()"

:: D. Manual CircuitPython runtime restoration (from bare-metal Rust back to CIRCUITPY drive):
::    1. Double-click the tiny Reset button on the XIAO board -> D:\ mounts as XIAO-SENSE
::    2. Copy official CircuitPython runtime UF2:
copy /Y build\adafruit-circuitpython-Seeed_XIAO_nRF52840_Sense-en_US-9.2.4.uf2 D:\
::    3. Wait 3 seconds -> Board automatically boots CircuitPython and mounts as D:\ (CIRCUITPY)
::    4. Deploy application code:
copy /Y src\xiao_nrf52840_sense\circuitpython\code.py D:\code.py
```

### 3. Interactive Serial Debug Keys (Rust Firmware)
While connected to `uv run xiao-cli monitor` or miniterm:
- **`d`**: Dump internal state (noise floor, dynamic threshold, PLL BPM/lock status, IMU g/jerk, battery V, die temp).
- **`r`**: Re-run the full hardware self-test diagnostic banner (`[DIAG]`, `[MIC]`, `[IMU]`, `[CAL]`, `[READY]`).
- **`1`**, **`2`**, **`3`**, **`4`**: Switch modes directly (`ON_BEAT`, `IN_BETWEEN`, `4/4`, `3/4`).
- **`z`**: Trigger immediate 30s inactivity low-power sleep test.
- **`b`**: Reboot directly into factory `XIAO-SENSE` UF2 bootloader mode.

---

## Onboard RGB LED Status Guide
- **Solid / Blinking Blue**: Initializing hardware, verifying battery & thermal rails, waking `board.MIC_PWR`, verifying `PDMIn` DMA stream, and calibrating ambient noise floor.
- **3 Green Blinks**: Initialization & sensor verification **OK** — ready and listening.
- **Bright White Flash + Color Pulses**: Gesture mode switch confirmed (flashes new mode number).
- **Rhythm Flash (Red, Blue, or Green)**: Real-time beat flash synchronized via the autonomous internal PLL clock according to active mode.
- **Alternating Red / Blue**: Hardware fault detected during microphone initialization.

---

## Running Unit Tests

### 1. Python Unit Test Suite (Host Algorithmic, PLL & CLI Tests)
```cmd
uv run pytest -v
```

### 2. Rust Unit Test Suite (Host `no_std` Core Library Tests)
```cmd
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc
```
