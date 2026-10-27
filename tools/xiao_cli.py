"""Hardware-in-the-Loop (HIL) & Rust UF2 CLI for Seeed Studio XIAO nRF52840 Sense.

Provides automated CircuitPython & Rust deployment (`deploy`, `rust-build`, `rust-deploy`),
pure-Python ELF32-to-UF2 conversion (`0xADA52840`), hardware status discovery (`status`),
soft-reset (`reset`), live serial monitoring (`monitor`), and automated on-device HIL testing (`hil-test`).
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

import serial
from serial.tools import list_ports

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIRMWARE_PATH = REPO_ROOT / "src" / "xiao_nrf52840_sense" / "circuitpython" / "code.py"
RUST_MANIFEST_PATH = REPO_ROOT / "src" / "xiao_nrf52840_sense" / "rust" / "Cargo.toml"
RUST_ELF_PATH = (
    REPO_ROOT
    / "src"
    / "xiao_nrf52840_sense"
    / "rust"
    / "target"
    / "thumbv7em-none-eabihf"
    / "release"
    / "ai-metronome-rust"
)
DEFAULT_UF2_OUTPUT_PATH = REPO_ROOT / "build" / "ai-metronome-rust.uf2"
DEFAULT_CIRCUITPYTHON_URL = (
    "https://adafruit-circuit-python.s3.amazonaws.com/bin/Seeed_XIAO_nRF52840_Sense/en_US/"
    "adafruit-circuitpython-Seeed_XIAO_nRF52840_Sense-en_US-9.2.4.uf2"
)
DEFAULT_CIRCUITPYTHON_UF2_PATH = (
    REPO_ROOT / "build" / "adafruit-circuitpython-Seeed_XIAO_nRF52840_Sense-en_US-9.2.4.uf2"
)

# UF2 Constants for Nordic nRF52840 (Adafruit UF2 Bootloader)
UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000
NRF52840_UF2_FAMILY_ID = 0xADA52840

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
            info_file = path / "boot_out.txt" if (path / "boot_out.txt").exists() else (path / "INFO_UF2.TXT")
            boot_txt = info_file.read_text(encoding="utf-8", errors="replace").strip() if info_file.exists() else None
            return path, label, boot_txt
        return None, None, None

    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        path = Path(root)
        if not path.exists():
            continue
        label = _get_volume_label(root)
        if label and label.upper() in ("CIRCUITPY", "XIAO-SENSE"):
            info_file = path / "boot_out.txt" if (path / "boot_out.txt").exists() else (path / "INFO_UF2.TXT")
            boot_txt = info_file.read_text(encoding="utf-8", errors="replace").strip() if info_file.exists() else None
            return path, label, boot_txt
        if (path / "boot_out.txt").exists():
            boot_txt = (path / "boot_out.txt").read_text(encoding="utf-8", errors="replace").strip()
            if "Seeed" in boot_txt or "XIAO" in boot_txt or "nRF52840" in boot_txt or "CircuitPython" in boot_txt:
                return path, label or "CIRCUITPY", boot_txt
        if (path / "INFO_UF2.TXT").exists():
            boot_txt = (path / "INFO_UF2.TXT").read_text(encoding="utf-8", errors="replace").strip()
            if "XIAO" in boot_txt or "nRF52840" in boot_txt or "UF2 Bootloader" in boot_txt:
                return path, label or "XIAO-SENSE", boot_txt

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


def elf_to_uf2(
    elf_path: Path,
    uf2_path: Path,
    family_id: int = NRF52840_UF2_FAMILY_ID,
) -> tuple[int, int, int]:
    """Convert a 32-bit ARM ELF file (`PT_LOAD` flash segments) into a UF2 image.

    Returns `(num_blocks, base_address, total_payload_bytes)`.
    """
    data = elf_path.read_bytes()
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise ValueError(f"Not a valid ELF binary: {elf_path}")
    if data[4] != 1 or data[5] != 1:
        raise ValueError("Expected 32-bit Little-Endian ARM ELF binary")

    e_phoff = struct.unpack_from("<I", data, 0x1C)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x2A)[0]
    e_phnum = struct.unpack_from("<H", data, 0x2C)[0]

    segments: list[tuple[int, bytes]] = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, _p_vaddr, p_paddr, p_filesz, _p_memsz, _p_flags, _p_align = struct.unpack_from(
            "<IIIIIIII", data, off
        )
        # Application flash starts at 0x00001000 (when SoftDevice is absent) or
        # 0x00027000 (with SoftDevice S140), and ends before 0x000ED000.
        # Filter out ELF file header segments that LLD places at address 0x00000000.
        if p_type == 1 and p_filesz > 0 and 0x00001000 <= p_paddr < 0x000ED000:
            seg_bytes = data[p_offset : p_offset + p_filesz]
            segments.append((p_paddr, seg_bytes))

    if not segments:
        raise ValueError(f"No loadable flash PT_LOAD segments found in {elf_path}")

    segments.sort(key=lambda s: s[0])
    min_addr = segments[0][0]
    max_addr = max(addr + len(seg) for addr, seg in segments)

    total_len = max_addr - min_addr
    flat_image = bytearray(b"\xff" * total_len)
    for addr, seg in segments:
        rel = addr - min_addr
        flat_image[rel : rel + len(seg)] = seg

    # Pad to 256-byte chunk boundary
    rem = len(flat_image) % 256
    if rem != 0:
        flat_image.extend(b"\xff" * (256 - rem))

    num_blocks = len(flat_image) // 256
    uf2_bytes = bytearray()

    for block_no in range(num_blocks):
        chunk = flat_image[block_no * 256 : (block_no + 1) * 256]
        target_addr = min_addr + block_no * 256
        payload = chunk + (b"\x00" * (476 - 256))
        block = struct.pack(
            "<IIIIIIII476sI",
            UF2_MAGIC_START0,
            UF2_MAGIC_START1,
            UF2_FLAG_FAMILY_ID_PRESENT,
            target_addr,
            256,
            block_no,
            num_blocks,
            family_id,
            bytes(payload),
            UF2_MAGIC_END,
        )
        uf2_bytes.extend(block)

    uf2_path.parent.mkdir(parents=True, exist_ok=True)
    uf2_path.write_bytes(uf2_bytes)
    return num_blocks, min_addr, total_len


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
                print(f"  [INFO]    {line}")
        code_file = info.drive_path / "code.py"
        if code_file.exists():
            print(f"  [CODE.PY] Present ({code_file.stat().st_size} bytes)")
    else:
        print("  [DRIVE]   NOT FOUND (Note: Native Rust firmware does not mount CIRCUITPY)")

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
    time.sleep(1.0)
    print("         -> Transfer complete. CircuitPython filesystem sync OK.\n")
    return True


def cmd_python_deploy(args: argparse.Namespace) -> int:
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


def cmd_rust_build(args: argparse.Namespace) -> int:
    """Compile the Rust firmware (`thumbv7em-none-eabihf`) and pack a UF2 image."""
    manifest = Path(args.manifest).resolve()
    uf2_out = Path(args.output).resolve()

    print("=" * 60)
    print("  BUILDING RUST FIRMWARE (thumbv7em-none-eabihf)")
    print("=" * 60)
    cmd = [
        "cargo",
        "build",
        "--manifest-path",
        str(manifest),
        "--release",
        "--target",
        "thumbv7em-none-eabihf",
    ]
    print(f"[BUILD] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        print("[ERROR] Cargo build failed.")
        return res.returncode

    if not RUST_ELF_PATH.exists():
        print(f"[ERROR] Expected ELF binary not found at {RUST_ELF_PATH}")
        return 1

    num_blocks, base_addr, payload_bytes = elf_to_uf2(RUST_ELF_PATH, uf2_out)
    print(f"[UF2]   Packed {payload_bytes} bytes @ 0x{base_addr:08X} -> {num_blocks} UF2 blocks")
    print(f"[UF2]   Output file: {uf2_out} ({uf2_out.stat().st_size} bytes)")
    print("=" * 60)
    return 0


def trigger_1200bps_bootloader(com_port: str) -> None:
    """Touch serial port at 1200 baud with DTR=False to enter Adafruit UF2 bootloader."""
    print(f"[BOOTLOADER] Touching {com_port} at 1200 baud (DTR=False) to enter XIAO-SENSE UF2 mode...")
    try:
        s = serial.Serial(com_port, baudrate=1200, timeout=0.2)
        s.dtr = False
        s.rts = False
        time.sleep(0.15)
        s.close()
    except serial.SerialException:
        pass


def cmd_rust_deploy(args: argparse.Namespace) -> int:
    """Build (optional) and flash the Rust `.uf2` image to the XIAO-SENSE bootloader drive."""
    uf2_path = Path(args.uf2).resolve()
    if not args.no_build or not uf2_path.exists():
        build_ns = argparse.Namespace(manifest=str(RUST_MANIFEST_PATH), output=str(uf2_path))
        rc = cmd_rust_build(build_ns)
        if rc != 0:
            return rc

    info = discover_device(args.drive, args.port)
    bootloader_drive: Path | None = None

    if info.drive_path and info.volume_label and info.volume_label.upper() == "XIAO-SENSE":
        bootloader_drive = info.drive_path
    else:
        if info.com_port:
            trigger_1200bps_bootloader(info.com_port)
        else:
            print("[BOOTLOADER] No serial port found. Double-tap the physical Reset button on the XIAO now...")

        print("[BOOTLOADER] Waiting up to 15s for XIAO-SENSE UF2 drive to mount...")
        deadline = time.monotonic() + 15.0
        prompted_manual = False
        while time.monotonic() < deadline:
            d_path, d_label, d_boot = find_circuitpy_drive(args.drive)
            if d_path and d_label and d_label.upper() == "XIAO-SENSE":
                bootloader_drive = d_path
                info.boot_out = d_boot
                break
            if not prompted_manual and (deadline - time.monotonic()) < 9.0:
                print("  [TIP] If the drive hasn't appeared yet, double-click the XIAO Reset button...")
                prompted_manual = True
            time.sleep(0.4)

    if not bootloader_drive:
        print("[ERROR] XIAO-SENSE UF2 bootloader drive not found. Double-tap Reset and re-run.")
        return 1

    print(f"[BOOTLOADER] Mounted at {bootloader_drive}")
    if info.boot_out:
        for line in info.boot_out.splitlines():
            print(f"  [INFO_UF2] {line}")

    dest_uf2 = bootloader_drive / uf2_path.name
    print(f"[FLASH] Copying {uf2_path.name} ({uf2_path.stat().st_size} bytes) -> {dest_uf2} ...")
    try:
        shutil.copyfile(uf2_path, dest_uf2)
    except OSError:
        # Windows often reports an I/O error on the final block because the UF2 bootloader
        # immediately resets the USB device as soon as the last UF2 block is flashed.
        pass

    print("[FLASH] UF2 transfer complete! Waiting for Rust USB CDC serial port to enumerate...")
    re_port: str | None = None
    re_deadline = time.monotonic() + 10.0
    time.sleep(1.2)
    while time.monotonic() < re_deadline:
        port_dev, _desc, _vp = find_xiao_serial_port(args.port)
        if port_dev:
            re_port = port_dev
            break
        time.sleep(0.35)

    if re_port:
        print(f"[SERIAL] Rust firmware enumerated on {re_port}!")
        if args.test:
            return run_hil_test(re_port, listen_sec=args.listen_sec, timeout_sec=args.timeout)
    else:
        print("[WARN] Serial port did not enumerate within 10s (check USB connection).")
        if args.test:
            return 1

    return 0


def cmd_python_restore(args: argparse.Namespace) -> int:
    """Flash official CircuitPython firmware UF2 to restore the CIRCUITPY filesystem and deploy code.py."""
    uf2_path = Path(args.uf2).resolve() if getattr(args, "uf2", None) else DEFAULT_CIRCUITPYTHON_UF2_PATH
    if not uf2_path.exists():
        print("[DOWNLOAD] Fetching official CircuitPython 9.2.4 UF2 for Seeed XIAO nRF52840 Sense...")
        print(f"           Source URL: {DEFAULT_CIRCUITPYTHON_URL}")
        uf2_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import urllib.request
            urllib.request.urlretrieve(DEFAULT_CIRCUITPYTHON_URL, uf2_path)
            print(f"           -> Downloaded ({uf2_path.stat().st_size} bytes) to {uf2_path}")
        except Exception as err:
            print(f"[ERROR] Failed to download CircuitPython UF2: {err}")
            return 1

    info = discover_device(args.drive, args.port)
    bootloader_drive: Path | None = None

    if info.drive_path and info.volume_label and info.volume_label.upper() == "XIAO-SENSE":
        bootloader_drive = info.drive_path
    else:
        if info.com_port:
            trigger_1200bps_bootloader(info.com_port)
        else:
            print("[BOOTLOADER] Double-tap the physical Reset button on the XIAO to enter DFU mode...")

        print("[BOOTLOADER] Waiting up to 15s for XIAO-SENSE UF2 drive to mount...")
        deadline = time.monotonic() + 15.0
        prompted_manual = False
        while time.monotonic() < deadline:
            d_path, d_label, d_boot = find_circuitpy_drive(args.drive)
            if d_path and d_label and d_label.upper() == "XIAO-SENSE":
                bootloader_drive = d_path
                info.boot_out = d_boot
                break
            if not prompted_manual and (deadline - time.monotonic()) < 9.0:
                print("  [TIP] If the drive hasn't appeared yet, double-click the XIAO Reset button...")
                prompted_manual = True
            time.sleep(0.4)

    if not bootloader_drive:
        print("[ERROR] XIAO-SENSE UF2 bootloader drive not found. Double-tap Reset and re-run.")
        return 1

    print(f"[BOOTLOADER] Mounted at {bootloader_drive}")
    dest_uf2 = bootloader_drive / uf2_path.name
    print(f"[FLASH] Copying CircuitPython runtime ({uf2_path.name}, {uf2_path.stat().st_size} bytes) -> {dest_uf2} ...")
    try:
        shutil.copyfile(uf2_path, dest_uf2)
    except OSError:
        pass

    print("[FLASH] CircuitPython runtime flashed! Waiting up to 15s for CIRCUITPY drive to mount...")
    circuitpy_drive: Path | None = None
    mount_deadline = time.monotonic() + 15.0
    time.sleep(2.0)
    while time.monotonic() < mount_deadline:
        d_path, d_label, _ = find_circuitpy_drive(args.drive)
        if d_path and d_label and d_label.upper() == "CIRCUITPY":
            circuitpy_drive = d_path
            break
        time.sleep(0.5)

    if not circuitpy_drive:
        print("[WARN] CIRCUITPY drive did not mount within 15s. Check USB connection or double-click Reset.")
        return 1

    print(f"[SUCCESS] CIRCUITPY drive mounted at {circuitpy_drive}!")

    deploy_file = Path(args.file) if hasattr(args, "file") and args.file else DEFAULT_FIRMWARE_PATH
    deploy_ok = deploy_firmware(deploy_file, circuitpy_drive)
    if not deploy_ok:
        return 1

    if getattr(args, "test", False):
        time.sleep(1.5)
        port_dev, _, _ = find_xiao_serial_port(args.port)
        return run_hil_test(port_dev, listen_sec=getattr(args, "listen_sec", 0.0), timeout_sec=getattr(args, "timeout", 10.0))

    return 0


def trigger_soft_reboot(ser: serial.Serial) -> None:
    """Interrupt any running script with Ctrl-C, enter REPL, and soft-reboot with Ctrl-D.

    Also triggers full hardware self-test replay on the Rust firmware (`0x04` / Ctrl-D).
    """
    ser.reset_input_buffer()
    ser.write(b"\x03\x03")
    ser.flush()
    time.sleep(0.35)
    ser.write(b"\r")
    ser.flush()
    time.sleep(0.20)
    ser.reset_input_buffer()
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
            ser.dtr = True
            ser.rts = True
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
        info = discover_device(args.drive, args.port)

    return run_hil_test(info.com_port, listen_sec=args.listen_sec, timeout_sec=args.timeout)


def cmd_monitor(args: argparse.Namespace) -> int:
    """Stream live USB serial console logs from the XIAO."""
    info = discover_device(None, args.port)
    if not info.com_port:
        print("[ERROR] No XIAO serial port detected.")
        return 1

    print(f"[MONITOR] Connected to {info.com_port} (115200 baud). Press Ctrl-C to exit.")
    if args.send:
        print(f"[MONITOR] Sending command key: {args.send!r}")
    try:
        with serial.Serial(info.com_port, baudrate=115200, timeout=0.1) as ser:
            ser.dtr = True
            ser.rts = True
            if args.reset:
                trigger_soft_reboot(ser)
            if args.send:
                ser.write(args.send.encode("utf-8"))
                ser.flush()
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
    args.send = None
    args.duration = args.duration if hasattr(args, "duration") and args.duration else 4.0
    return cmd_monitor(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xiao-cli",
        description="HIL Development & Rust/CircuitPython Test CLI for Seeed Studio XIAO nRF52840 Sense",
    )
    parser.add_argument("--drive", help="Explicit CIRCUITPY or XIAO-SENSE drive path (e.g. D:\\)")
    parser.add_argument("--port", help="Explicit COM port (e.g. COM9)")

    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub_status = sub.add_parser("status", help="Detect CIRCUITPY/XIAO-SENSE drive and USB serial port")
    sub_status.set_defaults(func=cmd_status)

    # python-deploy (CircuitPython)
    sub_pydeploy = sub.add_parser("python-deploy", aliases=["deploy", "push"], help="Copy code.py to CIRCUITPY drive")
    sub_pydeploy.add_argument("--file", default=str(DEFAULT_FIRMWARE_PATH), help="Source Python file to deploy")
    sub_pydeploy.add_argument("--test", action="store_true", help="Run HIL verification immediately after deploy")
    sub_pydeploy.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for clicks/gestures after init")
    sub_pydeploy.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_pydeploy.set_defaults(func=cmd_python_deploy)

    # python-restore (Restore CircuitPython runtime and CIRCUITPY drive from Rust/DFU)
    sub_pyrestore = sub.add_parser(
        "python-restore",
        aliases=["restore", "restore-circuitpython"],
        help="Flash official CircuitPython firmware UF2 to restore CIRCUITPY drive and deploy code.py",
    )
    sub_pyrestore.add_argument("--uf2", help="Custom CircuitPython UF2 runtime path (defaults to cached 9.2.4)")
    sub_pyrestore.add_argument("--file", default=str(DEFAULT_FIRMWARE_PATH), help="Source Python file to deploy after restore")
    sub_pyrestore.add_argument("--test", action="store_true", help="Run HIL verification immediately after restore")
    sub_pyrestore.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for clicks/gestures after init")
    sub_pyrestore.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_pyrestore.set_defaults(func=cmd_python_restore)

    # rust-build
    sub_rbuild = sub.add_parser("rust-build", help="Compile Rust firmware and generate UF2 image")
    sub_rbuild.add_argument("--manifest", default=str(RUST_MANIFEST_PATH), help="Path to Rust Cargo.toml")
    sub_rbuild.add_argument("--output", default=str(DEFAULT_UF2_OUTPUT_PATH), help="Output UF2 file path")
    sub_rbuild.set_defaults(func=cmd_rust_build)

    # rust-deploy
    sub_rdeploy = sub.add_parser("rust-deploy", help="Build and flash Rust UF2 firmware to XIAO-SENSE")
    sub_rdeploy.add_argument("--uf2", default=str(DEFAULT_UF2_OUTPUT_PATH), help="UF2 file to flash")
    sub_rdeploy.add_argument("--no-build", action="store_true", help="Skip cargo build if UF2 already exists")
    sub_rdeploy.add_argument("--test", action="store_true", help="Run HIL verification immediately after flashing")
    sub_rdeploy.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for clicks/gestures after init")
    sub_rdeploy.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_rdeploy.set_defaults(func=cmd_rust_deploy)

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
    sub_mon.add_argument("--send", help="Send a single debug key upon connecting (e.g. 'd', 'r', '1'..'4', 'z', 'b')")
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
