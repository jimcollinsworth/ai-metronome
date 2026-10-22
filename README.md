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
├── archive/
│   └── puck/                       # Archived Puck.js BLE CLI/TUI prototype & tests
├── docs/                           # Documentation and architecture design specifications
├── src/
│   ├── ai_metronome/               # Host-testable core algorithms (PDM click detector)
│   └── xiao_nrf52840_sense/        # Target MCU firmware implementations
│       ├── circuitpython/
│       │   └── code.py             # Self-contained CircuitPython click detector POC
│       ├── cpp/                    # Planned C++ firmware implementation
│       └── rust/                   # Planned Rust firmware implementation
├── tests/                          # Automated unit test suites
├── tools/                          # Developer and deployment utilities
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

### 2. Deploying Firmware (`deploy` / `push`)
Pushes the firmware source to the board's flash memory. CircuitPython automatically reloads upon file write:
```bash
# Push default firmware (src/xiao_nrf52840_sense/circuitpython/code.py)
uv run xiao-cli deploy

# Push and immediately trigger automated hardware-in-the-loop verification
uv run xiao-cli deploy --test

# Deploy a specific custom source file
uv run xiao-cli deploy --file path/to/my_code.py
```

### 3. Automated On-Device Verification (`hil-test` / `test`)
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

### 4. Real-Time Telemetry Monitor (`monitor` / `logs`)
Streams live serial diagnostics at 115200 baud, showing click detections, noise floor shifts, BPM calculations, and IMU gestures:
```bash
# Stream continuously (exit with Ctrl+C)
uv run xiao-cli monitor

# Soft-reset the board upon connecting and stream live logs
uv run xiao-cli monitor --reset

# Stream logs for a fixed duration (e.g. 10 seconds)
uv run xiao-cli monitor --duration 10
```

### 5. Board Soft-Reset (`reset`)
Triggers a programmatic soft-reboot over USB CDC Serial (`Ctrl+C` interrupt followed by `Ctrl+D` software restart) and displays the bootloader output:
```bash
uv run xiao-cli reset
```

### 6. Explicit Port / Drive Overrides
If multiple boards or drives are attached, override the auto-discovery by specifying `--drive` or `--port`:
```bash
uv run xiao-cli --drive E:\ --port COM4 status
uv run xiao-cli --port COM9 monitor
```

---

## Manual Deployment

If running outside the Python CLI environment, copy the self-contained script directly to the root of the mounted `CIRCUITPY` USB drive:

```powershell
Copy-Item src\xiao_nrf52840_sense\circuitpython\code.py D:\code.py -Force
```
*(Replace `D:` with your active `CIRCUITPY` drive letter. Zero external `/lib` dependencies are required; direct hardware register drivers are bundled in `code.py`.)*

---

## Onboard RGB LED Status Guide
- **Solid / Blinking Blue**: Initializing hardware, verifying battery & thermal rails, waking `board.MIC_PWR`, verifying `PDMIn` DMA stream, and calibrating ambient noise floor.
- **3 Green Blinks**: Initialization & sensor verification **OK** — ready and listening.
- **Bright White Flash + Color Pulses**: Gesture mode switch confirmed (flashes new mode number).
- **Rhythm Flash (Red, Blue, or Green)**: Real-time beat flash synchronized via the autonomous internal PLL clock according to active mode.
- **Alternating Red / Blue**: Hardware fault detected during microphone initialization.

---

## Running Unit Tests

```bash
uv run pytest -v
```
