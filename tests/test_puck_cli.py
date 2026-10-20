"""Unit tests for simplified Puck.js Agent CLI."""

import json
from types import SimpleNamespace
import pytest

from tools.puck_cli.ble_client import ScannedDevice
from tools.puck_cli.cli import run_cli


def test_cli_scan_json(monkeypatch, capsys):
    async def fake_scan(timeout=4.0, espruino_only=False):
        return [
            ScannedDevice(
                name="Puck.js d3ad",
                address="F5:5A:BF:65:D3:AD",
                rssi=-59,
                is_espruino=True,
            )
        ]

    monkeypatch.setattr("tools.puck_cli.cli.scan_devices", fake_scan)
    exit_code = run_cli(["scan", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["devices"][0]["name"] == "Puck.js d3ad"


def test_cli_exec_json(monkeypatch, capsys):
    async def fake_resolve(target, scan_timeout=4.0):
        return ScannedDevice(name="Puck.js d3ad", address="F5:5A:BF:65:D3:AD", rssi=-59, is_espruino=True)

    class FakePuckClient:
        def __init__(self, address, **kwargs):
            self.address = address

        async def connect(self, timeout=None):
            pass

        async def disconnect(self):
            pass

        async def execute(self, js_code, timeout=3.0):
            return "=24.5"

    monkeypatch.setattr("tools.puck_cli.cli.resolve_device_address", fake_resolve)
    monkeypatch.setattr("tools.puck_cli.cli.PuckBLEClient", FakePuckClient)

    exit_code = run_cli(["exec", "E.getTemperature()", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["output"] == "=24.5"


def test_cli_diag_json(monkeypatch, capsys):
    async def fake_resolve(target, scan_timeout=4.0):
        return ScannedDevice(name="Puck.js d3ad", address="F5:5A:BF:65:D3:AD", rssi=-59, is_espruino=True)

    class FakePuckClient:
        def __init__(self, address, **kwargs):
            self.address = address

        async def connect(self, timeout=None):
            pass

        async def disconnect(self):
            pass

        async def diagnose(self, timeout=3.0):
            return {"battery": 95, "temperature": 24.5, "version": "2v18", "memory": {"free": 1800, "total": 2500}}

    monkeypatch.setattr("tools.puck_cli.cli.resolve_device_address", fake_resolve)
    monkeypatch.setattr("tools.puck_cli.cli.PuckBLEClient", FakePuckClient)

    exit_code = run_cli(["diag", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["diagnostics"]["battery"] == 95
