# Testing Documentation & Verification Guide: ai-metronome

This document defines the testing strategy, test suites, execution commands, and operational standards for `ai-metronome`.

---

## 1. Testing Architecture & Verification Pyramid

Testing for this project operates across defined tiers:

- **Unit Testing**: Isolated verification of data structures, BLE NUS payload framing, Espruino Reference Intellisense completion/signature lookup, and helper functions.
- **CLI & Protocol Mocking**: Verification of BLE scanner sorting, GATT UART notification streams, and agent JSON CLI subcommands (`scan`, `pair`, `exec`, `api`).
- **Smoke Testing**: Basic package importability and CLI entry point sanity checks.

---

## 2. Test Suites

| Test File | Scope |
|-----------|-------|
| `tests/test_smoke.py` | Package importability sanity check |
| `tests/test_puck_intellisense.py` | 989-entry Espruino Reference catalog, dot-completion (`Puck.`, `NRF.`, `E.`, `ESP32.`), instance resolution (`LED1.` -> `Pin`, `Bluetooth.` -> `Serial`), and active call signature tooltips |
| `tests/test_puck_ble.py` | Espruino BLE peripheral identification, 20-byte MTU chunking, REPL echo/prompt stripping, scanner sorting, and `PuckBLEClient` async NUS TX/RX cycle |
| `tests/test_puck_cli.py` | Agent CLI subcommands (`puck api`, `puck scan --json`, `puck exec --json`) |

---

## 3. Environment & Test Tooling Setup

### Toolchain Versions & Requirements
* **Environment & Package Manager**: `uv` (`.venv/`)
* **Python Runtime**: Python 3.12+
* **Test Framework**: `pytest` (v8.0+) + `pytest-asyncio`

### Running Tests

Execute the full test suite with:
```bash
uv run pytest
```

Execute tests with verbose output:
```bash
uv run pytest -v
```
