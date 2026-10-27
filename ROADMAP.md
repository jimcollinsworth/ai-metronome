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
- **Stage 2 — C++ Firmware**: Porting the audio DMA capture, PLL beat clock, and onset detection pipeline to C++ for deterministic hardware timer interrupts and zero-gap double-buffered PDM DMA (`src/xiao_nrf52840_sense/cpp/`).
- **Stage 3 — Rust Firmware**: Evaluating an embedded Rust (`embassy-nrf` / `nrf52840-hal`) implementation for memory-safe, zero-cost async audio DSP and BLE telemetry (`src/xiao_nrf52840_sense/rust/`).
- **Stage 4 — Optimized Native Code with Multi-Cluster Timbre/Harmonicity Rhythm Locking, Instrument Rejection & Custom-Phrase Voice Input (TFLite Micro / TinyML)**:
  - **Multi-Stream Rhythm Locking via Timbre, Harmonicity & Spectral Flatness**:
    - Extract a 7D acoustic fingerprint per candidate onset (`128-sample` onset window + `20–35 ms` tail):
      1. **Spectral Flatness ($\text{SFM}$)**: Wiener entropy distinguishing broadband percussive clicks ($\text{SFM} \approx 0.35\text{–}0.80$) from tonal instrument notes ($\text{SFM} < 0.18$).
      2. **Harmonicity ($H$)**: Normalized autocorrelation peak in the `[80–1200 Hz]` pitch lag range (low $< 0.35$ for clicks, high $> 0.60$ for pitched instruments).
      3. **Post-Onset Tail Decay ($\text{DR}_{25\text{ms}}$)**: RMS ratio of the `20–35 ms` tail to onset peak ($< 0.15$ for dry clicks vs $> 0.30$ for resonant piano strings).
      4. **4-Band $L_2$-Normalized Timbre Envelope ($\hat{\mathbf{e}}_1\dots\hat{\mathbf{e}}_4$)**: Volume/distance-invariant subband energy profile across `125–500 Hz`, `500–1.5 kHz`, `1.5–3.5 kHz`, and `3.5–8 kHz`.
    - **Listen-and-Cluster Acquisition**: Maintain 4 candidate sound clusters ($C_1\dots C_4$) grouped by cosine similarity ($\ge 0.88$, with support for alternating `A-B-A-B` tick/tock pairs). After accumulating $\ge 3$ intervals, rank clusters by $\text{Regularity}(\Delta t) \times \text{ClickProfile}(\text{SFM}, H, \text{DR}) \times \text{Prominence}$ and lock the PLL onto the strongest repeating sound stream $C^*$.
  - **Musical Instrument Rejection (e.g., Piano Practice Discrimination)**:
    - Once locked onto the winning click cluster $C^*$, reject any transient whose timbre vector deviates from $\boldsymbol{\mu}^*$, exhibits high harmonicity or sustained string resonance, or falls outside the expected PLL phase window.
  - **On-Device Voice Input with Custom Phrases (Keyword Spotting)**:
    - Run a quantized `int8` Depthwise-Separable CNN (DS-CNN) via **TensorFlow Lite for Microcontrollers (TFLite Micro)** + ARM CMSIS-NN DSP acceleration (`~7 ms` inference, `~25 KB` Flash, `~28 KB` RAM on the nRF52840 Cortex-M4F).
    - Share the continuous 16 kHz PDM microphone DMA ring buffer and 40-bin Log-Mel / MFCC spectral frontend between the click-similarity engine and the voice recognizer (blanking `10 ms` click slices during KWS windowing).
    - Train and deploy **custom spoken phrases** (e.g., *"on beat"*, *"upbeat"*, *"four four"*, *"three four"*, *"sleep"*) via a host Python training/augmentation pipeline exported to a C byte array (`model_data.h`).
- **Archived Exploration (`archive/puck/`)**: Initial Puck.js BLE console prototype archived after determining an onboard microphone is essential.

### Phase 1: Core Engine & Timing Architecture
- [Placeholder: timing loop, rhythm generation, or audio engine requirements]

### Phase 2: Interface & Control
- [Placeholder: CLI, GUI, or external hardware/MIDI controls]

### Phase 3: Advanced Capabilities
- [Placeholder: adaptive features, AI integrations, or pattern customization]
