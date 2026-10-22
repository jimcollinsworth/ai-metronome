# `ROADMAP.md` — Long-Term Vision & Feature Backlog

Strategic proposals, architecture ideas, and long-term roadmap for `ai-metronome`.

---

## 1. Vision & Core Philosophy

### Acoustic Augmentation in Real-World Musical Environments
`ai-metronome` is built on the philosophy of non-intrusive musical augmentation: working harmoniously alongside authentic physical instruments and traditional mechanical metronomes rather than replacing them with sterile digital beeps.

A central design requirement is reliable operation in hostile acoustic environments—specifically when the metronome is **positioned directly on top of an actively played piano**. In this scenario, the microphone is subjected to massive acoustic energy across the entire frequency spectrum (27.5 Hz to 4,186+ Hz), loud percussive hammer-string onsets, sustain pedal sympathetic resonance, and structural vibrations conducted through the piano lid and metronome enclosure.

### Multi-Tiered Acoustic Isolation Strategy
To reliably lock onto the mechanical escapement click while ignoring musical performance audio:
1. **Physical Enclosure Advantage**: Housing the microphone inside the metronome body creates a favorable signal-to-noise ratio (SNR) for internal mechanical clicks compared to external ambient sound.
2. **Deterministic Transient DSP**: Filtering with steep high-pass/bandpass characteristics (1 kHz to 6 kHz), evaluating attack-slope velocity ($\Delta \text{amplitude} / \Delta t < 1.5\,\text{ms}$), crest factor, and spectral flatnesses to reject harmonic piano tones.
3. **Machine Learning / TinyML Classification**: Employing lightweight neural transient classifiers (running under CMSIS-NN / TFLite Micro) to distinguish authentic escapement clicks from piano hammer onsets, percussive taps, and ambient speech.
4. **Active Internal Echo & Speaker Cancellation**: When an audio output transducer/speaker is integrated into future hardware revisions, the firmware will implement reference-based acoustic echo cancellation (AEC) or synchronous phase gating so the unit's own sounds never corrupt the incoming click detector stream.

---

## 2. Milestone Proposals

### Phase 0: Hardware Target & Multi-Language MCU Progression (XIAO nRF52840 Sense)
- **Target Hardware**: Seeed Studio XIAO nRF52840 Sense (64 MHz Cortex-M4F, onboard digital PDM MEMS microphone, 6-axis IMU, RGB LED, BLE 5.0).
- **Stage 1 — CircuitPython POC**: Rapid prototyping of hardware initialization, PDM microphone health checks, adaptive high-pass click detection, and visual LED beat synchronization (`src/xiao_nrf52840_sense/circuitpython/code.py`).
- **Stage 2 — C++ Firmware**: Porting the audio DMA capture, PLL beat clock, and onset detection pipeline to C++ for deterministic hardware timer interrupts and zero-gap double-buffered PDM DMA (`src/xiao_nrf52840_sense/cpp/`).
- **Stage 3 — Rust Firmware**: Evaluating an embedded Rust (`embassy-nrf` / `nrf52840-hal`) implementation for memory-safe, zero-cost async audio DSP and BLE telemetry (`src/xiao_nrf52840_sense/rust/`).
- **Stage 4 — Optimized Native Code with On-Device Voice Input (TFLite Micro / TinyML)**:
  - Run an quantized int8 Keyword Spotting (KWS) neural network via **TensorFlow Lite for Microcontrollers (TFLite Micro)** + ARM CMSIS-NN DSP acceleration on the nRF52840 Cortex-M4F.
  - Share the continuous 16 kHz PDM microphone DMA ring buffer between the real-time click/PLL engine and the TFLite Micro audio frontend (MFCC / log-mel spectrogram extraction).
  - Support hands-free spoken mode & meter commands (e.g., *"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"stop"*) alongside IMU gesture controls.
- **Archived Exploration (`archive/puck/`)**: Initial Puck.js BLE console prototype archived after determining an onboard microphone is essential.

### Phase 1: Core Engine & Timing Architecture
- [Placeholder: timing loop, rhythm generation, or audio engine requirements]

### Phase 2: Interface & Control
- [Placeholder: CLI, GUI, or external hardware/MIDI controls]

### Phase 3: Advanced Capabilities
- [Placeholder: adaptive features, AI integrations, or pattern customization]
