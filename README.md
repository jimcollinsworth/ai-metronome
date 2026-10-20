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

### Deploying to the Board
Copy [`src/xiao_nrf52840_sense/circuitpython/code.py`](file:///c:/Users/jimco/Projects/ai-metronome/src/xiao_nrf52840_sense/circuitpython/code.py) directly to the root of your `CIRCUITPY` USB drive as `code.py`:

```powershell
Copy-Item src\xiao_nrf52840_sense\circuitpython\code.py D:\code.py -Force
```
*(Replace `D:` with your `CIRCUITPY` drive letter. Requires zero external `/lib` dependencies.)*

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
