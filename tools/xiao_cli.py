"""Rust Firmware Build, Flash, Monitor & HIL CLI for Seeed Studio XIAO nRF52840 Sense.

Provides deterministic Rust-first commands (`build`, `deploy`, `test`, `monitor`, `reset`, `status`)
and pure-Python ELF32-to-UF2 packaging (`0xADA52840` @ `0x00027000`).

(CircuitPython prototype recovery is isolated in `tools/restore_circuitpython.py`.)
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
SMOKE_TEST_ELF_PATH = (
    REPO_ROOT
    / "src"
    / "xiao_nrf52840_sense"
    / "rust"
    / "target"
    / "thumbv7em-none-eabihf"
    / "release"
    / "deploy-test"
)
DEFAULT_UF2_OUTPUT_PATH = REPO_ROOT / "build" / "ai-metronome-rust.uf2"
SMOKE_TEST_UF2_OUTPUT_PATH = REPO_ROOT / "build" / "deploy-test.uf2"

# UF2 Constants for Nordic nRF52840 (Adafruit UF2 Bootloader)
UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000
NRF52840_UF2_FAMILY_ID = 0xADA52840

# Known USB Vendor IDs for Seeed Studio (0x2886) and Adafruit (0x239A)
XIAO_VIDS = {0x2886, 0x239A}


@dataclass
class XiaoDeviceInfo:
    """Discovered XIAO nRF52840 Sense USB drive & CDC serial port endpoints."""

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


def find_xiao_drive(explicit_drive: str | None = None) -> tuple[Path | None, str | None, str | None]:
    """Locate the mounted XIAO-SENSE bootloader drive (or CIRCUITPY drive if present)."""
    if explicit_drive:
        path = Path(explicit_drive)
        if path.exists():
            label = _get_volume_label(str(path.resolve().anchor)) or "SPECIFIED"
            info_file = path / "INFO_UF2.TXT" if (path / "INFO_UF2.TXT").exists() else (path / "boot_out.txt")
            boot_txt = info_file.read_text(encoding="utf-8", errors="replace").strip() if info_file.exists() else None
            return path, label, boot_txt
        return None, None, None

    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        path = Path(root)
        if not path.exists():
            continue
        label = _get_volume_label(root)
        if label and label.upper() in ("XIAO-SENSE", "CIRCUITPY"):
            info_file = path / "INFO_UF2.TXT" if (path / "INFO_UF2.TXT").exists() else (path / "boot_out.txt")
            boot_txt = info_file.read_text(encoding="utf-8", errors="replace").strip() if info_file.exists() else None
            return path, label, boot_txt
        if (path / "INFO_UF2.TXT").exists():
            boot_txt = (path / "INFO_UF2.TXT").read_text(encoding="utf-8", errors="replace").strip()
            if "XIAO" in boot_txt or "nRF52840" in boot_txt or "UF2 Bootloader" in boot_txt:
                return path, label or "XIAO-SENSE", boot_txt

    return None, None, None


# Alias kept for backward compatibility with tests/utilities
find_circuitpy_drive = find_xiao_drive


def find_xiao_serial_port(explicit_port: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Locate the XIAO nRF52840 Sense USB CDC Serial port."""
    ports = list(list_ports.comports())

    if explicit_port:
        for p in ports:
            if p.device.upper() == explicit_port.upper():
                vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid and p.pid else None
                return p.device, p.description, vid_pid
        return explicit_port, "Manual Port", None

    for p in ports:
        if p.vid in XIAO_VIDS:
            vid_pid = f"{p.vid:04X}:{p.pid:04X}"
            return p.device, p.description, vid_pid

    for p in ports:
        desc_upper = (p.description or "").upper()
        hwid_upper = (p.hwid or "").upper()
        if "ACTIVE MANAGEMENT TECHNOLOGY" in desc_upper or "VEN_8086" in hwid_upper:
            continue
        if "USB" in hwid_upper or "SERIAL" in desc_upper:
            vid_pid = f"{p.vid:04X}:{p.pid:04X}" if p.vid and p.pid else p.hwid
            return p.device, p.description, vid_pid

    return None, None, None


def discover_device(drive: str | None = None, port: str | None = None) -> XiaoDeviceInfo:
    """Discover both USB storage drive and USB CDC serial port for XIAO."""
    drive_path, label, boot_out = find_xiao_drive(drive)
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
        if p_type == 1 and p_filesz > 0 and 0x00001000 <= p_paddr < 0x000ED000:
            seg_bytes = data[p_offset : p_offset + p_filesz]
            segments.append((p_paddr, seg_bytes))

    # If the application is linked at 0x00027000, ignore any stray LLD header segment below 0x00027000
    if any(addr >= 0x00027000 for addr, _ in segments):
        segments = [(addr, seg) for addr, seg in segments if addr >= 0x00027000]

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


def elf_to_ihex(elf_path: Path, hex_path: Path) -> tuple[int, int]:
    """Convert a 32-bit ARM ELF file (`PT_LOAD` flash segments) into an Intel HEX (`.hex`) file.

    Used by `adafruit-nrfutil dfu genpkg` to build official Nordic S140 DFU `.zip` packages.
    Returns `(base_address, total_payload_bytes)`.
    """
    data = elf_path.read_bytes()
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise ValueError(f"Not a valid ELF binary: {elf_path}")

    e_phoff = struct.unpack_from("<I", data, 0x1C)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x2A)[0]
    e_phnum = struct.unpack_from("<H", data, 0x2C)[0]

    segments: list[tuple[int, bytes]] = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, _p_vaddr, p_paddr, p_filesz, _p_memsz, _p_flags, _p_align = struct.unpack_from(
            "<IIIIIIII", data, off
        )
        if p_type == 1 and p_filesz > 0 and 0x00001000 <= p_paddr < 0x000ED000:
            seg_bytes = data[p_offset : p_offset + p_filesz]
            segments.append((p_paddr, seg_bytes))

    if any(addr >= 0x00027000 for addr, _ in segments):
        segments = [(addr, seg) for addr, seg in segments if addr >= 0x00027000]

    if not segments:
        raise ValueError(f"No loadable flash PT_LOAD segments found in {elf_path}")

    segments.sort(key=lambda s: s[0])
    min_addr = segments[0][0]
    max_addr = max(addr + len(seg) for addr, seg in segments)
    total_len = max_addr - min_addr

    def _ihex_line(rec_type: int, addr16: int, payload: bytes) -> str:
        raw = bytes([len(payload), (addr16 >> 8) & 0xFF, addr16 & 0xFF, rec_type]) + payload
        csum = (-sum(raw)) & 0xFF
        return ":" + raw.hex().upper() + f"{csum:02X}\n"

    lines: list[str] = []
    curr_ext_addr: int | None = None
    for seg_addr, seg_bytes in segments:
        for offset in range(0, len(seg_bytes), 16):
            chunk = seg_bytes[offset : offset + 16]
            abs_addr = seg_addr + offset
            ext_addr = (abs_addr >> 16) & 0xFFFF
            if ext_addr != curr_ext_addr:
                curr_ext_addr = ext_addr
                lines.append(_ihex_line(0x04, 0x0000, struct.pack(">H", ext_addr)))
            lines.append(_ihex_line(0x00, abs_addr & 0xFFFF, chunk))

    lines.append(":00000001FF\n")
    hex_path.parent.mkdir(parents=True, exist_ok=True)
    hex_path.write_text("".join(lines), encoding="ascii")
    return min_addr, total_len


def build_dfu_package(hex_path: Path, zip_path: Path) -> bool:
    """Invoke official `adafruit-nrfutil dfu genpkg` (`--dev-type 0x0052 --sd-req 0x0123`) if available."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    cmd = [
        "uv",
        "run",
        "--with",
        "adafruit-nrfutil",
        "adafruit-nrfutil",
        "dfu",
        "genpkg",
        "--dev-type",
        "0x0052",
        "--sd-req",
        "0x0123",
        "--application",
        str(hex_path),
        str(zip_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return res.returncode == 0 and zip_path.exists()


def copy_uf2_blocks_flushed(uf2_path: Path, dest_uf2: Path) -> None:
    """Write UF2 image in 512-byte blocks and flush to the USB MSC bootloader drive."""
    import os

    data = uf2_path.read_bytes()
    try:
        with open(dest_uf2, "wb", buffering=0) as f:
            for offset in range(0, len(data), 512):
                f.write(data[offset : offset + 512])
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        # UF2 bootloader immediately disconnects & jumps to app when the last block is written
        pass


def cmd_status(args: argparse.Namespace) -> int:
    """Display discovered XIAO nRF52840 Sense bootloader drive and serial port status."""
    info = discover_device(args.drive, args.port)
    print("=" * 60)
    print("  XIAO nRF52840 SENSE -- DEVICE STATUS (RUST WORKFLOW)")
    print("=" * 60)

    if info.drive_path:
        print(f"  [DRIVE]   Mounted at : {info.drive_path} (Label: {info.volume_label})")
        if info.boot_out:
            for line in info.boot_out.splitlines():
                print(f"  [INFO]    {line}")
    else:
        print("  [DRIVE]   No UF2 drive mounted (Normal when running Rust firmware)")

    if info.com_port:
        print(f"  [SERIAL]  Port       : {info.com_port} ({info.port_description}) [{info.usb_vid_pid}]")
    else:
        print("  [SERIAL]  NOT FOUND (Double-tap Reset on XIAO to enter UF2 bootloader)")

    print("=" * 60)
    return 0 if (info.drive_path or info.com_port) else 1


def cmd_rust_build(args: argparse.Namespace) -> int:
    """Compile the Rust firmware (`thumbv7em-none-eabihf`) and pack a UF2 image."""
    smoke_test = getattr(args, "smoke_test", False)
    manifest = Path(getattr(args, "manifest", RUST_MANIFEST_PATH)).resolve()
    default_out = SMOKE_TEST_UF2_OUTPUT_PATH if smoke_test else DEFAULT_UF2_OUTPUT_PATH
    uf2_out = Path(getattr(args, "output", None) or default_out).resolve()
    bin_name = "deploy-test" if smoke_test else "ai-metronome-rust"
    elf_path = SMOKE_TEST_ELF_PATH if smoke_test else RUST_ELF_PATH

    print("=" * 60)
    print(f"  BUILDING RUST FIRMWARE: {bin_name} (thumbv7em-none-eabihf)")
    print("=" * 60)
    cmd = [
        "cargo",
        "build",
        "--manifest-path",
        str(manifest),
        "--release",
        "--target",
        "thumbv7em-none-eabihf",
        "--bin",
        bin_name,
    ]
    print(f"[BUILD] Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        print("[ERROR] Cargo build failed.")
        return res.returncode

    if not elf_path.exists():
        print(f"[ERROR] Expected ELF binary not found at {elf_path}")
        return 1

    num_blocks, base_addr, payload_bytes = elf_to_uf2(elf_path, uf2_out)
    hex_out = uf2_out.with_suffix(".hex")
    zip_out = uf2_out.with_suffix(".zip")
    elf_to_ihex(elf_path, hex_out)
    dfu_ok = build_dfu_package(hex_out, zip_out)
    print(f"[UF2]   Packed {payload_bytes} bytes @ 0x{base_addr:08X} -> {num_blocks} UF2 blocks")
    print(f"[UF2]   Output file: {uf2_out} ({uf2_out.stat().st_size} bytes)")
    if dfu_ok:
        print(f"[DFU]   Official Nordic S140 DFU package: {zip_out} ({zip_out.stat().st_size} bytes)")
    print("=" * 60)
    return 0


def trigger_bootloader(com_port: str) -> None:
    """Request XIAO-SENSE UF2 bootloader via Rust serial 'b' command or 1200-baud touch."""
    print(f"[BOOTLOADER] Requesting XIAO-SENSE UF2 bootloader on {com_port}...")
    try:
        with serial.Serial(com_port, baudrate=115200, timeout=0.2) as s:
            s.dtr = True
            s.rts = True
            s.write(b"b")
            s.flush()
            time.sleep(0.15)
    except serial.SerialException:
        pass

    try:
        s = serial.Serial(com_port, baudrate=1200, timeout=0.2)
        s.dtr = False
        s.rts = False
        time.sleep(0.15)
        s.close()
    except serial.SerialException:
        pass


def verify_smoke_test_serial(com_port: str, timeout_sec: float = 5.0) -> int:
    """Verify the minimal `deploy-test` binary responds over USB CDC serial."""
    print(f"[SMOKE_TEST] Opening {com_port} to verify deploy-test response...")
    try:
        with serial.Serial(com_port, baudrate=115200, timeout=0.2) as s:
            s.dtr = True
            s.rts = True
            time.sleep(0.15)
            s.write(b"r")
            s.flush()
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                raw = s.readline()
                if raw:
                    line = raw.decode("utf-8", errors="replace").strip()
                    print(f"  [DEVICE] {line}")
                    if "[DEPLOY_TEST]" in line:
                        print("[SMOKE_TEST] PASS: Minimal Rust deploy-test enumerated and responded over USB CDC!")
                        return 0
    except serial.SerialException as err:
        print(f"[SMOKE_TEST] FAIL: Serial error on {com_port}: {err}")
        return 1
    print(f"[SMOKE_TEST] FAIL: Did not receive [DEPLOY_TEST] banner within {timeout_sec:.1f}s.")
    return 1


def cmd_rust_deploy(args: argparse.Namespace) -> int:
    """Build (optional) and flash the Rust `.uf2` image to the XIAO-SENSE bootloader drive."""
    smoke_test = getattr(args, "smoke_test", False)
    default_uf2 = SMOKE_TEST_UF2_OUTPUT_PATH if smoke_test else DEFAULT_UF2_OUTPUT_PATH
    uf2_arg = getattr(args, "uf2", None)
    uf2_path = Path(uf2_arg if uf2_arg else default_uf2).resolve()

    if not getattr(args, "no_build", False) or not uf2_path.exists():
        build_ns = argparse.Namespace(
            manifest=str(RUST_MANIFEST_PATH),
            output=str(uf2_path),
            smoke_test=smoke_test,
        )
        rc = cmd_rust_build(build_ns)
        if rc != 0:
            return rc

    info = discover_device(args.drive, args.port)
    bootloader_drive: Path | None = None

    if info.drive_path and info.volume_label and info.volume_label.upper() == "XIAO-SENSE":
        bootloader_drive = info.drive_path
    else:
        if info.com_port:
            trigger_bootloader(info.com_port)
        else:
            print("[BOOTLOADER] Double-click the Reset button on the XIAO to mount XIAO-SENSE...")

        print("[BOOTLOADER] Waiting up to 15s for XIAO-SENSE UF2 drive to mount...")
        deadline = time.monotonic() + 15.0
        prompted = False
        while time.monotonic() < deadline:
            d_path, d_label, d_boot = find_xiao_drive(args.drive)
            if d_path and d_label and d_label.upper() == "XIAO-SENSE":
                bootloader_drive = d_path
                info.boot_out = d_boot
                break
            if not prompted and (deadline - time.monotonic()) < 9.0:
                print("  [TIP] Double-click the physical Reset button on the XIAO if D:\\ hasn't appeared yet...")
                prompted = True
            time.sleep(0.4)

    if not bootloader_drive:
        print("[ERROR] XIAO-SENSE UF2 bootloader drive not found. Double-click Reset and re-run.")
        return 1

    print(f"[BOOTLOADER] Mounted at {bootloader_drive}")
    if info.boot_out:
        for line in info.boot_out.splitlines():
            print(f"  [INFO_UF2] {line}")

    dfu_zip = uf2_path.with_suffix(".zip")
    dfu_flashed = False
    if getattr(args, "dfu", False) and dfu_zip.exists():
        bl_port, _bdesc, _bvp = find_xiao_serial_port(args.port)
        if bl_port:
            print(f"[DFU]   Flashing {dfu_zip.name} over bootloader serial {bl_port} via adafruit-nrfutil...")
            dfu_cmd = [
                "uv",
                "run",
                "--with",
                "adafruit-nrfutil",
                "adafruit-nrfutil",
                "dfu",
                "serial",
                "-pkg",
                str(dfu_zip),
                "-p",
                bl_port,
                "-b",
                "115200",
                "--singlebank",
            ]
            res = subprocess.run(dfu_cmd, check=False)
            dfu_flashed = res.returncode == 0

    if not dfu_flashed:
        dest_uf2 = bootloader_drive / uf2_path.name
        print(f"[FLASH] Writing {uf2_path.name} ({uf2_path.stat().st_size} bytes) in 512-byte UF2 blocks -> {dest_uf2} ...")
        copy_uf2_blocks_flushed(uf2_path, dest_uf2)

    print("[FLASH] UF2 transfer complete! Waiting for Rust USB CDC serial port to enumerate...")
    re_port: str | None = None
    re_deadline = time.monotonic() + 10.0
    time.sleep(1.0)
    while time.monotonic() < re_deadline:
        port_dev, _desc, _vp = find_xiao_serial_port(args.port)
        if port_dev:
            re_port = port_dev
            break
        time.sleep(0.35)

    if re_port:
        print(f"[SERIAL] Rust firmware enumerated on {re_port}!")
        if smoke_test:
            return verify_smoke_test_serial(re_port, timeout_sec=getattr(args, "timeout", 5.0))
        if getattr(args, "test", False):
            return run_hil_test(re_port, listen_sec=getattr(args, "listen_sec", 0.0), timeout_sec=getattr(args, "timeout", 10.0))
    else:
        print("[WARN] Serial port did not enumerate within 10s (check USB connection).")
        if smoke_test or getattr(args, "test", False):
            return 1

    return 0


def trigger_self_test_replay(ser: serial.Serial) -> None:
    """Send 'r' (or 0x04) to replay the full hardware self-test banner on the Rust firmware."""
    ser.reset_input_buffer()
    ser.write(b"r")
    ser.flush()


def run_hil_test(com_port: str | None, listen_sec: float = 0.0, timeout_sec: float = 10.0) -> int:
    """Run automated Hardware-in-the-Loop (HIL) verification over USB Serial."""
    if not com_port:
        print("[ERROR] No XIAO serial port available for HIL testing.")
        return 1

    print("\n" + "=" * 65)
    print("  HARDWARE-IN-THE-LOOP (HIL) TEST RUNNER (RUST FIRMWARE)")
    print("=" * 65)
    print(f"  Target Serial Port : {com_port}")
    print(f"  Response Timeout   : {timeout_sec:.1f}s")
    print(f"  Live Event Window  : {listen_sec:.1f}s (clicks, gestures & BLE)")
    print("\n  Scheduled Checkpoints:")
    print("    [1/7] POWER_DIAG     : Battery rail, charge status, CPU temp & RAM/Flash")
    print("    [2/7] MIC_POWER      : PDM microphone power gate (P1.10 MIC_PWR)")
    print("    [3/7] MIC_DMA_STREAM : PDM 16kHz EasyDMA stream & signal health")
    print("    [4/7] IMU_BUS        : LSM6DS3TR-C power gate & 400kHz TWIM0 I2C bus")
    print("    [5/7] IMU_ACCEL      : 3-axis accelerometer & gyroscope active")
    print("    [6/7] BLE_ADVERTISER : 2.4GHz BLE 1Mbps BTHome v2 (0xFCD2) tempo broadcaster")
    print("    [7/7] CAL_AND_READY  : Ambient noise calibration & PLL beat clock ready")
    print("=" * 65 + "\n")

    checks: dict[str, dict[str, str | bool]] = {
        "POWER_DIAG": {"passed": False, "detail": "", "name": "Power & Memory Diagnostics"},
        "MIC_POWER": {"passed": False, "detail": "", "name": "Microphone Power Rail (P1.10 MIC_PWR)"},
        "MIC_DMA_STREAM": {"passed": False, "detail": "", "name": "PDM 16kHz EasyDMA Stream & Health"},
        "IMU_BUS": {"passed": False, "detail": "", "name": "LSM6DS3TR-C I2C Bus @ 400kHz"},
        "IMU_ACCEL": {"passed": False, "detail": "", "name": "3-Axis Accelerometer (WHO_AM_I=0x6A)"},
        "BLE_ADVERTISER": {"passed": False, "detail": "", "name": "BLE Advertiser (AI-METRO BTHome 0xFCD2)"},
        "CAL_AND_READY": {"passed": False, "detail": "", "name": "Noise Calibration & PLL Ready"},
    }
    failures: list[str] = []

    try:
        with serial.Serial(com_port, baudrate=115200, timeout=0.1) as ser:
            ser.dtr = True
            ser.rts = True
            print("[STEP 1/2] Requesting hardware self-test replay ('r')...")
            trigger_self_test_replay(ser)

            start_time = time.monotonic()
            ready_time: float | None = None
            replayed_after_partial = False
            power_diag_parts: list[str] = []

            while True:
                now = time.monotonic()
                if ready_time is None and (now - start_time) > timeout_sec:
                    failures.append(f"Timed out after {timeout_sec:.1f}s waiting for [READY] banner.")
                    break
                if ready_time is not None and (now - ready_time) >= listen_sec:
                    break

                raw_line = ser.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue

                print(f"  | [MCU] {line}")

                if "[CRASH_LOG]" in line or "[FAIL]" in line:
                    failures.append(line.strip())

                if "[DIAG]" in line:
                    power_diag_parts.append(line.split("[DIAG]", 1)[1].strip())
                    if "Memory / Storage" in line and not checks["POWER_DIAG"]["passed"]:
                        checks["POWER_DIAG"]["passed"] = True
                        checks["POWER_DIAG"]["detail"] = " ; ".join(power_diag_parts)

                elif "[MIC]  Power Gate" in line and "Active" in line:
                    checks["MIC_POWER"]["passed"] = True
                    checks["MIC_POWER"]["detail"] = line.split(":", 1)[1].strip()

                elif "[MIC]  Signal Health" in line and "OK" in line:
                    checks["MIC_DMA_STREAM"]["passed"] = True
                    checks["MIC_DMA_STREAM"]["detail"] = line.split(":", 1)[1].strip()

                elif "[IMU]  I2C Bus" in line and "Operational" in line:
                    checks["IMU_BUS"]["passed"] = True
                    checks["IMU_BUS"]["detail"] = line.split(":", 1)[1].strip()

                elif "[IMU]  Accelerometer" in line and "Active" in line:
                    checks["IMU_ACCEL"]["passed"] = True
                    checks["IMU_ACCEL"]["detail"] = line.split(":", 1)[1].strip()

                elif "[BLE]  Advertiser" in line and "Active" in line:
                    checks["BLE_ADVERTISER"]["passed"] = True
                    checks["BLE_ADVERTISER"]["detail"] = line.split(":", 1)[1].strip()

                elif "[READY] Initialization OK!" in line:
                    checks["CAL_AND_READY"]["passed"] = True
                    checks["CAL_AND_READY"]["detail"] = "Calibration complete & PLL ready"
                    # If we attached mid-boot and only caught the tail end of the first self-test,
                    # trigger a clean replay ('r') so all 7 checkpoints are captured.
                    if not all(bool(c["passed"]) for c in checks.values()) and not replayed_after_partial:
                        replayed_after_partial = True
                        power_diag_parts.clear()
                        trigger_self_test_replay(ser)
                    else:
                        ready_time = time.monotonic()

    except serial.SerialException as err:
        print(f"[ERROR] Serial communication failure on {com_port}: {err}")
        return 1

    total_elapsed = time.monotonic() - start_time
    all_passed = all(bool(c["passed"]) for c in checks.values()) and not failures

    print("\n" + "=" * 65)
    print(f"  [STEP 2/2] HIL VERIFICATION SUMMARY ({total_elapsed:.2f}s total)")
    print("=" * 65)
    for key, info in checks.items():
        status = "PASS" if info["passed"] else "FAIL"
        detail = f" -- {info['detail']}" if info["detail"] else ""
        print(f"  [{status}] {key:<16}: {info['name']}{detail}")

    if failures:
        print("\n  [FAILURES]:")
        for f in failures:
            print(f"    - {f}")

    print("=" * 65)
    return 0 if all_passed else 1


def cmd_hil_test(args: argparse.Namespace) -> int:
    """Run automated HIL test (optionally building & flashing Rust first with --deploy)."""
    if getattr(args, "deploy", False):
        args.no_build = False
        args.test = True
        return cmd_rust_deploy(args)

    info = discover_device(args.drive, args.port)
    return run_hil_test(info.com_port, listen_sec=args.listen_sec, timeout_sec=args.timeout)


def cmd_monitor(args: argparse.Namespace) -> int:
    """Stream live USB CDC serial output with interactive single-keystroke control."""
    info = discover_device(args.drive, args.port)
    if not info.com_port:
        print("[ERROR] No XIAO serial port detected.")
        return 1

    print("=" * 65)
    print(f"  [MONITOR] XIAO nRF52840 Rust Console ({info.com_port} @ 115200 baud)")
    print("=" * 65)
    print("  Interactive Key Commands:")
    print("    [1]..[4] : Set Mode (1: On-Beat, 2: Upbeat, 3: 4/4, 4: 3/4)")
    print("    [m]      : Cycle to Next Mode")
    print("    [d]/[s]  : Dump DSP, PLL, BLE, IMU & Battery State")
    print("    [r]      : Replay Full Hardware Self-Test")
    print("    [z]      : Test Inactivity Sleep Mode")
    print("    [b]      : Enter XIAO-SENSE UF2 Bootloader")
    print("    [h]      : Show Key Commands Help")
    print("    [Ctrl-C] : Exit Monitor")
    print("=" * 65 + "\n")

    is_windows = sys.platform == "win32"
    if is_windows:
        import msvcrt

    try:
        with serial.Serial(info.com_port, baudrate=115200, timeout=0.05) as ser:
            ser.dtr = True
            ser.rts = True
            if getattr(args, "reset", False):
                trigger_self_test_replay(ser)
            if getattr(args, "send", None):
                ser.write(args.send.encode("utf-8"))
                ser.flush()

            start = time.monotonic()
            while True:
                if args.duration > 0 and (time.monotonic() - start) >= args.duration:
                    break

                if is_windows and msvcrt.kbhit():
                    ch_bytes = msvcrt.getch()
                    if ch_bytes in (b"\x00", b"\xe0"):
                        msvcrt.getch()
                    elif ch_bytes == b"\x03":
                        raise KeyboardInterrupt
                    else:
                        key_char = ch_bytes.decode("utf-8", errors="ignore")
                        if key_char in ("h", "H", "?"):
                            print(
                                "\n[HELP] 1..4=Mode | m=Cycle | d/s=Dump | r=Self-Test | z=Sleep | b=Bootloader | Ctrl-C=Exit\n",
                                flush=True,
                            )
                        elif key_char:
                            ser.write(ch_bytes)
                            ser.flush()
                            print(f"\n[KEY: '{key_char}'] -> Sent to MCU", flush=True)

                try:
                    waiting = ser.in_waiting
                    if waiting > 0:
                        raw = ser.read(waiting)
                        if raw:
                            print(raw.decode("utf-8", errors="replace"), end="", flush=True)
                    else:
                        time.sleep(0.01)
                except (serial.SerialException, OSError):
                    time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n[MONITOR] Closed.")
    except serial.SerialException as err:
        print(f"\n[ERROR] Serial error: {err}")
        return 1
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Replay the full hardware self-test on the Rust firmware and stream output."""
    args.reset = True
    args.send = None
    args.duration = getattr(args, "duration", 4.0) or 4.0
    return cmd_monitor(args)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--drive", help="Explicit XIAO-SENSE bootloader drive path (e.g. D:\\)")
    common.add_argument("--port", help="Explicit COM port (e.g. COM9)")

    parser = argparse.ArgumentParser(
        prog="xiao-cli",
        parents=[common],
        description="Rust Firmware Build, Flash, Monitor & HIL CLI for Seeed Studio XIAO nRF52840 Sense",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub_status = sub.add_parser("status", parents=[common], help="Detect XIAO-SENSE drive and Rust USB serial port")
    sub_status.set_defaults(func=cmd_status)

    # build / rust-build
    sub_rbuild = sub.add_parser("build", parents=[common], aliases=["rust-build"], help="Compile Rust firmware and generate UF2 image")
    sub_rbuild.add_argument("--manifest", default=str(RUST_MANIFEST_PATH), help="Path to Rust Cargo.toml")
    sub_rbuild.add_argument("--output", default=None, help="Output UF2 file path")
    sub_rbuild.add_argument("--smoke-test", action="store_true", help="Build minimal 65-line deploy-test binary instead of full app")
    sub_rbuild.set_defaults(func=cmd_rust_build)

    # deploy / rust-deploy / push
    sub_rdeploy = sub.add_parser("deploy", parents=[common], aliases=["rust-deploy", "push"], help="Build and flash Rust UF2/DFU firmware to XIAO-SENSE")
    sub_rdeploy.add_argument("--uf2", default=None, help="UF2 file to flash")
    sub_rdeploy.add_argument("--dfu", action="store_true", help="Flash via official adafruit-nrfutil serial DFU (.zip) instead of UF2")
    sub_rdeploy.add_argument("--smoke-test", action="store_true", help="Build, flash, and verify minimal deploy-test binary")
    sub_rdeploy.add_argument("--no-build", action="store_true", help="Skip cargo build if UF2 already exists")
    sub_rdeploy.add_argument("--test", action="store_true", help="Run HIL verification immediately after flashing")
    sub_rdeploy.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for clicks/gestures after init")
    sub_rdeploy.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_rdeploy.set_defaults(func=cmd_rust_deploy)

    # test / hil-test
    sub_test = sub.add_parser("test", parents=[common], aliases=["hil-test"], help="Run automated 7-point on-device HIL verification")
    sub_test.add_argument("--deploy", action="store_true", help="Build and flash latest Rust UF2 before testing")
    sub_test.add_argument("--listen-sec", type=float, default=0.0, help="Seconds to listen for live clicks/shakes after init")
    sub_test.add_argument("--timeout", type=float, default=10.0, help="Max seconds to wait for [READY]")
    sub_test.set_defaults(func=cmd_hil_test)

    # monitor / logs
    sub_mon = sub.add_parser("monitor", parents=[common], aliases=["logs"], help="Stream live Rust serial console output")
    sub_mon.add_argument("--reset", action="store_true", help="Trigger hardware self-test upon connecting")
    sub_mon.add_argument("--send", help="Send a single debug key upon connecting (e.g. 'd', 'r', '1'..'4', 'm', 'z', 'b')")
    sub_mon.add_argument("--duration", type=float, default=0.0, help="Auto-exit after N seconds (0 = continuous)")
    sub_mon.set_defaults(func=cmd_monitor)

    # reset
    sub_rst = sub.add_parser("reset", parents=[common], help="Trigger hardware self-test over serial and show startup log")
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
