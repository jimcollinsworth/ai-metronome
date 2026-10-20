# `JOURNAL.md` — Project History & Architectural Decision Records (ADRs)

Chronological record of milestones, architectural decisions, user steering, and technical refactorings for `ai-metronome`.

---

## 2026-10-19 — Refactoring Puck.js BLE Tooling to Lightweight Operational CLI

> [!NOTE] User Instructions & Guidance:
> - Removed the heavy JavaScript Intellisense engine and the large 460KB JSON reference file.
> - Resolved Windows console ANSI display character corruption (`?[36m`).
> - Fixed command exit inconsistency so `q`, `quit`, and `exit` cleanly terminate the console across all prompts.
> - Streamlined the TUI to a lean, bulletproof terminal console focused strictly on operational commands (`scan`, `connect`, `status`, `reset`, `diag`, `upload`) and direct REPL execution.
> - Preserved structured `--json` CLI commands for agent-driven iteration, deployment, and testing across a handful of Puck.js devices.

### ADR 003: Lean Windows BLE Tooling & Windows Console Processing
- **Context**: The initial prototype bundled a 460KB Espruino reference dictionary and complex PromptSession autocomplete overlays that produced ANSI artifacts in standard Windows `cmd.exe`. In addition, Windows WinRT returned `RPC_E_RETRY` (`[WinError -2147416359]`) on unpaired GATT access.
- **Decision**:
  1. Purged `prompt-toolkit`, `rich`, and the static JSON reference, reducing runtime dependencies to solely `bleak`.
  2. Enabled native Windows Virtual Terminal processing (`ENABLE_VIRTUAL_TERMINAL_PROCESSING` via `kernel32.SetConsoleMode`) and forced MTA COM mode (`sys.coinit_flags = 0`).
  3. Simplified interactive console to unified commands (`q` exits everywhere) with clean plain-text tables.
  4. Documented Windows Bluetooth pairing requirement for Puck.js devices to establish OS device nodes for reliable WinRT communication.

---

## 2026-10-18 — Project Scaffolding & Initial Toolchain Setup

> [!NOTE] User Instructions & Guidance:
> - Initialized repository with `uv`.
> - Created baseline directory structure and mandatory governance documents.
> - Kept domain descriptions and architecture as generic placeholders pending user design.

### ADR 001: Modern Python Toolchain with `uv`
- **Context**: Setting up a new repository requiring reproducible environment management, fast dependency resolution, and test automation.
- **Decision**: Adopt Astral `uv` for package management, virtual environment isolation, and script execution.
- **Consequences**: Standard `pyproject.toml` configuration, reproducible `.python-version`, and zero overhead.
