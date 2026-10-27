# ai-metronome

[Placeholder overview: project description and purpose in progress]

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

## XIAO nRF52840 Sense — CircuitPython POC (`v1`)

### Deploying CircuitPython to the Board (`cmd.exe`)
Copy [`src/xiao_nrf52840_sense/circuitpython/code.py`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/circuitpython/code.py) directly to the mounted `CIRCUITPY` USB drive (or use `xiao-cli`):

```cmd
:: Automated deploy & test via xiao-cli
uv run xiao-cli python-deploy --test

:: Or manual file copy
copy /Y src\xiao_nrf52840_sense\circuitpython\code.py D:\code.py
```

---

## XIAO nRF52840 Sense — Embedded Rust Firmware (`v2.6`)

### Windows `cmd.exe` Toolchain Commands
All commands run directly in standard Windows Command Prompt (`cmd.exe`) without external GNU toolchains or debuggers:

```cmd
:: 1. Run Rust library unit tests natively on Windows
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc

:: 2. Cross-compile release binary and generate build\ai-metronome-rust.uf2
uv run xiao-cli rust-build

:: 3. Flash UF2 image to XIAO-SENSE bootloader drive
uv run xiao-cli rust-deploy

:: 4. Run automated 6-point Hardware-in-the-Loop test over COM9
uv run xiao-cli hil-test --port COM9

:: 5. Interactive live serial monitor & debug console
uv run xiao-cli monitor --port COM9
```

### Interactive Serial Debug Keys
While connected to `uv run xiao-cli monitor`:
- **`d`**: Dump internal state (noise floor, dynamic threshold, PLL BPM/lock status, IMU $g$/jerk, battery V, die temp).
- **`r`**: Re-run the full hardware self-test diagnostic banner (`[DIAG]`, `[MIC]`, `[IMU]`, `[CAL]`, `[READY]`).
- **`1`**, **`2`**, **`3`**, **`4`**: Switch modes directly (`ON_BEAT`, `IN_BETWEEN`, `4/4`, `3/4`).
- **`z`**: Trigger immediate 30s inactivity low-power sleep test.
- **`b`**: Reboot directly into factory `XIAO-SENSE` UF2 bootloader mode.

### Onboard RGB LED Status Guide
- **Solid / Blinking Blue**: Initializing hardware, verifying battery & thermal rails, waking `board.MIC_PWR`, verifying `PDMIn` DMA stream, and calibrating ambient room noise floor.
- **3 Green Blinks**: Initialization & microphone verification **OK** — ready and listening.
- **Red Flash**: **Click detected!** Blinks in real time with each detected metronome click and logs peak, noise floor, and estimated BPM over USB Serial (`115200` baud).
- **Alternating Red / Blue**: Hardware fault detected during microphone initialization.

---

## Running Unit Tests

```bash
uv run pytest -v
```
