---
name: xiao-assistant
description: >-
  Query the XIAO Assistant MCP tools whenever the user works with Seeed Studio
  XIAO boards: pinouts, specs, deep-sleep power data, code examples
  (Arduino/MicroPython/CircuitPython/Zephyr), upload/boot troubleshooting,
  board selection, or wiki lookups. Triggers on any XIAO mention (esp32c3,
  esp32s3, esp32c5, esp32c6, rp2040, rp2350, nrf52840, nrf54l15, nrf54lm20a,
  mg24, ra4m1, samd21 and Sense/Plus variants) or XIAO-shaped requests
  ("tiny board with wifi", 电池供电的低功耗板子).
---

# XIAO Assistant — usage rules

17 boards, 64 code examples, troubleshooting and internal knowledge, plus a
live wiki.seeedstudio.com search. All pin data verified against the official
wiki. Chinese and misspelled queries both work.

## Decision tree — call tools in this order

| User intent | Tool chain |
|---|---|
| Names a board ("esp32s3", "xiao with camera", "低功耗蓝牙板") | `resolve_board` → `get_pinout` (visual) or `get_board_info` (raw data) |
| Wants working code | `search_examples` (top 3 come with full source + ids) → `get_example` for any listed id → **`compile_sketch` it before handing over** (Arduino sketches only; zephyr/micropython examples can't be compiled here) |
| Hit an error / board misbehaves | `troubleshoot` with the **exact error text** → `search_knowledge` for field-tested fixes → `search_wiki` as last resort |
| Choosing between boards | `resolve_board` with the requirement ("battery BLE under 10µA") — power data is indexed; then `get_board_info` on the shortlist |
| Setup / first flash | `get_quickstart` |
| Support ticket / customer complaint (整段日志) | `diagnose_ticket` — fingerprints first, triage, ready-to-send reply |
| Topic not in the 17 boards | `search_wiki` |

`resolve_board` returns the **best match first (⭐)**, capped at 5 — treat the
first entry as the answer unless the query is genuinely ambiguous.

## Tool reference

| Tool | Key params | Returns |
|---|---|---|
| `resolve_board` | `query` (any language, typos OK) | top-5 boards, ⭐ best match, full specs + low-power line |
| `get_board_info` | `board` id | raw board JSON (pins, connectivity, power, languages) |
| `get_pinout` | `board` id | formatted pin table |
| `search_examples` | `query`, optional `language`, `board` | top 3 with full code + **ID** line; remainder listed by id |
| `get_example` | `id` | one complete example with source |
| `compile_sketch` | `board` + `code` or `exampleId` | real arduino-cli compile - verify sketches BEFORE giving them to the user |
| `diagnose_ticket` | `text` (whole ticket, zh/en, ≤32KB) | triage L1/L2/L3 + ready-to-send Chinese reply — L3 (发烫/短路) NEVER self-fix, tell the user to stop powering and RMA |
| `list_boards` | — | all 17 boards, one line each |
| `get_quickstart` | `board` id | IDE setup + first-upload guide |
| `troubleshoot` | `symptoms` (paste the exact message), optional `board` | diagnosis steps + solutions |
| `search_knowledge` | `query`, optional `board` | support-ticket-grade problems/solutions, often with code |
| `search_wiki` | `query` (English works best) | live wiki page links |

## Hardware gotchas — mention these proactively

- **XIAO ESP32C3 has NO onboard user LED.** `LED_BUILTIN` does not compile on
  its core. Fix: external LED → D10 through a 150 Ω resistor. Blink examples
  for esp32c3 are excluded on purpose.
- **ESP32S3 Sense deep sleep is ~3 mA**, not µA, unless you cut power to the
  camera/SD rail. For µA-level sleep pick nRF52840 (5 µA), MG24 (1.95 µA), or
  nRF54LM20A (4.76 µA / 0.33 µA ship mode).
- **All XIAO are 3.3 V logic** — never wire 5 V signals to a pin.
- **Native USB**: ESP32-series XIAOs need no CP210x/CH340 driver; the port is
  `/dev/ttyACM0` on Linux (not ttyUSB). Upload hangs at "Connecting..." →
  hold BOOT, click Upload, release on connect.
- **Pin numbering**: classic boards use D-numbers (D4=SDA D5=SCL D6=TX D7=RX
  D8=SCK D9=MISO D10=MOSI), but a few boards' rows follow the official wiki's
  GPIO numbering — always read the values from `get_pinout` instead of
  assuming, and say which convention you're using when giving wiring advice.

## Response conventions

- Empty result ≠ broken: blank/garbage queries return `[]` by design.
- `search_examples` keeps responses small (top 3 full code); fetch the rest by
  id via `get_example` instead of re-searching broader.
- If the user hasn't named a board, ask once — but try `resolve_board` on
  their description first, they often described it well enough.
- Camera examples on ESP32S3 reference `camera_pins.h`, which ships inside
  arduino-esp32's CameraWebServer example folder — tell the user to copy it
  or select that example as the base.

## Limits (be honest with users)

- Wiki search scores English page slugs; Chinese wiki queries return nothing —
  translate the term to English first, then `search_wiki`.
- 17 boards are covered locally; XIAO Plus variants (nRF52840 Plus etc.) are
  not yet in the dataset — fall back to `search_wiki` for those.
