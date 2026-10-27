---
name: circuitpython-tricks
description: >-
  Real-time CircuitPython tips, timing accuracy patterns, ulab.numpy C-accelerated DSP,
  shadow garbage collection, non-blocking USB serial, NVM persistence, and hardware tricks
  based on todbot/circuitpython-tricks and official CircuitPython documentation.
---

# CircuitPython Real-Time & Hardware Tricks Skill

Use this skill whenever writing, optimizing, or debugging CircuitPython firmware—especially for timing-critical audio, DSP, LED sequencing, or sensor polling loops.

## 1. High-Precision Timing & Avoiding the 30-Bit Float Trap

CircuitPython uses **30-bit small floats** (~21 bits of mantissa, ~6 decimal digits) to avoid heap allocation on every math operation:
- **The Trap:** `time.monotonic()` counts fractional seconds since boot in a 30-bit float. After ~17 minutes of uptime (`1024.0` s), resolution degrades to `~0.5 ms`; after an hour (`4096.0` s), it steps in coarse `2–4 ms` increments. Also `int(0.004 * 1000)` evaluates to `3` instead of `4`.
- **Solution A (`time.monotonic_ns()` Epoch Anchoring):**
  Use 64-bit integer nanoseconds anchored to a startup or resettable epoch so float offsets stay small and retain microsecond precision:
  ```python
  epoch_ns = time.monotonic_ns()
  now_sec = (time.monotonic_ns() - epoch_ns) / 1_000_000_000.0
  ```
- **Solution B (`supervisor.ticks_ms()` Wrap-Safe Integer Milliseconds):**
  `supervisor.ticks_ms()` returns an integer millisecond counter (`0 .. 2^29 - 1`) that never loses 1 ms resolution regardless of uptime:
  ```python
  import supervisor
  _TICKS_PERIOD = 1 << 29
  _TICKS_MAX = _TICKS_PERIOD - 1
  _TICKS_HALFPERIOD = _TICKS_PERIOD >> 1

  def ticks_diff(ticks1: int, ticks2: int) -> int:
      return ((ticks1 - ticks2 + _TICKS_HALFPERIOD) & _TICKS_MAX) - _TICKS_HALFPERIOD
  ```

---

## 2. Garbage Collection & Zero-Allocation Loops

- **Warning on `gc.disable()` + Heap-Allocating Calls (`ulab.numpy`, `time.monotonic_ns()`):**
  - Never combine `gc.disable()` with functions that allocate heap objects on every iteration of a high-rate loop (e.g. 200 Hz audio frames).
  - `time.monotonic_ns()` returns a 64-bit integer that exceeds CircuitPython's 30-bit small-int representation and **allocates a heap BigInt object on every call**.
  - Similarly, `np.array(buf)`, `np.diff(arr)`, and `abs(diffs)` allocate 3 new `ndarray` heap objects per frame (~600 allocations/sec at 200 Hz). If automatic GC is disabled, the 110 KB heap rapidly exhausts and raises `MemoryError`.
- **Zero-Allocation Small-Integer Loops for Short Buffers (`N <= 128`):**
  - For short DMA buffers (like 80 samples @ 16 kHz = 5 ms), a pure-Python integer loop over `array.array("H")` uses only 30-bit small integers, **allocates 0 bytes on the heap**, never triggers GC pauses during quiet tracking, and executes in `< 0.3 ms`.
  - Keep automatic GC enabled when using zero-allocation loops so heap memory remains healthy indefinitely.

---

## 3. C-Accelerated Vector DSP with Built-In `ulab.numpy`

CircuitPython on nRF52840, RP2040/RP2350, SAMD51, and ESP32-S3 compiles in `ulab.numpy`, executing vector math in native C ~10x faster than Python `for` loops.

### Critical `ulab.numpy` Gotchas on Hardware:
1. **Supported `dtype`s ONLY:** `ulab.numpy` supports **only** `np.uint8`, `np.int8`, `np.uint16`, `np.int16`, and `np.float` (the default when `dtype` is omitted). **It does NOT have `np.int32` or `np.int64`** (`AttributeError: 'module' object has no attribute 'int32'`).
2. **Use Built-in `abs()`, NOT `np.abs()`:** `ulab.numpy` does **not** expose `np.abs`. Instead, pass the `ulab.numpy.ndarray` to Python's built-in `abs(arr)`, which invokes `ndarray.__abs__()` in compiled C.
3. **Avoid Unsigned Underflow in `np.diff()`:** Convert unsigned 16-bit audio buffers (`array.array("H")`) to default `np.float` via `np.array(sample_buffer)` before calling `np.diff()`:
   ```python
   from ulab import numpy as np

   arr = np.array(sample_buffer)   # defaults to np.float
   diffs = abs(np.diff(arr))        # C-accelerated |s[i] - s[i-1]|
   hp_peak = int(np.max(diffs))
   peak_idx = int(np.argmax(diffs)) + 1
   hp_mean = float(np.mean(diffs))
   ```

---

## 4. Non-Blocking USB Serial Commands & State Persistence

- **Non-Blocking Serial Input (`supervisor.runtime.serial_bytes_available`):**
  Checking `supervisor.runtime.serial_bytes_available` takes microseconds and allows reading single-key commands over USB CDC Serial without blocking the main loop:
  ```python
  import sys, supervisor
  if supervisor.runtime.serial_bytes_available:
      ch = sys.stdin.read(1)
  ```
- **Persistent State Across Power Cycles (`microcontroller.nvm`):**
  Store mode or calibration bytes in non-volatile memory (`microcontroller.nvm[0]`):
  ```python
  import microcontroller
  saved_mode = microcontroller.nvm[0]
  if microcontroller.nvm[0] != new_mode:
      microcontroller.nvm[0] = new_mode  # Only write when changed to preserve flash wear
  ```
- **Order of Operations in Real-Time Loops:**
  Always update GPIO / LED outputs **before** calling `print()` over USB Serial, as USB CDC buffer flushes can block for several milliseconds.

---

## 5. Local & External References

- **Local Full Cookbook**: [todbot-circuitpython-tricks.md](./references/todbot-circuitpython-tricks.md) (Downloaded from [`todbot/circuitpython-tricks`](https://github.com/todbot/circuitpython-tricks))
- **Upstream Repository**: [https://github.com/todbot/circuitpython-tricks](https://github.com/todbot/circuitpython-tricks)
- **CircuitPython Core Modules Reference**: [https://docs.circuitpython.org/en/latest/shared-bindings/index.html](https://docs.circuitpython.org/en/latest/shared-bindings/index.html)
- **`ulab` Documentation**: [https://micropython-ulab.readthedocs.io/en/latest/](https://micropython-ulab.readthedocs.io/en/latest/)
