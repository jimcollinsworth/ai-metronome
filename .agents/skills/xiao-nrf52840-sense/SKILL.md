---
name: xiao-nrf52840-sense
description: >-
  Hardware architecture, internal sensor power gates, PDM microphone DMA, LSM6DS3TR-C IMU
  registers, active-low RGB LED, battery sensing, and HIL CLI workflows for the Seeed Studio
  XIAO nRF52840 Sense across CircuitPython, C++, Rust, and TFLite Micro.
---

# Seeed Studio XIAO nRF52840 Sense Hardware & Firmware Skill

Use this skill when developing, testing, or debugging code for the **Seeed Studio XIAO nRF52840 Sense** (`Seeed_XIAO_nRF52840_Sense`, USB VID `0x2886` / `0x239A`).

## 1. Internal Hardware Pin Map & Power Gates

Unlike generic dev boards, the XIAO nRF52840 Sense gates its onboard sensors behind dedicated power pins to allow ultra-low-power sleep (`< 5 uA`). **You must drive the power gate HIGH before initializing the peripheral bus.**

| Subsystem | CircuitPython Pin(s) | nRF52840 GPIO | Notes & Requirements |
| :--- | :--- | :--- | :--- |
| **PDM Microphone Power** | `board.MIC_PWR` | `P1.10` | Set OUTPUT `True` (`HIGH`) + wait `20 ms` before `PDMIn`. |
| **PDM Microphone Bus** | `board.PDM_CLK`, `board.PDM_DATA` | `P1.00`, `P0.16` | `MSM261D3526H1CPM` digital MEMS mic (`16000 Hz`, 16-bit unsigned). |
| **6-Axis IMU Power** | `board.IMU_PWR` | `P1.08` | Set OUTPUT `True` (`HIGH`) + wait `80 ms` before `busio.I2C`. |
| **6-Axis IMU I2C Bus** | `board.IMU_SCL`, `board.IMU_SDA` | `P0.27`, `P0.07` | Internal I2C bus (400 kHz supported); `board.IMU_INT1` on `P0.11`. |
| **Onboard RGB LED** | `board.LED_RED`, `LED_GREEN`, `LED_BLUE` | `P0.26`, `P0.30`, `P0.06` | **Active-Low**: `value = False` turns LED **ON**, `value = True` turns LED **OFF**. |
| **Battery Read Gate** | `board.READ_BATT_ENABLE`, `board.VBATT` | `P0.14`, `P0.31` | Drive `READ_BATT_ENABLE = False` (`LOW`) to read `VBATT`, then set `True` to prevent drain. |
| **Charge Status** | `board.CHARGE_STATUS` | `P0.17` | Input: `False` (`LOW`) = Charging, `True` (`HIGH`) = Discharging / Full. |

---

## 2. Onboard Sensors: Direct Register & DMA Specifications

### ST LSM6DS3TR-C 6-Axis IMU (I2C Address `0x6A` or `0x6B`)
- **`WHO_AM_I` (`0x0F`)**: Returns `0x6A` (or `0x69` on older LSM6DS3 variants).
- **`CTRL1_XL` (`0x10`)**:
  - `0x48`: 104 Hz ODR, $\pm 4g$ full scale (`8192 LSB/g`).
  - `0x68`: 416 Hz ODR, $\pm 4g$ full scale (`8192 LSB/g`) — recommended for high-rate gesture/tap detection.
- **Accelerometer Output (`0x28`–`0x2D`)**: 6-byte burst read (`OUTX_L_XL` to `OUTZ_H_XL`), unpacked via `struct.unpack("<hhh", buf6)`.

### PDM Microphone (`audiobusio.PDMIn`)
- 80 samples at `16000 Hz` executes in **`4.9 ms`** on the nRF52840 (~200 Hz frame loop rate).
- 128 samples at `16000 Hz` executes in **`9.8 ms`** (~100 Hz frame loop rate).

---

## 3. Embedded Rust Boot, USB CDC Enumeration & UF2/DFU Flashing Rules (Proven on Hardware)

When building bare-metal Embedded Rust (`thumbv7em-none-eabihf`, `nrf52840-hal` / `nrf-usbd` / `usb-device`) for the Seeed Studio XIAO nRF52840 Sense (which ships with `UF2 Bootloader 0.6.2` and `SoftDevice: S140 7.3.0`), **five strict hardware/bootloader requirements** must be followed, and previous false assumptions must be avoided:

### A. Verified Rules (Must Always Do)
1. **Link at `0x00027000` (Above S140 v7.3.0) with `RAM = 0x20006000`**:
   - The factory bootloader expects the application vector table at `0x00027000` (`nrf52840_s140_v7.ld`).
   - Reserve `0x20000000..0x20006000` for MBR/S140 and keep the top 272 bytes (`0x2003FEF0..0x20040000`) above `_stack_start` for the clean-boot trampoline flag (`0x2003FEFC`) and retained crash log (`0x2003FF00`).
2. **One-Shot `SCB::sys_reset()` Clean-Boot Trampoline After UF2 Flashing (`0x2003FEFC`)**:
   - **Why**: When `XIAO-SENSE` (`D:\`) is mounted, the Adafruit UF2 bootloader runs TinyUSB (MSC + CDC) on `NRF_USBD`. When a `.uf2` file finishes copying, the bootloader calls `board_teardown()` and jumps directly to `0x00027000` **without performing a hardware MCU reset**, leaving `NRF_USBD` internal state dirty (`USB\VID_0000&PID_0002` — *Device Descriptor Request Failed*).
   - **Fix**: On entry to `main()`, check a retained SRAM word (`0x2003_FEFC != 0xB007_C1EA`). On the first entry after UF2 jump, write `0xB007_C1EA`, delay ~200 ms (`cortex_m::asm::delay(12_800_000)`) so Windows finishes unmounting `D:\`, and call `SCB::sys_reset()`. On the instant reboot (<1 ms), the bootloader sees a valid app, **skips TinyUSB completely**, and jumps back to `0x00027000` on 100% freshly reset silicon!
3. **Explicit `.max_packet_size_0(64).unwrap()` on `UsbDeviceBuilder`**:
   - `usb-device 0.3.2` defaults `max_packet_size_0` to `8` bytes (`device_builder.rs:92`), whereas `nrf-usbd` requires 64-byte EP0 control transfers. Omitting `.max_packet_size_0(64)` causes Windows descriptor requests to fail.
4. **Stop Bootloader FreeRTOS `SysTick` & Mask NVIC Before Setting `SCB->VTOR = 0x00027000`**:
   - Disable interrupts (`cortex_m::interrupt::disable()`), stop `SysTick` (`SYST.CSR = 0`), clear pending `SysTick`/`PendSV` in `SCB->ICSR`, clear all 8 `NVIC.ICER`/`NVIC.ICPR` registers, and only then write `SCB->VTOR = 0x00027000`.
5. **Unbuffered 512-Byte UF2 Block Writes & Continuous USB Polling**:
   - Write `.uf2` files in unbuffered 512-byte blocks (`buffering=0` + `os.fsync()`) or flash via official `adafruit-nrfutil dfu serial` (`--dev-type 0x0052 --sd-req 0x0123`).
   - Poll `usb_dev.poll(&mut [&mut serial])` during sensor power-up delays (`delay_ms_with_poll`) and PDM DMA waits (`capture_frame_with_poll`).

### B. False Assumptions Removed (Do NOT Do)
- **FALSE**: *"Touching `USBD.USBPULLUP` or `USBD.ENABLE` manually before `Usbd::new()` fixes post-UF2 enumeration."* — Touching `USBD` registers before `nrf-usbd` initializes actually interferes with `nrf-usbd`'s internal power/event state machine; a clean `SCB::sys_reset()` trampoline is what resets `NRF_USBD` hardware properly.
- **FALSE**: *"Enabling global interrupts (`cortex_m::interrupt::enable()`) helps `nrf-usbd` enumerate."* — Polling `usb_dev.poll()` works purely via registers with `PRIMASK=1`; enabling global interrupts without a `USBD` ISR vectors into `DefaultHandler`.
- **FALSE**: *"Software `cortex_m::asm::delay()` bit-banging at 64 MHz drives WS2812B NeoPixels accurately."* — Loop/store overhead stretches `'0'` pulses past `550 ns`, causing WS2812B LEDs to latch `0xFFFFFF` (stuck full white). Always use hardware `NRF_PWM0` EasyDMA (`prescaler = DIV_1` 16 MHz, `countertop = 20` = 800 kHz, `DUTY_0 = 6 | 0x8000` = `375 ns`, `DUTY_1 = 13 | 0x8000` = `812.5 ns`).

---

## 4. Project Rust Development & HIL Testing Workflow (`xiao-cli`)

Always verify changes on the physical XIAO nRF52840 Sense using `xiao-cli` (`tools/xiao_cli.py`) in Windows `cmd.exe`:

```cmd
:: 1. Discover mounted XIAO-SENSE drive or Rust USB Serial port (e.g. COM10 [2886:0045])
uv run xiao-cli status

:: 2. Build & flash minimal USB serial smoke-test binary (build\deploy-test.uf2)
uv run xiao-cli deploy --smoke-test

:: 3. Build, flash, and run automated 7-point Hardware-in-the-Loop (HIL) test
uv run xiao-cli deploy --test

:: 4. Re-run 7-point HIL test or open interactive live serial monitor
uv run xiao-cli test
uv run xiao-cli monitor
```

---

## 4. Downloaded Upstream Reference Files

- **Seeed XIAO Assistant Skill**: [xiao-assistant.md](./references/xiao-assistant.md) (from [`Seeed-Studio/xiao-assistant`](https://github.com/Seeed-Studio/xiao-assistant))
- **nRF52840 Board Spec**: [nrf52840-board.yaml](./references/nrf52840-board.yaml)
- **Getting Started Guide**: [getting-started-nrf52840.yaml](./references/getting-started-nrf52840.yaml)
- **Audio & PDM Examples**: [audio-examples.yaml](./references/audio-examples.yaml)
- **IMU & Sensor Examples**: [sensors-examples.yaml](./references/sensors-examples.yaml)
- **Low-Power & Sleep Guide**: [low-power.yaml](./references/low-power.yaml)
- **Related nRF52840 MCU Skill**: [`../nrf52840-mcu/SKILL.md`](../nrf52840-mcu/SKILL.md) (from [`alexex1993/mcu-skills`](https://github.com/alexex1993/mcu-skills))
