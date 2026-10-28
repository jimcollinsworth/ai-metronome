"""Standalone Emergency Recovery Utility for CircuitPython Prototype (`CIRCUITPY`).

This script is completely separated from the daily Rust development workflow (`xiao-cli`).
Use it only if you ever want to restore the archived CircuitPython prototype runtime
and `code.py` onto the Seeed Studio XIAO nRF52840 Sense:

    uv run python tools/restore_circuitpython.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import time
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.xiao_cli import find_xiao_drive, find_xiao_serial_port, trigger_bootloader

PROTOTYPE_CODE_PATH = REPO_ROOT / "src" / "xiao_nrf52840_sense" / "circuitpython" / "code.py"
COMBINED_SD_CP_UF2 = REPO_ROOT / "build" / "circuitpython-with-softdevice-xiao-sense.uf2"
OFFICIAL_CP_UF2 = REPO_ROOT / "build" / "adafruit-circuitpython-Seeed_XIAO_nRF52840_Sense-en_US-9.2.4.uf2"
OFFICIAL_CP_URL = (
    "https://adafruit-circuit-python.s3.amazonaws.com/bin/Seeed_XIAO_nRF52840_Sense/en_US/"
    "adafruit-circuitpython-Seeed_XIAO_nRF52840_Sense-en_US-9.2.4.uf2"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone recovery utility to restore the archived CircuitPython prototype onto XIAO nRF52840 Sense."
    )
    parser.add_argument("--drive", help="Explicit drive letter (e.g. D:\\)")
    parser.add_argument("--port", help="Explicit COM port (e.g. COM9)")
    parser.add_argument("--uf2", help="Custom CircuitPython UF2 path")
    args = parser.parse_args()

    if args.uf2:
        uf2_path = Path(args.uf2).resolve()
    elif COMBINED_SD_CP_UF2.exists():
        uf2_path = COMBINED_SD_CP_UF2
    else:
        uf2_path = OFFICIAL_CP_UF2

    if not uf2_path.exists():
        print(f"[DOWNLOAD] Downloading CircuitPython 9.2.4 UF2 to {uf2_path}...")
        uf2_path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(OFFICIAL_CP_URL, uf2_path)

    drive_path, label, _ = find_xiao_drive(args.drive)
    if not (drive_path and label and label.upper() == "XIAO-SENSE"):
        com_port, _, _ = find_xiao_serial_port(args.port)
        if com_port:
            trigger_bootloader(com_port)
        else:
            print("[BOOTLOADER] Double-click the XIAO Reset button to mount XIAO-SENSE...")

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            d_path, d_label, _ = find_xiao_drive(args.drive)
            if d_path and d_label and d_label.upper() == "XIAO-SENSE":
                drive_path = d_path
                break
            time.sleep(0.4)

    if not drive_path:
        print("[ERROR] XIAO-SENSE bootloader drive not found. Double-click Reset and re-run.")
        return 1

    print(f"[RESTORE] Flashing {uf2_path.name} -> {drive_path} ...")
    try:
        shutil.copyfile(uf2_path, drive_path / uf2_path.name)
    except OSError:
        pass

    print("[RESTORE] Waiting for CIRCUITPY drive to mount...")
    cp_drive: Path | None = None
    deadline = time.monotonic() + 18.0
    time.sleep(2.0)
    while time.monotonic() < deadline:
        d_path, d_label, _ = find_xiao_drive(args.drive)
        if d_path and d_label and d_label.upper() == "CIRCUITPY":
            cp_drive = d_path
            break
        time.sleep(0.5)

    if not cp_drive:
        print("[ERROR] CIRCUITPY drive did not mount within 18s.")
        return 1

    if PROTOTYPE_CODE_PATH.exists():
        shutil.copyfile(PROTOTYPE_CODE_PATH, cp_drive / "code.py")
        print(f"[RESTORE] Copied archived {PROTOTYPE_CODE_PATH.name} -> {cp_drive / 'code.py'}")

    print("[SUCCESS] CircuitPython prototype restored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
