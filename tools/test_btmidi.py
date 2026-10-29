"""Bluetooth Low Energy MIDI (BLE-MIDI) Sample Test Launcher & Local Config Server.

Builds and deploys the standalone `btmidi-test` Rust binary to the Seeed Studio XIAO nRF52840 Sense,
verifies live BLE-MIDI peripheral advertising & fixed-beat generation over USB Serial, and serves the
local HTML Configuration & Monitoring Dashboard (`tools/btmidi_config.html`) on `http://127.0.0.1:8765`.

Usage:
    # Build, flash, verify, and open the local HTML config & monitor dashboard:
    uv run python tools/test_btmidi.py

    # Build, flash, and run automated HIL verification (non-blocking):
    uv run python tools/test_btmidi.py --verify-only

    # Serve the local HTML dashboard against an already-flashed XIAO:
    uv run python tools/test_btmidi.py --no-deploy

    # Restore the main ai-metronome-rust firmware when finished:
    uv run python tools/test_btmidi.py --restore
"""

from __future__ import annotations

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import webbrowser

import serial

try:
    from tools.xiao_cli import (
        REPO_ROOT,
        RUST_MANIFEST_PATH,
        cmd_rust_deploy,
        copy_uf2_blocks_flushed,
        discover_device,
        elf_to_uf2,
        find_xiao_drive,
        find_xiao_serial_port,
        trigger_bootloader,
    )
except ImportError:
    from xiao_cli import (  # type: ignore
        REPO_ROOT,
        RUST_MANIFEST_PATH,
        cmd_rust_deploy,
        copy_uf2_blocks_flushed,
        discover_device,
        elf_to_uf2,
        find_xiao_drive,
        find_xiao_serial_port,
        trigger_bootloader,
    )

BTMIDI_ELF_PATH = (
    REPO_ROOT
    / "src"
    / "xiao_nrf52840_sense"
    / "rust"
    / "target"
    / "thumbv7em-none-eabihf"
    / "release"
    / "btmidi-test"
)
BTMIDI_UF2_PATH = REPO_ROOT / "build" / "btmidi-test.uf2"
HTML_DASHBOARD_PATH = Path(__file__).resolve().parent / "btmidi_config.html"


class SerialBridge:
    """Thread-safe USB Serial bridge between the XIAO nRF52840 and the local HTML dashboard."""

    def __init__(self, port: str) -> None:
        self.port = port
        self.lock = threading.Lock()
        self.last_status_line: str = ""
        self.events: deque[str] = deque(maxlen=50)
        self.cmd_queue: deque[str] = deque()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def send_command(self, cmd: str) -> None:
        with self.lock:
            self.cmd_queue.append(cmd.strip())

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            evts = list(self.events)
            self.events.clear()
            return {
                "port": self.port,
                "last_line": self.last_status_line,
                "events": evts,
            }

    def _worker(self) -> None:
        while self.running:
            try:
                with serial.Serial(self.port, baudrate=115200, timeout=0.1) as ser:
                    ser.dtr = True
                    ser.rts = True
                    while self.running:
                        with self.lock:
                            while self.cmd_queue:
                                cmd = self.cmd_queue.popleft()
                                ser.write(f"{cmd}\n".encode("utf-8"))
                                ser.flush()
                        raw = ser.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue
                            with self.lock:
                                if line.startswith("[BTMIDI]"):
                                    self.last_status_line = line
                                else:
                                    self.events.append(line)
                                    print(f"  {line}")
            except serial.SerialException:
                time.sleep(0.5)


def build_and_deploy_btmidi(explicit_drive: str | None, explicit_port: str | None) -> str | None:
    """Compile `btmidi-test`, pack UF2, flash to XIAO-SENSE, and return active COM port."""
    print("=" * 65)
    print("  BUILDING & DEPLOYING BLE-MIDI SAMPLE TEST APP (btmidi-test)")
    print("=" * 65)

    cmd = [
        "cargo",
        "build",
        "--manifest-path",
        str(RUST_MANIFEST_PATH),
        "--release",
        "--target",
        "thumbv7em-none-eabihf",
        "--bin",
        "btmidi-test",
    ]
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0 or not BTMIDI_ELF_PATH.exists():
        print("[ERROR] Cargo build of btmidi-test failed.")
        return None

    num_blocks, base_addr, payload_bytes = elf_to_uf2(BTMIDI_ELF_PATH, BTMIDI_UF2_PATH)
    print(f"[UF2] Packed {payload_bytes} bytes @ 0x{base_addr:08X} -> {num_blocks} UF2 blocks ({BTMIDI_UF2_PATH})")

    info = discover_device(explicit_drive, explicit_port)
    drive_path = info.drive_path

    if not drive_path and info.com_port:
        trigger_bootloader(info.com_port)
        for _ in range(30):
            time.sleep(0.25)
            drive_path, _, _ = find_xiao_drive(explicit_drive)
            if drive_path:
                break

    if not drive_path:
        print("[ERROR] XIAO-SENSE UF2 drive not found. Double-tap Reset button and retry.")
        return None

    dest_uf2 = drive_path / "CURRENT.UF2"
    print(f"[FLASH] Writing {BTMIDI_UF2_PATH.name} -> {dest_uf2} ...")
    copy_uf2_blocks_flushed(BTMIDI_UF2_PATH, dest_uf2)

    print("[WAIT]  Waiting for XIAO BLE-MIDI Test firmware to enumerate USB Serial...")
    for _ in range(32):
        time.sleep(0.25)
        port, desc, vid_pid = find_xiao_serial_port(explicit_port)
        if port:
            print(f"[READY] XIAO BLE-MIDI Test enumerated on {port} ({desc}) [{vid_pid}]")
            return port

    print("[ERROR] Serial port did not enumerate after flashing.")
    return None


def verify_btmidi_serial(com_port: str) -> bool:
    """Verify live `[BTMIDI]` telemetry and interactive preset/BPM commands on hardware."""
    print(f"\n[VERIFY] Connecting to {com_port} to verify BLE-MIDI advertising & command control...")
    saw_ready_or_status = False
    saw_pianoteq_preset = False
    saw_widi_preset = False

    try:
        with serial.Serial(com_port, baudrate=115200, timeout=0.25) as ser:
            ser.dtr = True
            ser.rts = True
            time.sleep(0.2)
            ser.write(b"STATUS\n")
            ser.flush()

            start = time.monotonic()
            step = 0
            while time.monotonic() - start < 5.0:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                print(f"  {line}")

                if line.startswith("[BTMIDI]"):
                    saw_ready_or_status = True
                    if step == 0:
                        step = 1
                        ser.write(b"PRESET PIANOTEQ\n")
                        ser.write(b"SET BPM=132.5\n")
                        ser.flush()
                    elif step == 1 and "CH_MIDI=1" in line and "ACCENT=84:115" in line and "BPM=132.5" in line:
                        saw_pianoteq_preset = True
                        step = 2
                        ser.write(b"PRESET WIDI\n")
                        ser.write(b"SET BPM=120.0\n")
                        ser.flush()
                    elif step == 2 and "CH_MIDI=10" in line and "ACCENT=76:120" in line and "BPM=120.0" in line:
                        saw_widi_preset = True
                        break
    except Exception as exc:
        print(f"[ERROR] Verification failed on {com_port}: {exc}")
        return False

    ok = saw_ready_or_status and saw_pianoteq_preset and saw_widi_preset
    print("=" * 65)
    if ok:
        print("  [PASS] BLE-MIDI Peripheral Advertising + Preset/BPM Config Verified!")
    else:
        print("  [FAIL] Did not receive expected BLE-MIDI status confirmation.")
    print("=" * 65)
    return ok


def serve_dashboard(com_port: str, http_port: int) -> int:
    """Start the local HTTP configuration & monitoring server and open browser."""
    bridge = SerialBridge(com_port)
    html_bytes = HTML_DASHBOARD_PATH.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html", "/btmidi_config.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bytes)
            elif self.path.startswith("/api/status"):
                payload = json.dumps(bridge.snapshot()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path == "/api/cmd":
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                cmd = str(body.get("cmd", "")).strip()
                if cmd:
                    bridge.send_command(cmd)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            else:
                self.send_response(404)
                self.end_headers()

    url = f"http://127.0.0.1:{http_port}"
    print(f"\n[DASHBOARD] Local HTML Config & Monitor running at: {url}")
    print(f"[FILE]      Or open directly in Chrome/Edge: {HTML_DASHBOARD_PATH}")
    print("            Press Ctrl-C to stop server.\n")
    webbrowser.open(url)

    server = HTTPServer(("127.0.0.1", http_port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[DASHBOARD] Shutting down.")
    finally:
        bridge.running = False
        server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy and test XIAO nRF52840 BLE-MIDI Sample App")
    parser.add_argument("--drive", help="Explicit UF2 drive path")
    parser.add_argument("--port", help="Explicit COM port")
    parser.add_argument("--http-port", type=int, default=8765, help="Local HTTP port (default: 8765)")
    parser.add_argument("--no-deploy", action="store_true", help="Skip flashing; connect to running board")
    parser.add_argument("--verify-only", action="store_true", help="Flash, verify over serial, and exit")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore main ai-metronome-rust firmware and run 7-point HIL test",
    )
    args = parser.parse_args()

    if args.restore:
        ns = argparse.Namespace(
            drive=args.drive,
            port=args.port,
            manifest=str(RUST_MANIFEST_PATH),
            output=None,
            smoke_test=False,
            dfu=False,
            test=True,
        )
        return cmd_rust_deploy(ns)

    com_port = args.port
    if not args.no_deploy:
        com_port = build_and_deploy_btmidi(args.drive, args.port)
        if not com_port:
            return 1
    else:
        info = discover_device(args.drive, args.port)
        com_port = info.com_port
        if not com_port:
            print("[ERROR] Could not detect XIAO serial port.")
            return 1

    if not verify_btmidi_serial(com_port):
        return 1

    if args.verify_only:
        return 0

    return serve_dashboard(com_port, args.http_port)


if __name__ == "__main__":
    sys.exit(main())
