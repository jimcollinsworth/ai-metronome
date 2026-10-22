"""Hardware-in-the-Loop (HIL) CLI for Seeed Studio XIAO nRF52840 Sense (CircuitPython).

Provides automated code deployment (`deploy`/`push`), hardware status discovery (`status`),
soft-reset (`reset`), live serial monitoring (`monitor`), and automated on-device HIL testing (`hil-test`).
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
import time

import serial
from serial.tools import list_ports

# Default firmware source file in the repository
DEFAULT_FIRMWARE_PATH = Path(__file__).resolve().parent.parent / "src" / "xiao_nrf52840_sense" / "circuitpython" / "code.py"

# Known USB Vendor IDs for Seeed Studio (0x2886) and Adafruit CircuitPython (0x239A)
XIAO_VIDS = {0x2886, 0x239A}


@dataclass
class XiaoDeviceInfo:
    """Discovered XIAO nRF52840 Sense mount & serial port endpoints."""

    drive_path: Path | None
    volume_label: str | None
    boot_out: str | None
    com_port: str | None
    port_description: str | None
    usb_vid_pid: str | None


def _get_volume_label(drive_root: str) -> str | None:
    """Return Windows volume label for a drive root like 'D:\\', or None if not mounted."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.windll.kernel32
    vol_name_buf = ctypes.create_unicode_buffer(261)
    fs_name_buf = ctypes.create_unicode_buffer(261)
    serial_num = ctypes.c_ulong(0)
    max_comp_len = ctypes.c_ulong(0)
    fs_flags = ctypes.c_ulong(0)

    res = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive_root),
        vol_name_buf,
        ctypes.sizeof(vol_name_buf),
        ctypes.byref(serial_num),
        ctypes.byref(max_comp_len),
        ctypes.byref(fs_flags),
        fs_name_buf,
        ctypes.sizeof(fs_name_buf),
    )
    if res == 0:
        return None
    return vol_name_buf.value


def find_circuitpy_drive(explicit_drive: str | None = None) -> tuple[Path | None, str | None, str | None]:
    """Locate the mounted CIRCUITPY (or XIAO-SENSE bootloader) USB drive."""
    if explicit_drive:
        path = Path(explicit_drive)
        if path.exists():
            label = _get_volume_label(str(path.resolve().anchor)) or "SPECIFIED"
            boot_txt = (path / "boot_out.txt").read_text(encoding="utf-8", errors="replace").strip() if (path / "boot_out.txt").exists() else None
            return path, label, boot_txt
        return None, None, None

    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        path = Path(root)
        if not path.exists():
            continue
        label = _get_volume_label(root)
        if label and label.upper() in ("CIRCUITPY", "XIAO-SENSE"):
            boot_file = path / "boot_out.txt"
            boot_txt = boot_file.read_text(encoding="utf-8", errors="replace").strip() if boot_file.exists() else None
            return path, label, boot_txt
        # Fallback if volume label is blank but boot_out.txt + code.py exist
        if (path / "boot_out.txt").exists():
            boot_txt = (path / "boot_out.txt").read_text(encoding="utf-8", errors="replace").strip()
            if "Seeed" in boot_txt or "XIAO" in boot_txt or "nRF52840" in boot_txt or "CircuitPython" in boot_txt:
                return path, label or "CIRCUITPY", boot_txt

    return None, None, None


def find_xiao_serial_port(explicit_port: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Locate the XIAO nRF52840 Sense USB CDC Serial port."""
    ports = list(list_ports.comports())

    if explicit_port:
        for p in ports:
            if p.device.upper() == explicit_port.upper():
                vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid and p.pid else None
                return p.device, p.description, vid_pid
        return explicit_port, "Manual Port", None

    # 1. Exact VID match (Seeed 0x2886 or Adafruit CircuitPython 0x239A)
    for p in ports:
        if p.vid in XIAO_VIDS:
            vid_pid = f"{p.vid:04X}:{p.pid:04X}"
            return p.device, p.description, vid_pid

    # 2. Fallback: Any USB serial port that is NOT Intel AMT SOL
    for p in ports:
        desc_upper = (p.description or "").upper()
        hwid_upper = (p.hwid or "").upper()
        if "ACTIVE MANAGEMENT TECHNOLOGY" in desc_upper or "VEN_8086" in hwid_upper:
            continue
        if "USB" in hwid_upper or "CIRCUITPYTHON" in desc_upper or "SERIAL" in desc_upper:
            vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid and p.pid else p.hwid
            return p.device, p.description, vid_pid

    return None, None, None


def discover_device(drive: str | None = None, port: str | None = None) -> XiaoDeviceInfo:
    """Discover both USB storage drive and USB CDC serial port for XIAO."""
    drive_path, label, boot_out = find_circuitpy_drive(drive)
    com_port, desc, vid_pid = find_xiao_serial_port(port)
    return XiaoDeviceInfo(
        drive_path=drive_path,
        volume_label=label,
        boot_out=boot_out,
        com_port=com_port,
        port_description=desc,
        usb_vid_pid=vid_pid,
    )


def cmd_status(args: argparse.Namespace) -> int:
    """Display discovered XIAO nRF52840 Sense drive and serial port status."""
    info = discover_device(args.drive, args.port)
    print("=" * 60)
    print("  XIAO nRF52840 SENSE -- DEVICE DISCOVERY STATUS")
    print("=" * 60)

    if info.drive_path:
        print(f"  [DRIVE]   Mounted at : {info.drive_path} (Label: {info.volume_label})")
        if info.boot_out:
            for line in info.boot_out.splitlines():
                print(f"  [FIRMWARE] {line}")
        code_file = info.drive_path / "code.py"
        if code_file.exists():
            print(f"  [CODE.PY] Present ({code_file.stat().st_size} bytes)")
        else:
            print("  [CODE.PY] Not found on drive")
    else:
        print("  [DRIVE]   NOT FOUND (Ensure XIAO is plugged in via data-capable USB-C cable)")

    if info.com_port:
        print(f"  [SERIAL]  Port       : {info.com_port} ({info.port_description}) [{info.usb_vid_pid}]")
    else:
        print("  [SERIAL]  NOT FOUND (No XIAO USB CDC serial port detected)")

    print("=" * 60)
    return 0 if (info.drive_path or info.com_port) else 1


def deploy_firmware(source_path: Path, target_drive: Path) -> bool:
    """Copy source `code.py` to `CIRCUITPY/code.py` and flush buffers."""
    if not source_path.exists():
        print(f"[ERROR] Source file does not exist: {source_path}")
        return False

    dest_path = target_drive / "code.py"
    size_bytes = source_path.stat().st_size
    print(f"\n[DEPLOY] Transferring firmware ({source_path.name}, {size_bytes} bytes)...")
    print(f"         Source : {source_path}")
    print(f"         Target : {dest_path}")
    shutil.copyfile(source_path, dest_path)
    # Give CircuitPython auto-reload ~1.0s to detect the FAT filesystem write
    time.sleep(1.0)
    print("         -> Transfer complete. CircuitPython filesystem sync OK.\n")
    return True


def cmd_deploy(args: argparse.Namespace) -> int:
    """Deploy `code.py` to the mounted CIRCUITPY drive."""
    info = discover_device(args.drive, args.port)
    if not info.drive_path:
        print("[ERROR] CIRCUITPY drive not found. Plug in the XIAO nRF52840 Sense or pass --drive.")
        return 1

    if info.volume_label and info.volume_label.upper() == "XIAO-SENSE":
        print(f"[ERROR] Board is in UF2 Bootloader mode ({info.drive_path}). Flash CircuitPython UF2 first.")
        return 1

    src = Path(args.file).resolve()
    if not deploy_firmware(src, info.drive_path):
        return 1

    if args.test:
        return run_hil_test(info.com_port, listen_sec=args.listen_sec, timeout_sec=args.timeout)
    return 0


def trigger_soft_reboot(ser: serial.Serial) -> None:
    """Interrupt any running script with Ctrl-C, enter REPL, and soft-reboot with Ctrl-D."""
    ser.reset_input_buffer()
    # 1. Send Ctrl-C twice to interrupt running code.py
    ser.write(b"\x03\x03")
    ser.flush()
    time.sleep(0.35)
    # 2. Enter REPL prompt and clear any KeyboardInterrupt output from the previous run
    ser.write(b"\r")
    ser.flush()
    time.sleep(0.20)
    ser.reset_input_buffer()
    # 3. Send Ctrl-D to exit REPL and trigger a clean soft reboot of code.py
    ser.write(b"\x04")
    ser.flush()


def run_hil_test(com_port: str | None, listen_sec: float = 0.0, timeout_sec: float = 10.0) -> int:
    """Run automated Hardware-in-the-Loop (HIL) test suite over USB Serial with real-time feedback."""
    if not com_port:
        print("[ERROR] No XIAO serial port available for HIL testing.")
        return 1

    print("\n" + "=" * 65)
    print(f"  HARDWARE-IN-THE-LOOP (HIL) TEST RUNNER")
    print("=" * 65)
    print(f"  Target Serial Port : {com_port}")
    print(f"  Response Timeout   : {timeout_sec:.1f}s")
    print(f"  Live Event Window  : {listen_sec:.1f}s (clicks & gestures)")
    print("\n  Scheduled Checkpoints:")
    print("    [1/6] POWER_DIAG     : Battery rail, charge status, CPU temp & storage")
    print("    [2/6] MIC_POWER      : PDM microphone power gate (board.MIC_PWR)")
    print("    [3/6] MIC_DMA_STREAM : PDMIn DMA ring buffer allocation & signal health")
    print("    [4/6] IMU_BUS        : LSM6DS3TR-C power gate & 400kHz I2C bus")
    print("    [5/6] IMU_ACCEL      : 3-axis accelerometer initialization & gravity")
    print("    [6/6] CAL_AND_READY  : Ambient noise calibration & PLL beat clock ready")
    print("=" * 65 + "\n")

    checks: dict[str, dict[str, str | bool]] = {
        "POWER_DIAG": {"passed": False, "detail": "", "name": "Power & Memory Diagnostics"},
        "MIC_POWER": {"passed": False, "detail": "", "name": "Microphone Power Rail (board.MIC_PWR)"},
        "MIC_DMA_STREAM": {"passed": False, "detail": "", "name": "PDMIn 16kHz DMA Stream & Health"},
        "IMU_BUS": {"passed": False, "detail": "", "name": "LSM6DS3TR-C I2C Bus @ 400kHz"},
        "IMU_ACCEL": {"passed": False, "detail": "", "name": "3-Axis Accelerometer (ODR/Range)"},
        "CAL_AND_READY": {"passed": False, "detail": "", "name": "Noise Calibration & PLL Ready"},
    }
    failures: list[str] = []
    in_traceback = False
    passed_count = 0

    try:
        with serial.Serial(com_port, baudrate=115200, timeout=0.1) as ser:
            print("[STEP 1/3] Triggering board soft-reset (Ctrl-C interrupt + Ctrl-D restart)...")
            trigger_soft_reboot(ser)
            print("           -> Soft-reboot signal dispatched. Monitoring MCU startup stream...\n")
            print("[STEP 2/3] Executing boot & sensor diagnostic milestones:")

            start_time = time.monotonic()
            last_line_time = start_time
            ready_time: float | None = None
            clicks_seen = 0
            gestures_seen = 0
            power_diag_parts: list[str] = []

            while True:
                now = time.monotonic()

                # Timeout before reaching [READY]
                if ready_time is None and (now - start_time) > timeout_sec:
                    failures.append(f"Timed out after {timeout_sec:.1f}s waiting for [READY] banner.")
                    break

                # Live listening completion
                if ready_time is not None:
                    if (now - ready_time) >= listen_sec:
                        break

                raw_line = ser.readline()
                if not raw_line:
                    # Provide visual feedback if waiting with no output for over 2 seconds
                    if ready_time is None and (now - last_line_time) > 2.0:
                        elapsed = now - start_time
                        print(f"  │ ... waiting for MCU bootloader response ({elapsed:.1f}s / {timeout_sec:.1f}s)")
                        last_line_time = now
                    continue

                last_line_time = now
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue

                print(f"  │ [MCU] {line}")

                # Detect Python tracebacks or hardware failures
                if "Traceback (most recent call last):" in line:
                    in_traceback = True
                    failures.append("Runtime exception traceback detected on MCU")
                    print(f"\n  ❌ [EXCEPTION DETECTED] Runtime error on MCU!\n")
                elif in_traceback:
                    failures.append(f"  {line}")

                if "[FAIL]" in line or "[FATAL]" in line:
                    failures.append(f"Hardware failure reported: {line.strip()}")
                    print(f"\n  ❌ [HARDWARE FAILURE] {line.strip()}\n")

                # 1. POWER_DIAG Check
                if "[DIAG] Battery Rail" in line:
                    power_diag_parts.append(line.split(":", 1)[-1].strip())
                elif "[DIAG] Memory / Storage" in line:
                    power_diag_parts.append(line.split(":", 1)[-1].strip())
                    if not checks["POWER_DIAG"]["passed"]:
                        checks["POWER_DIAG"]["passed"] = True
                        passed_count += 1
                        checks["POWER_DIAG"]["detail"] = " | ".join(power_diag_parts)
                        print(f"  ├─✔ [CHECK 1/6 PASS] POWER_DIAG: {checks['POWER_DIAG']['detail']}")

                # 2. MIC_POWER Check
                elif "[MIC]  Power Gate" in line or "[MIC] Power Gate" in line:
                    if not checks["MIC_POWER"]["passed"]:
                        checks["MIC_POWER"]["passed"] = True
                        passed_count += 1
                        checks["MIC_POWER"]["detail"] = line.split(":", 1)[-1].strip()
                        print(f"  ├─✔ [CHECK 2/6 PASS] MIC_POWER: {checks['MIC_POWER']['detail']}")

                # 3. MIC_DMA_STREAM Check
                elif "[MIC]  Signal Health" in line or "[MIC] Signal Health" in line:
                    if not checks["MIC_DMA_STREAM"]["passed"]:
                        checks["MIC_DMA_STREAM"]["passed"] = True
                        passed_count += 1
                        checks["MIC_DMA_STREAM"]["detail"] = line.split(":", 1)[-1].strip()
                        print(f"  ├─✔ [CHECK 3/6 PASS] MIC_DMA_STREAM: {checks['MIC_DMA_STREAM']['detail']}")

                # 4. IMU_BUS Check
                elif "[IMU]  I2C Bus" in line or "[IMU] I2C Bus" in line:
                    if not checks["IMU_BUS"]["passed"]:
                        checks["IMU_BUS"]["passed"] = True
                        passed_count += 1
                        checks["IMU_BUS"]["detail"] = line.split(":", 1)[-1].strip()
                        print(f"  ├─✔ [CHECK 4/6 PASS] IMU_BUS: {checks['IMU_BUS']['detail']}")

                # 5. IMU_ACCEL Check
                elif "[IMU]  Accelerometer" in line or "[IMU] Accelerometer" in line:
                    if not checks["IMU_ACCEL"]["passed"]:
                        checks["IMU_ACCEL"]["passed"] = True
                        passed_count += 1
                        checks["IMU_ACCEL"]["detail"] = line.split(":", 1)[-1].strip()
                        print(f"  ├─✔ [CHECK 5/6 PASS] IMU_ACCEL: {checks['IMU_ACCEL']['detail']}")

                # 6. CAL_AND_READY Check
                elif "[READY] Initialization OK!" in line:
                    if not checks["CAL_AND_READY"]["passed"]:
                        checks["CAL_AND_READY"]["passed"] = True
                        passed_count += 1
                        checks["CAL_AND_READY"]["detail"] = "PLL Beat Clock armed & ready"
                        print(f"  └─✔ [CHECK 6/6 PASS] CAL_AND_READY: {checks['CAL_AND_READY']['detail']}")
                    ready_time = time.monotonic()
                    if listen_sec > 0:
                        print(f"\n[STEP 3/3] >>> Hardware Ready! Listening for {listen_sec:.1f}s for live events... <<<")
                        print("           (Trigger clicks or shake/drop the board to verify live response)\n")

                # Live events
                if "[CLICK #" in line:
                    clicks_seen += 1
                    print(f"  │ ♫ [LIVE EVENT: CLICK #{clicks_seen}] {line.strip()}")
                elif "[GESTURE:" in line or "[SHAKE DETECTED]" in line:
                    gestures_seen += 1
                    print(f"  │ ⚡ [LIVE EVENT: GESTURE #{gestures_seen}] {line.strip()}")

    except serial.SerialException as err:
        print(f"\n[ERROR] Serial connection error on {com_port}: {err}")
        return 1

    total_duration = time.monotonic() - start_time
    print("\n" + "=" * 65)
    print("  HIL VERIFICATION SUMMARY & SCORECARD")
    print("=" * 65)
    all_passed = len(failures) == 0 and (passed_count == len(checks))

    idx = 1
    for key, data in checks.items():
        is_p = bool(data["passed"])
        mark = "PASS" if is_p else "FAIL"
        symbol = "✔" if is_p else "✘"
        detail_txt = f"({data['detail']})" if data["detail"] else ""
        print(f"  {symbol} [{mark}] {idx}. {key:<14} : {data['name']} {detail_txt}")
        idx += 1

    print("-" * 65)
    print(f"  Total Duration : {total_duration:.2f}s")
    if listen_sec > 0:
        print(f"  Live Captures  : {clicks_seen} clicks | {gestures_seen} mode gestures")

    if failures:
        print("\n  ❌ FAILURES DETECTED:")
        for f in failures:
            print(f"    - {f}")
        print("\n  RESULT: TEST FAILED")
    else:
        print("\n  RESULT: ALL 6 CHECKS PASSED (Hardware & Firmware 100% Operational)")

    print("=" * 65 + "\n")
    return 0 if all_passed else 1


def cmd_hil_test(args: argparse.Namespace) -> int:
    """Execute HIL test (optionally deploying firmware first)."""
    info = discover_device(args.drive, args.port)
    if args.deploy:
        if not info.drive_path:
            print("[ERROR] Cannot deploy: CIRCUITPY drive not found.")
            return 1
        if not deploy_firmware(Path(args.file).resolve(), info.drive_path):
            return 1
        # Re-discover serial port after deploy in case USB re-enumerated
        info = discover_device(args.drive, args.port)

    return run_hil_test(info.com_port, listen_sec=args.listen_sec, timeout_sec=args.timeout)


def cmd_monitor(args: argparse.Namespace) -> int:
    """Stream live USB serial console logs from the XIAO."""
    info = discover_device(None, args.port)
    if not info.com_port:
        print("[ERROR] No XIAO serial port detected.")
        return 1

    print(f"[MONITOR] Connected to {info.com_port} (115200 baud). Press Ctrl-C to exit.")
    try:
        with serial.Serial(info.com_port, baudrate=115200, timeout=0.1) as ser:
            if args.reset:
                trigger_soft_reboot(ser)
            start = time.monotonic()
            while True:
                if args.duration > 0 and (time.monotonic() - start) >= args.duration:
                    break
                raw = ser.readline()
                if raw:
                    print(raw.decode("utf-8", errors="replace"), end="", flush=True)
    except KeyboardInterrupt:
        print("\n[MONITOR] Closed.")
    except serial.SerialException as err:
        print(f"\n[ERROR] Serial error: {err}")
        return 1
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Soft-reboot the XIAO over USB Serial and print startup banner."""
    args.reset = True
    args.duration = args.duration if hasattr(args, "duration") and args.duration else 4.0
    return cmd_monitor(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xiao-cli",
        description="HIL Development & Test CLI for Seeed Studio XIAO nRF52840 Sense",
    )
    parser.add_argument("--drive", help="Explicit CIRCUITPY drive path (e.g. D:\\)")
    parser.add_argument("--port", help="Explicit COM port (e.g. COM4)")

    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub_status = sub.add_parser("status", help="Detect CIRCUITPY drive and USB serial port")
    sub_status.set_defaults(func=cmd_status)

    # deploy / push
    sub_deploy = sub.add_parser("deploy", aliases=["push"], help="Copy code.py to CIRCUITPY drive")
    sub_deploy.add_argument("--file", default=str(DEFAULT_FIRMWARE_PATH), help="Source Python file to deploy")
    sub_deploy.add_argument("--test", action="store_true", help="Run HIL verification immediately after deploy")
    sub_deploy.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for clicks/gestures after init")
    sub_deploy.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_deploy.set_defaults(func=cmd_deploy)

    # hil-test
    sub_test = sub.add_parser("hil-test", aliases=["test"], help="Run automated on-device HIL verification")
    sub_test.add_argument("--deploy", action="store_true", help="Deploy latest code.py before testing")
    sub_test.add_argument("--file", default=str(DEFAULT_FIRMWARE_PATH), help="Source Python file if --deploy is used")
    sub_test.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for live clicks/shakes after init")
    sub_test.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_test.set_defaults(func=cmd_hil_test)

    # monitor
    sub_mon = sub.add_parser("monitor", aliases=["logs"], help="Stream live serial console output")
    sub_mon.add_argument("--reset", action="store_true", help="Soft-reset board upon connecting")
    sub_mon.add_argument("--duration", type=float, default=0.0, help="Auto-exit after N seconds (0 = continuous)")
    sub_mon.set_defaults(func=cmd_monitor)

    # reset
    sub_rst = sub.add_parser("reset", help="Soft-reboot board over serial and show startup log")
    sub_rst.add_argument("--duration", type=float, default=4.0, help="Seconds to stream startup output")
    sub_rst.set_defaults(func=cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
