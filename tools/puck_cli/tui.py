"""Simplified, clean interactive terminal console for Puck.js / Espruino devices."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from tools.puck_cli.ble_client import (
    PuckBLEClient,
    ScannedDevice,
    load_saved_device,
    resolve_device_address,
    save_selected_device,
    scan_devices,
)


def print_devices_table(devices: list[ScannedDevice]) -> None:
    if not devices:
        print("  (No devices found)")
        return
    print("\n  #  Device Name          Address             Signal     Type")
    print("  -- ------------------- ------------------- ---------- ----------------------")
    for idx, d in enumerate(devices, start=1):
        d_type = "Puck.js (NUS)" if d.is_espruino else "Other BLE"
        print(f"  {idx:<2} {d.name:<19} {d.address:<19} {d.rssi:>4} dBm   {d_type}")
    print()


def print_help() -> None:
    print("""
Available Commands:
  scan [all]            Scan for nearby Puck.js (or all BLE) devices
  connect <name|mac|#>  Connect to a device by name, address, or scan index
  disconnect            Disconnect from active device
  status                Show active connection status
  reset                 Send reset() to Puck.js RAM
  diag                  Show battery, temperature, firmware version, and memory
  upload <file.js>      Upload a .js script file to Puck.js
  help, ?               Show this help message
  quit, q, exit         Exit the console

Any other input is sent directly as JavaScript to the connected Puck.js.
Examples:
  LED1.set()
  LED1.reset()
  E.getTemperature()
  Puck.mag()
""")


class PuckConsole:
    """Simplistic, bulletproof interactive console for Puck.js devices."""

    def __init__(self, initial_device: str | None = None) -> None:
        self.initial_device = initial_device
        self.client: PuckBLEClient | None = None
        self.active_device: ScannedDevice | None = None
        self.last_scanned: list[ScannedDevice] = []

    def _on_rx(self, text: str) -> None:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
        if cleaned.strip() and cleaned.strip() != ">":
            print(cleaned, end="", flush=True)

    def _on_disconnect(self) -> None:
        print("\n[Puck.js] Disconnected.", flush=True)

    async def connect_device(self, target: ScannedDevice) -> bool:
        if self.client and self.client.is_connected:
            await self.client.disconnect()

        print(f"Connecting to {target.name} ({target.address})...", end="", flush=True)
        self.client = PuckBLEClient(
            address=target.address,
            name=target.name,
            on_rx=self._on_rx,
            on_disconnect=self._on_disconnect,
        )
        try:
            await self.client.connect(timeout=8.0)
            self.active_device = target
            save_selected_device(target)
            print(" Connected!")
            return True
        except Exception as exc:
            print(f" Failed: {exc}")
            self.client = None
            self.active_device = None
            return False

    async def do_scan(self, espruino_only: bool = True) -> list[ScannedDevice]:
        mode = "Puck.js" if espruino_only else "all BLE"
        print(f"Scanning for {mode} devices...", end="", flush=True)
        try:
            self.last_scanned = await scan_devices(timeout=3.5, espruino_only=espruino_only)
            print(f" Found {len(self.last_scanned)} device(s).")
            print_devices_table(self.last_scanned)
        except Exception as exc:
            print(f" Scan error: {exc}")
            self.last_scanned = []
        return self.last_scanned

    async def handle_command(self, line: str) -> bool:
        """Process a line of user input. Returns False if user wants to quit."""
        stripped = line.strip()
        if not stripped:
            return True

        # Strip optional leading colon so :q and q work identically
        cmd_line = stripped[1:].strip() if stripped.startswith(":") else stripped
        parts = cmd_line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Uniform exit
        if cmd in ("q", "quit", "exit"):
            return False

        if cmd in ("help", "?"):
            print_help()
            return True

        if cmd == "scan":
            await self.do_scan(espruino_only=(arg.lower() != "all"))
            return True

        if cmd == "status":
            if self.client and self.client.is_connected and self.active_device:
                print(f"Connected: {self.active_device.name} ({self.active_device.address})")
            else:
                saved = load_saved_device()
                saved_str = f" (Saved default: {saved.name} {saved.address})" if saved else ""
                print(f"Disconnected.{saved_str}")
            return True

        if cmd == "connect":
            if not arg:
                # If numbers from scan exist
                if self.last_scanned:
                    print("Specify device number or name. Example: connect 1")
                    return True
                saved = load_saved_device()
                if saved:
                    await self.connect_device(saved)
                else:
                    devs = await self.do_scan(espruino_only=True)
                    if devs:
                        await self.connect_device(devs[0])
                return True

            # Check if arg is an index from last scan
            if arg.isdigit() and self.last_scanned:
                idx = int(arg) - 1
                if 0 <= idx < len(self.last_scanned):
                    await self.connect_device(self.last_scanned[idx])
                    return True
                print(f"Index out of range (1-{len(self.last_scanned)}).")
                return True

            try:
                target = await resolve_device_address(arg)
                await self.connect_device(target)
            except Exception as exc:
                print(f"Error: {exc}")
            return True

        if cmd == "disconnect":
            if self.client and self.client.is_connected:
                await self.client.disconnect()
                print("Disconnected.")
            else:
                print("Already disconnected.")
            return True

        if cmd == "reset":
            if self.client and self.client.is_connected:
                await self.client.reset()
                print("Puck.js reset.")
            else:
                print("Not connected.")
            return True

        if cmd in ("diag", "info"):
            if not self.client or not self.client.is_connected:
                print("Not connected. Connect to a device first.")
                return True
            print("Reading device diagnostics...", flush=True)
            info = await self.client.diagnose()
            print("Device Diagnostics:")
            for k, v in info.items():
                print(f"  {k}: {v}")
            return True

        if cmd == "upload":
            if not arg:
                print("Usage: upload <path/to/script.js>")
                return True
            p = Path(arg)
            if not p.exists():
                print(f"File not found: {p}")
                return True
            if not self.client or not self.client.is_connected:
                print("Not connected to a Puck.js.")
                return True
            print(f"Uploading {p.name} ({p.stat().st_size} bytes)...")
            res = await self.client.upload(p.read_text(encoding="utf-8"))
            if res:
                print(res)
            print("Upload complete.")
            return True

        # Not an internal operational command — send directly as JavaScript to Puck
        if self.client and self.client.is_connected:
            res = await self.client.execute(stripped)
            if res:
                print(res)
            return True

        print(f"Not connected. Type 'scan' or 'connect' to connect to Puck.js, or 'help' for commands.")
        return True

    async def run(self) -> int:
        print("=== Puck.js BLE Console ===")
        print("Type 'help' for commands, 'q' or 'quit' to exit.\n")

        # Initial auto-connect if device specified or saved
        if self.initial_device:
            try:
                target = await resolve_device_address(self.initial_device)
                await self.connect_device(target)
            except Exception as exc:
                print(f"Notice: {exc}")
        else:
            saved = load_saved_device()
            if saved:
                print(f"Saved device: {saved.name} ({saved.address})")
                print("Press Enter to connect, 's' to scan, or 'q' to quit.")
                ans = (await asyncio.to_thread(input, "Choice [Enter/s/q] > ")).strip().lower()
                if ans in ("q", "quit", "exit"):
                    return 0
                if ans in ("s", "scan"):
                    devs = await self.do_scan(espruino_only=True)
                    if devs:
                        print("Enter # to connect (or 'q' to skip): ", end="", flush=True)
                        c = (await asyncio.to_thread(input, "")).strip().lower()
                        if c.isdigit() and 1 <= int(c) <= len(devs):
                            await self.connect_device(devs[int(c) - 1])
                else:
                    await self.connect_device(saved)
            else:
                devs = await self.do_scan(espruino_only=True)
                if devs:
                    print("Enter # to connect (or 'q' to skip): ", end="", flush=True)
                    c = (await asyncio.to_thread(input, "")).strip().lower()
                    if c.isdigit() and 1 <= int(c) <= len(devs):
                        await self.connect_device(devs[int(c) - 1])

        # Main interactive loop
        while True:
            if self.client and self.client.is_connected and self.active_device:
                prompt_str = f"{self.active_device.name} > "
            else:
                prompt_str = "puck(offline) > "

            try:
                line = await asyncio.to_thread(input, prompt_str)
            except (EOFError, KeyboardInterrupt):
                print()
                break

            keep_going = await self.handle_command(line)
            if not keep_going:
                break

        if self.client and self.client.is_connected:
            await self.client.disconnect()
        print("Goodbye.")
        return 0
