---
name: embedded-rust
description: Architecture patterns, best practices, memory safety rules, zero-allocation conventions, and professional reference examples for bare-metal and async Embedded Rust (ARM Cortex-M, nRF52840, Embassy, PAC/HAL, probe-rs, defmt).
---

# Embedded Rust Development Guide & Reference Patterns

This skill outlines operational principles, safety rules, architecture patterns, and reference examples for writing professional, production-grade embedded Rust firmware on resource-constrained microcontrollers (specifically ARM Cortex-M4F / Nordic nRF52840).

---

## 1. Core Engineering Principles for Production Firmware

### A. Zero Heap Allocation in Real-Time Paths
- **Rule**: Do **NOT** rely on dynamic heap memory allocation (`alloc`, `Box`, `Vec`, `String`) in critical firmware paths.
- **Why**: Dynamic allocation introduces non-deterministic execution times, heap fragmentation, and silent allocation failures during long-running operations.
- **Pattern**: Use statically sized, stack-allocated, or statically placed buffers (`heapless::Vec`, `heapless::String`, fixed-size arrays `[T; N]`, or circular ring buffers).

### B. Hardware DMA & Atomic Memory Ordering
- When peripherals write to RAM via EasyDMA (e.g. `NRF_PDM`, `NRF_PWM0`, `NRF_RADIO`, `NRF_SPIM`):
  1. The CPU cache/pipeline and DMA controller must stay synchronized. Always insert `core::sync::atomic::compiler_fence(Ordering::SeqCst)` or `cortex_m::asm::dsb()` before triggering DMA start tasks and after verifying DMA completion events.
  2. The buffer passed to DMA (`PTR` register) must reside in physical Data RAM (`0x20000000..0x2003FFFF` on nRF52840), never Flash/ROM or unmapped regions.
  3. Statically size DMA arrays so they cannot be dropped or moved while the hardware peripheral is actively clocking bits.

### C. Stack Protection & Linker Safety
- **Tool**: `flip-link` (Zero-cost stack overflow protection).
  - Traditional linker scripts place the stack above the heap/BSS growing downwards toward data. An overflow silently corrupts variables before hitting an unmapped fault.
  - `flip-link` reverses the layout: the stack begins at the lowest RAM address and grows downward into reserved address space, causing a deterministic `HardFault` the instant an overflow occurs.
- **Relocation (`VTOR`)**:
  - When booting under a bootloader (e.g., Adafruit UF2, Nordic SoftDevice S140), always relocate the vector table in the first instruction of `main`:
    ```rust
    (*cortex_m::peripheral::SCB::PTR).vtor.write(0x0002_7000);
    cortex_m::asm::dsb();
    cortex_m::asm::isb();
    ```

---

## 2. Concurrency Paradigms: Choosing the Right Model

| Feature | Bare-Metal Polling (PAC/HAL) | Embassy Async Runtime (`embassy-nrf`) | RTIC (Real-Time Interrupt-driven Concurrency) |
| :--- | :--- | :--- | :--- |
| **Model** | Single-threaded cooperative loop | Async/await cooperative task executor | Hardware priority-preemptive interrupt tasks |
| **Overhead** | Absolute minimum (0 bytes RAM) | Very low (static task state machines) | Minimal (uses ARM NVIC hardware priorities) |
| **Concurrency**| Manual closures & state polling | `spawner.spawn(task).unwrap()` | Task dispatch via software interrupts |
| **Driver Model**| Direct registers (`pac`) or blocking HAL | Non-blocking async drivers (`embassy_nrf`) | Resource locks via ceiling priority |
| **Sleep/Power**| Manual `WFI` / `WFE` in idle loop | Automatic `WFI` when all tasks await | Automatic sleep when all queues empty |
| **Best For** | Ultra-tight DSP loops, tiny utilities | Multitasking (Audio + USB + BLE + Sensors) | Hard real-time control (motor drives, robotics)|

---

## 3. Asynchronous Embedded Rust with Embassy (`embassy-rs`)

Embassy is the modern standard for writing high-performance, asynchronous embedded Rust without a traditional heavyweight C RTOS.

### A. Architectural Pattern
```rust
#![no_std]
#![no_main]

use defmt::info;
use defmt_rtt as _;
use panic_probe as _;
use embassy_executor::Spawner;
use embassy_nrf::gpio::{Level, Output, OutputDrive};
use embassy_time::{Duration, Timer};

#[embassy_executor::task]
async fn blink_task(mut led: Output<'static>) {
    loop {
        led.set_high();
        Timer::after(Duration::from_millis(500)).await;
        led.set_low();
        Timer::after(Duration::from_millis(500)).await;
    }
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_nrf::init(Default::default());
    info!("Hardware initialized cleanly");

    let led_pin = Output::new(p.P0_26, Level::High, OutputDrive::Standard);
    spawner.spawn(blink_task(led_pin)).unwrap();

    loop {
        Timer::after(Duration::from_secs(10)).await;
    }
}
```

### B. Inter-Task Communication (`embassy-sync`)
- **`Channel<RawMutex, T, N>`**: Asynchronous multi-producer, multi-consumer queue with fixed capacity `N`. Ideal for passing audio onset events or sensor samples from DMA tasks to processing engines.
- **`Signal<RawMutex, T>`**: Lightweight one-shot event signaling. Tasks `.wait().await` until another task calls `.signal(val)`.
- **`Mutex<RawMutex, T>`**: Mutual exclusion locking across async `.await` boundaries.

---

## 4. Exemplary Professional Embedded Rust Codebases on GitHub

Study these repositories as gold-standard references for clean architecture, idiomatic abstractions, and hardware mastery:

### 1. `embassy-rs/embassy`
- **URL**: [github.com/embassy-rs/embassy](https://github.com/embassy-rs/embassy)
- **Key Files**:
  - `examples/nrf52840/src/bin/pdm.rs`: Direct async PDM microphone DMA streaming.
  - `examples/nrf52840/src/bin/usb_serial.rs`: Async USB CDC ACM device implementation.
  - `examples/nrf52840/src/bin/pwm.rs`: EasyDMA PWM generation for WS2812B / motor drivers.
  - `examples/nrf52840/src/bin/twim.rs`: Non-blocking async I2C bus transactions.

### 2. `embassy-rs/trouble`
- **URL**: [github.com/embassy-rs/trouble](https://github.com/embassy-rs/trouble)
- **What It Teaches**:
  - A modern, memory-safe, pure-Rust Bluetooth Low Energy (BLE 5.0) Host and Controller stack.
  - Demonstrates how to design complex protocol state machines and GATT services entirely in `#![no_std]` Rust without vendor blobs.

### 3. `knurling-rs` by Ferrous Systems
- **URL**: [github.com/knurling-rs/app-template](https://github.com/knurling-rs/app-template)
- **What It Teaches**:
  - `defmt`: Highly efficient binary logging where format strings remain on host development PC.
  - `probe-rs`: Sub-second flash programming and RTT terminal streaming without GDB.
  - `flip-link`: Zero-cost stack overflow linker setup.

### 4. `tock/tock`
- **URL**: [github.com/tock/tock](https://github.com/tock/tock)
- **What It Teaches**:
  - Production capability-based security in embedded systems.
  - Pure Rust microkernel separating untrusted user-space applications (C, Rust, Lua) from privileged hardware capsules.

---

## 5. Development Diagnostics & Toolchain Standards

```bash
# 1. Formatting and linting
cargo fmt --all
cargo clippy --target thumbv7em-none-eabihf -- -D warnings

# 2. Host Unit Testing (Dual Target Design)
# Keep DSP logic, PLL mode engines, and protocol encoders strictly independent of PAC
cargo test --lib --target x86_64-pc-windows-msvc

# 3. Size Inspection
cargo size --target thumbv7em-none-eabihf --release --bin ai-metronome-rust -- -A
cargo nm --target thumbv7em-none-eabihf --release --bin ai-metronome-rust -- --size-sort -r | head -n 25
```
