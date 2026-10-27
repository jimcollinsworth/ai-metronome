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

## 3. Project HIL Development & Testing Workflow (`xiao-cli`)

Always verify changes on the physical XIAO nRF52840 Sense using `xiao-cli` (`tools/xiao_cli.py`):

```bash
# 1. Discover mounted CIRCUITPY drive (e.g. D:\) and USB Serial port (e.g. COM9)
uv run xiao-cli status

# 2. Deploy code.py and run automated 6-point Hardware-in-the-Loop (HIL) test
uv run xiao-cli hil-test --deploy

# 3. Stream live serial output or listen for live clicks/gestures
uv run xiao-cli hil-test --listen-sec 10
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
