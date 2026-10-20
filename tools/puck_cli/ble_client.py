"""Puck.js / Espruino BLE client using native Windows WinRT GATT."""

from __future__ import annotations

import sys

# Force Multi-Threaded Apartment (MTA) mode for WinRT COM before any Bleak imports
if not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 0

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from bleak import BleakClient, BleakScanner

NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

ESPRUINO_PREFIXES = ("puck.js", "espruino", "bangle.js", "pixl.js", "jolt.js", "mdbt42")
STATE_FILE_PATH = Path.cwd() / ".puck_device.local.json"


def enable_windows_vt() -> None:
    """Enable virtual terminal processing in Windows console to properly render standard ANSI formatting."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_out = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
                kernel32.SetConsoleMode(h_out, mode.value | 0x0004 | 0x0008)
        except Exception:
            pass


enable_windows_vt()


@dataclass
class ScannedDevice:
    name: str
    address: str
    rssi: int
    is_espruino: bool
    service_uuids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_espruino_device(name: str | None, service_uuids: Iterable[str] | None) -> bool:
    norm = (name or "").strip().lower()
    if any(norm.startswith(p) or p in norm for p in ESPRUINO_PREFIXES):
        return True
    uuids = [u.lower() for u in (service_uuids or [])]
    return NUS_SERVICE_UUID in uuids


def chunk_payload(data: bytes, chunk_size: int = 20) -> Iterable[bytes]:
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def clean_espruino_output(raw: str, sent_command: str = "") -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    lines = [line.strip() for line in text.split("\n")]
    cleaned: list[str] = []
    cmd = sent_command.strip()
    removed_echo = False

    for line in lines:
        if not line:
            continue
        if not removed_echo and cmd and (line == cmd or line == f">{cmd}"):
            removed_echo = True
            continue
        if line == ">":
            continue
        if line.startswith(">") and not line.startswith(">>"):
            line = line[1:].strip()
            if not line:
                continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


async def scan_devices(timeout: float = 4.0, espruino_only: bool = False) -> list[ScannedDevice]:
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results: list[ScannedDevice] = []

    for address, (ble_dev, adv_data) in discovered.items():
        name = getattr(adv_data, "local_name", None) or getattr(ble_dev, "name", None) or "Unknown"
        rssi = int(getattr(adv_data, "rssi", -100) or -100)
        uuids = list(getattr(adv_data, "service_uuids", []) or [])
        esp = is_espruino_device(name, uuids)

        if espruino_only and not esp:
            continue

        results.append(
            ScannedDevice(
                name=name,
                address=getattr(ble_dev, "address", address),
                rssi=rssi,
                is_espruino=esp,
                service_uuids=uuids,
            )
        )

    results.sort(key=lambda d: (not d.is_espruino, -d.rssi, d.name))
    return results


async def resolve_device_address(target: str | None, scan_timeout: float = 4.0) -> ScannedDevice:
    if not target:
        saved = load_saved_device()
        if saved:
            return saved
        devices = await scan_devices(timeout=scan_timeout, espruino_only=True)
        if not devices:
            raise RuntimeError("No Puck.js / Espruino devices found. Ensure device is awake and nearby.")
        return devices[0]

    # Check for direct MAC address pattern
    if re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", target.strip()):
        return ScannedDevice(
            name=target.strip(),
            address=target.strip().upper().replace("-", ":"),
            rssi=0,
            is_espruino=True,
        )

    # Scan and match partial name or MAC
    devices = await scan_devices(timeout=scan_timeout, espruino_only=False)
    q = target.strip().lower()
    for dev in devices:
        if q in dev.name.lower() or q in dev.address.lower():
            return dev

    raise RuntimeError(f"Could not find BLE device matching '{target}'.")


def save_selected_device(device: ScannedDevice, path: Path = STATE_FILE_PATH) -> None:
    path.write_text(json.dumps(device.to_dict(), indent=2), encoding="utf-8")


def load_saved_device(path: Path = STATE_FILE_PATH) -> ScannedDevice | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ScannedDevice(
            name=data.get("name", "Puck.js"),
            address=data["address"],
            rssi=int(data.get("rssi", 0)),
            is_espruino=bool(data.get("is_espruino", True)),
            service_uuids=list(data.get("service_uuids", [])),
        )
    except Exception:
        return None


class PuckBLEClient:
    """Async BLE Nordic UART client for Puck.js devices."""

    def __init__(
        self,
        address: str,
        name: str = "Puck.js",
        on_rx: Callable[[str], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        client_factory: Callable[..., Any] = BleakClient,
    ) -> None:
        self.address = address
        self.name = name
        self.on_rx = on_rx
        self.on_disconnect = on_disconnect
        self._client_factory = client_factory
        self._client: Any | None = None
        self._rx_buffer: list[str] = []
        self._rx_event = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    def _handle_disconnect(self, _client: Any) -> None:
        if self.on_disconnect:
            self.on_disconnect()

    def _handle_rx(self, _sender: Any, data: bytearray) -> None:
        text = bytes(data).decode("utf-8", errors="replace")
        self._rx_buffer.append(text)
        self._rx_event.set()
        if self.on_rx:
            self.on_rx(text)

    async def connect(self, timeout: float = 10.0) -> None:
        """Connect to device with an automatic retry on Windows WinRT COM glitches."""
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                self._client = self._client_factory(
                    self.address,
                    disconnected_callback=self._handle_disconnect,
                )
                await self._client.connect(timeout=timeout)
                await self._client.start_notify(NUS_RX_CHAR_UUID, self._handle_rx)
                return
            except Exception as exc:
                last_err = exc
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                if attempt == 0:
                    await asyncio.sleep(0.5)

        raise RuntimeError(f"Failed to connect to {self.name} ({self.address}): {last_err}")

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(NUS_RX_CHAR_UUID)
            except Exception:
                pass
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def send(self, code: str, append_newline: bool = True, chunk_delay: float = 0.02) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected to Puck.js.")

        payload = code
        if append_newline and not payload.endswith("\n"):
            payload += "\n"
        b_data = payload.encode("utf-8")

        for chunk in chunk_payload(b_data, chunk_size=20):
            await self._client.write_gatt_char(NUS_TX_CHAR_UUID, chunk, response=False)
            if chunk_delay > 0:
                await asyncio.sleep(chunk_delay)

    async def execute(self, js_code: str, timeout: float = 3.0, settle_delay: float = 0.2) -> str:
        self._rx_buffer.clear()
        self._rx_event.clear()

        await self.send(js_code, append_newline=True)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._rx_event.wait(), timeout=min(settle_delay, remaining))
                self._rx_event.clear()
                joined = "".join(self._rx_buffer)
                if joined.rstrip().endswith(">"):
                    await asyncio.sleep(min(0.05, settle_delay))
                    break
            except asyncio.TimeoutError:
                if self._rx_buffer:
                    break

        return clean_espruino_output("".join(self._rx_buffer), sent_command=js_code)

    async def reset(self) -> None:
        await self.send("reset();\n")
        await asyncio.sleep(0.3)

    async def upload(self, script: str, reset_first: bool = True, save_after: bool = False) -> str:
        if reset_first:
            await self.reset()
        result = await self.execute(script)
        if save_after:
            await self.send("save();\n")
        return result

    async def diagnose(self, timeout: float = 3.0) -> dict[str, Any]:
        """Fetch battery, temperature, firmware version, and memory from device."""
        cmd = (
            "JSON.stringify({"
            "bat: (typeof E.getBattery==='function')?E.getBattery():null,"
            "temp: (typeof E.getTemperature==='function')?E.getTemperature():null,"
            "ver: process.env.VERSION,"
            "mem: process.memory()"
            "})"
        )
        raw = await self.execute(cmd, timeout=timeout)
        clean_json = raw.strip()
        if clean_json.startswith("="):
            clean_json = clean_json[1:].strip()
        try:
            return json.loads(clean_json)
        except Exception:
            return {"raw_output": raw}
