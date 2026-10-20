# ai-metronome

[Placeholder overview: project description and purpose in progress]

---

## Architecture & Layout

```text
ai-metronome/
├── .agents/              # Agent operating rules and workflow specifications
├── docs/                 # Documentation and architecture design specifications
├── src/
│   └── ai_metronome/     # Core application package
├── tools/
│   └── puck_cli/         # Windows BLE CLI & lightweight console for Puck.js devices
├── tests/                # Automated test suites
├── AGENTS.md             # Universal agent operating guidelines
├── JOURNAL.md            # Chronological log & Architectural Decision Records (ADRs)
├── PLANNING.md           # Active backlog & sprint task tracking
├── ROADMAP.md            # Long-term vision and feature backlog
├── TESTING.md            # Testing strategy and execution guide
├── pyproject.toml        # Project metadata and dependencies
└── main.py               # Application entry point
```

---

## Developer Setup

### Prerequisites
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager

### Installation

1. Clone or navigate to the repository directory.
2. Synchronize the virtual environment:
   ```bash
   uv sync
   ```

---

## Puck.js BLE Tool (`tools/puck_cli`)

A fast, lightweight Windows BLE CLI and interactive console for connecting, deploying, iterating, and diagnosing Puck.js devices over Nordic UART Service (NUS).

### Windows Bluetooth Setup
Before first connection, pair your Puck.js in Windows:
> **Windows Settings** -> **Bluetooth & devices** -> **Add device** -> **Bluetooth** -> select your Puck.js (e.g. `Puck.js d3ad`).

### Interactive Console
```bash
uv run puck
# Or connect directly to a specific device:
uv run puck -d d3ad
```

Inside the console:
- Type `help` or `?` for operational commands.
- Type `q`, `quit`, or `exit` to exit cleanly at any prompt.
- Type any JavaScript directly to run it on the device (e.g., `LED1.set()`, `Puck.mag()`, `E.getBattery()`).
- Type `scan` to refresh nearby Puck devices, or `connect <#|name>` to switch devices.
- Type `diag` to view battery, temperature, firmware version, and free memory.
- Type `upload <file.js>` to deploy code to RAM.

### Agent & Script CLI (Structured JSON Mode)
```bash
# Scan for nearby Puck.js devices
uv run puck scan --json

# Set default device for subsequent commands
uv run puck use d3ad

# Execute a JavaScript expression and capture result
uv run puck exec "E.getTemperature()" --json
uv run puck exec -d d3ad "LED1.set()" --json

# Deploy a script to RAM
uv run puck deploy script.js --json

# Query device diagnostics (battery, temp, firmware version, memory)
uv run puck diag -d d3ad --json

# Reset Puck.js RAM state
uv run puck reset -d d3ad
```

---

## Running Tests

Execute test suite with pytest via `uv`:
```bash
uv run pytest
```
