# `ROADMAP.md` — Long-Term Vision & Feature Backlog

Strategic proposals, architecture ideas, and long-term roadmap for `ai-metronome`.

---

## 1. Vision & Core Philosophy

[Placeholder: high-level vision, audio/timing principles, and creative goals to be defined by Jim]

---

## 2. Milestone Proposals

### Phase 0: Hardware Target & Multi-Language MCU Progression (XIAO nRF52840 Sense)
- **Target Hardware**: Seeed Studio XIAO nRF52840 Sense (64 MHz Cortex-M4F, onboard digital PDM MEMS microphone, 6-axis IMU, RGB LED, BLE 5.0).
- **Stage 1 — CircuitPython POC**: Rapid prototyping of hardware initialization, PDM microphone health checks, adaptive high-pass click detection, and visual LED beat synchronization (`src/xiao_nrf52840_sense/circuitpython/code.py`).
- **Stage 2 — C++ Firmware**: Porting the audio DMA capture and onset detection pipeline to C++ for deterministic sub-millisecond interrupt timing and full hardware peripheral access (`src/xiao_nrf52840_sense/cpp/`).
- **Stage 3 — Rust Firmware**: Evaluating an embedded Rust (`embassy-nrf` / `nrf52840-hal`) implementation for memory-safe, zero-cost async audio DSP and BLE telemetry (`src/xiao_nrf52840_sense/rust/`).
- **Archived Exploration (`archive/puck/`)**: Initial Puck.js BLE console prototype archived after determining an onboard microphone is essential.

### Phase 1: Core Engine & Timing Architecture
- [Placeholder: timing loop, rhythm generation, or audio engine requirements]

### Phase 2: Interface & Control
- [Placeholder: CLI, GUI, or external hardware/MIDI controls]

### Phase 3: Advanced Capabilities
- [Placeholder: adaptive features, AI integrations, or pattern customization]
