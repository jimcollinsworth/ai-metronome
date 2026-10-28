# Testing Documentation & Verification Guide: `ai-metronome`

This document defines the testing strategy, test suites, and Windows `cmd.exe` verification commands for `ai-metronome`.

---

## 1. Verification Tiers

1. **Rust Host Unit Tests (`cargo test`)**:
   - Exercises the platform-independent `no_std` core library natively on `x86_64-pc-windows-msvc`:
     - `ble_advertiser`: BLE `ADV_NONCONN_IND` header (`0x42`), Random Static MAC formatting (`|= 0xC0`), and **BTHome v2** (`UUID = 0xFCD2`) payload encoding for fractional (`0.01` factor) and integer BPM.
     - `mode_engine`: 4-mode beat sequencing, pre-lock dimming (`0.18`), weak-beat Red dimming (`0.20`), continuous flywheel coasting after sound stops, seamless mode switching, and immediate deceleration/acceleration adaptation.
     - `click_detector`: First-difference high-pass filter ($H(z)=1-z^{-1}$), outlier-resistant lower-tertile startup calibration, and sub-frame ($62.5\,\mu\text{s}$) impulse detection.
     - `gesture`: Dual-gesture mode switching (`DOUBLE_SHAKE` and `HARD_DROP`) and 30s inactivity sleep/wake state machine.
     - `crash_log`: Retained SRAM (`0x2003FF00`) panic & `HardFault` recording and CRC/magic validation.
2. **UF2 Toolchain & Reference Tests (`pytest`)**:
   - Validates the pure-Python ELF32 `PT_LOAD` parser and UF2 block generator (`tests/test_uf2_packer.py`) as well as reference DSP/PLL algorithms (`tests/test_click_detector.py`, `tests/test_mode_engine.py`).
3. **On-Device Hardware-in-the-Loop Verification (`uv run xiao-cli test`)**:
   - Connects to the XIAO nRF52840 Sense over USB CDC serial (`115200` baud), triggers the hardware self-test (`'r'`), and verifies all 7 hardware checkpoints:
     1. `POWER_DIAG` — Battery voltage divider (`P0.14` / `AIN7`), charge status (`P0.17`), CPU die temp (`NRF_TEMP`), and memory map.
     2. `MIC_POWER` — `P1.10` (`MIC_PWR`) high-drive (`H0H1`) power rail activation.
     3. `MIC_DMA_STREAM` — `NRF_PDM` 16 kHz 16-bit mono EasyDMA frame capture and peak-to-peak signal health.
     4. `IMU_BUS` — `P1.08` (`IMU_PWR`) high-drive rail and `NRF_TWIM0` 400 kHz I2C bus (`addr=0x6A`).
     5. `IMU_ACCEL` — `LSM6DS3TR-C` `WHO_AM_I=0x6A` verification, 3-axis accelerometer (`g`), and 3-axis gyroscope (`dps`).
     6. `BLE_ADVERTISER` — `NRF_RADIO` 2.4 GHz BLE 1 Mbps advertiser (`Name="AI-METRO"`, `BTHome v2 UUID=0xFCD2`).
     7. `CAL_AND_READY` — 25-frame ambient noise floor calibration, CJMCU-2812-8 (`D0`/`P0.02`) 8-pixel startup sweep + 3x Green LED blink, and `[READY]` state.

---

## 2. Test Execution Commands (`cmd.exe`)

### A. Rust Core Unit Tests
```cmd
cargo test --manifest-path src\xiao_nrf52840_sense\rust\Cargo.toml --lib --target x86_64-pc-windows-msvc
```

### B. Python UF2 Packer & Reference Unit Tests
```cmd
uv run pytest -v
```

### C. Rust Build, Flash & On-Device HIL Verification
```cmd
:: Build release ELF and pack build\ai-metronome-rust.uf2 (linked @ 0x00027000)
uv run xiao-cli build

:: Flash UF2 to XIAO-SENSE and immediately run the 7-point HIL test
uv run xiao-cli deploy --test

:: Re-run the 7-point HIL test on already-flashed hardware
uv run xiao-cli test

:: Listen for live clicks, gestures, and BLE broadcasts for 15 seconds
uv run xiao-cli test --listen-sec 15
```
