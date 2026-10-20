"""Command-Line Interface for Puck.js / Espruino BLE control."""

from __future__ import annotations

import sys

# Force Multi-Threaded Apartment (MTA) mode for WinRT COM before any Bleak imports
if not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 0

import argparse
import asyncio
import json
from pathlib import Path
from typing import Sequence

from tools.puck_cli.ble_client import (
    PuckBLEClient,
    enable_windows_vt,
    load_saved_device,
    resolve_device_address,
    save_selected_device,
    scan_devices,
)
from tools.puck_cli.tui import PuckConsole, print_devices_table

enable_windows_vt()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="puck",
        description="Windows BLE CLI for interacting, deploying, and debugging Puck.js devices.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # tui / console
    p_tui = subparsers.add_parser("tui", help="Launch simple interactive terminal console")
    p_tui.add_argument("-d", "--device", help="Device name, address, or substring to connect initially")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan for nearby BLE Puck.js devices")
    p_scan.add_argument("--all", action="store_true", help="Include non-Puck BLE devices")
    p_scan.add_argument("-t", "--timeout", type=float, default=3.5, help="Scan timeout in seconds")
    p_scan.add_argument("--json", action="store_true", help="Output JSON for AI agents")

    # use / select
    p_use = subparsers.add_parser("use", help="Select and remember default Puck.js device")
    p_use.add_argument("device", help="Device name, address, or substring")

    # exec
    p_exec = subparsers.add_parser("exec", help="Execute JavaScript code on the device")
    p_exec.add_argument("code", help="JavaScript expression or statements to execute")
    p_exec.add_argument("-d", "--device", help="Target device (defaults to saved/first Puck.js)")
    p_exec.add_argument("-t", "--timeout", type=float, default=3.0, help="Response timeout in seconds")
    p_exec.add_argument("--json", action="store_true", help="Output JSON for AI agents")

    # deploy / upload
    p_deploy = subparsers.add_parser("deploy", help="Deploy a .js script file to Puck.js")
    p_deploy.add_argument("file", help="Path to local .js file")
    p_deploy.add_argument("-d", "--device", help="Target device")
    p_deploy.add_argument("--no-reset", action="store_true", help="Do not send reset() before uploading")
    p_deploy.add_argument("--save", action="store_true", help="Send save() after uploading to write to flash")
    p_deploy.add_argument("--json", action="store_true", help="Output JSON for AI agents")

    # diag / info
    p_diag = subparsers.add_parser("diag", help="Query battery, temperature, version, and memory diagnostics")
    p_diag.add_argument("-d", "--device", help="Target device")
    p_diag.add_argument("--json", action="store_true", help="Output JSON for AI agents")

    # reset
    p_reset = subparsers.add_parser("reset", help="Send reset() to Puck.js to clear RAM state")
    p_reset.add_argument("-d", "--device", help="Target device")

    return parser


async def _cmd_scan(args: argparse.Namespace) -> int:
    devices = await scan_devices(timeout=args.timeout, espruino_only=not args.all)
    if args.json:
        print(json.dumps({"count": len(devices), "devices": [d.to_dict() for d in devices]}, indent=2))
        return 0

    print_devices_table(devices)
    return 0


async def _cmd_use(args: argparse.Namespace) -> int:
    try:
        target = await resolve_device_address(args.device)
        save_selected_device(target)
        print(f"Default device set: {target.name} ({target.address})")
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


async def _cmd_exec(args: argparse.Namespace) -> int:
    try:
        target = await resolve_device_address(args.device)
        client = PuckBLEClient(target.address, name=target.name)
        await client.connect()
        try:
            output = await client.execute(args.code, timeout=args.timeout)
        finally:
            await client.disconnect()

        if args.json:
            print(json.dumps({"ok": True, "device": target.to_dict(), "output": output}, indent=2))
        else:
            if output:
                print(output)
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Execution error: {exc}")
        return 1


async def _cmd_deploy(args: argparse.Namespace) -> int:
    p = Path(args.file)
    if not p.exists():
        msg = f"File not found: {p}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}, indent=2))
        else:
            print(msg)
        return 1

    code = p.read_text(encoding="utf-8")
    try:
        target = await resolve_device_address(args.device)
        client = PuckBLEClient(target.address, name=target.name)
        await client.connect()
        try:
            output = await client.upload(
                code,
                reset_first=not args.no_reset,
                save_after=args.save,
            )
        finally:
            await client.disconnect()

        if args.json:
            print(json.dumps({"ok": True, "device": target.to_dict(), "file": str(p), "output": output}, indent=2))
        else:
            print(f"Deployed {p.name} to {target.name} ({target.address}) successfully.")
            if output:
                print(output)
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Deploy error: {exc}")
        return 1


async def _cmd_diag(args: argparse.Namespace) -> int:
    try:
        target = await resolve_device_address(args.device)
        client = PuckBLEClient(target.address, name=target.name)
        await client.connect()
        try:
            diag = await client.diagnose()
        finally:
            await client.disconnect()

        if args.json:
            print(json.dumps({"ok": True, "device": target.to_dict(), "diagnostics": diag}, indent=2))
        else:
            print(f"Diagnostics for {target.name} ({target.address}):")
            for k, v in diag.items():
                print(f"  {k}: {v}")
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"Diagnostics error: {exc}")
        return 1


async def _cmd_reset(args: argparse.Namespace) -> int:
    try:
        target = await resolve_device_address(args.device)
        client = PuckBLEClient(target.address, name=target.name)
        await client.connect()
        try:
            await client.reset()
        finally:
            await client.disconnect()
        print(f"Puck.js {target.name} reset.")
        return 0
    except Exception as exc:
        print(f"Reset error: {exc}")
        return 1


def run_cli(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None or args.command == "tui":
        dev = getattr(args, "device", None)
        console = PuckConsole(initial_device=dev)
        return asyncio.run(console.run())

    if args.command == "scan":
        return asyncio.run(_cmd_scan(args))

    if args.command == "use":
        return asyncio.run(_cmd_use(args))

    if args.command == "exec":
        return asyncio.run(_cmd_exec(args))

    if args.command == "deploy":
        return asyncio.run(_cmd_deploy(args))

    if args.command == "diag":
        return asyncio.run(_cmd_diag(args))

    if args.command == "reset":
        return asyncio.run(_cmd_reset(args))

    parser.print_help()
    return 0


def main() -> None:
    sys.exit(run_cli())
