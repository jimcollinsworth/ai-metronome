# `PLANNING.md` — Active Backlog & Sprint Milestones

Active backlog and task tracking for `ai-metronome`.

---

## Active Sprint: Project Scaffolding & Lightweight Puck.js BLE Tooling

- [x] Initialize project using `uv`
- [x] Configure `pyproject.toml` and baseline dev dependencies
- [x] Establish standard directory structure (`src/ai_metronome`, `tools/`, `tests`, `docs`, `.agents`)
- [x] Establish mandatory governance documents (`AGENTS.md`, `README.md`, `PLANNING.md`, `ROADMAP.md`, `JOURNAL.md`, `TESTING.md`)
- [x] Build lightweight `tools/puck_cli` Windows BLE CLI for Puck.js devices:
  - [x] Stripped heavy Intellisense engine and 460KB JSON catalog in favor of lean operational tooling
  - [x] Native Windows WinRT BLE client (`bleak`) with clean MTA thread configuration and Windows VT console support
  - [x] Simplified, single-mode console: unified `q`/`quit`/`exit`, operational commands (`scan`, `connect`, `status`, `reset`, `diag`, `upload`), and direct JS execution
  - [x] Agent CLI with structured `--json` output for automated deploy, diagnose, iterate, and test workflows across a handful of Puck.js devices
  - [x] Automated unit test suite (`tests/test_puck_ble.py`, `tests/test_puck_cli.py`, `tests/test_smoke.py`) passing (9/9)
- [ ] [Feature planning in progress: define core domain requirements and architecture]

---

## Backlog

- [ ] [Backlog items in progress]
