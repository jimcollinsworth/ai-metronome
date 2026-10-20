"""Unit tests for simplified Puck.js BLE client and utilities."""

from types import SimpleNamespace
import pytest

from tools.puck_cli.ble_client import (
    NUS_SERVICE_UUID,
    NUS_TX_CHAR_UUID,
    PuckBLEClient,
    chunk_payload,
    clean_espruino_output,
    is_espruino_device,
    scan_devices,
)


def test_is_espruino_device_detection():
    assert is_espruino_device("Puck.js d3ad", []) is True
    assert is_espruino_device("Espruino-ESP32", []) is True
    assert is_espruino_device("Unknown", [NUS_SERVICE_UUID]) is True
    assert is_espruino_device("Headphones", ["0000180f-0000-1000-8000-00805f9b34fb"]) is False


def test_chunk_payload():
    data = b"LED1.set();\n"
    chunks = list(chunk_payload(data, chunk_size=20))
    assert len(chunks) == 1
    assert chunks[0] == data


def test_clean_espruino_output():
    raw = "E.getBattery()\r\n=95\r\n>"
    assert clean_espruino_output(raw, sent_command="E.getBattery()") == "=95"


@pytest.mark.asyncio
async def test_scan_devices_prioritizes_puck(monkeypatch):
    fake_map = {
        "11:22:33:44:55:66": (
            SimpleNamespace(name="Other Device", address="11:22:33:44:55:66"),
            SimpleNamespace(local_name="Other Device", rssi=-30, service_uuids=[]),
        ),
        "F5:5A:BF:65:D3:AD": (
            SimpleNamespace(name="Puck.js d3ad", address="F5:5A:BF:65:D3:AD"),
            SimpleNamespace(local_name="Puck.js d3ad", rssi=-59, service_uuids=[NUS_SERVICE_UUID]),
        ),
    }

    async def fake_discover(**kwargs):
        return fake_map

    monkeypatch.setattr("tools.puck_cli.ble_client.BleakScanner.discover", fake_discover)

    devs = await scan_devices(timeout=1.0)
    assert len(devs) == 2
    assert devs[0].name == "Puck.js d3ad"
    assert devs[0].is_espruino is True


@pytest.mark.asyncio
async def test_puck_client_execute_and_diag():
    written = []
    rx_holder = {}

    class FakeClient:
        def __init__(self, address, disconnected_callback=None):
            self.address = address
            self.is_connected = False

        async def connect(self, timeout=None):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def start_notify(self, char_uuid, callback):
            rx_holder["cb"] = callback

        async def stop_notify(self, char_uuid):
            rx_holder.pop("cb", None)

        async def write_gatt_char(self, char_uuid, data, response=False):
            written.append(bytes(data))
            if b"JSON.stringify" in data and "cb" in rx_holder:
                rx_holder["cb"](None, bytearray(b'={"bat":95,"temp":24.5,"ver":"2v18"}\r\n>'))
            elif b"LED1.set" in data and "cb" in rx_holder:
                rx_holder["cb"](None, bytearray(b"=true\r\n>"))

    client = PuckBLEClient("F5:5A:BF:65:D3:AD", client_factory=FakeClient)
    await client.connect()
    assert client.is_connected is True

    res = await client.execute("LED1.set()", timeout=0.5, settle_delay=0.05)
    assert res == "=true"

    diag = await client.diagnose(timeout=0.5)
    assert diag.get("bat") == 95
    assert diag.get("ver") == "2v18"

    await client.disconnect()
    assert client.is_connected is False
