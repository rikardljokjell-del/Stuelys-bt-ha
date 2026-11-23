"""Short, serialized GATT connections through Home Assistant Bluetooth."""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import logging
import sys

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.importlib import async_import_module
from recsrmesh.ble import CHARACTERISTIC_HIGH, CHARACTERISTIC_LOW, SERVICE_UUID
from recsrmesh.mcp_crypto import decrypt_packet, make_packet, random_seq

from .protocol import (
    APP, FEF1, device_name, device_status, dim_command, level_command, network_key,
    power_command,
)

_LOGGER = logging.getLogger(__name__)
FRAGMENT_DELAY = 0.025
WRITE_SETTLE_TIME = 0.25
REPLY_TIMEOUT = 8
# In the switch captures, the same frame appears with TTL 0x32 and 0x31.
ADVERTISEMENT_TTL = b"\x32"
DIM_ADVERTISEMENT_INTERVAL = 100
DIM_HOLD_SECONDS = 1.5


class MeshError(HomeAssistantError):
    """A BLE operation failed or the requested response was not verified."""


class Link:
    def __init__(self, client, *, without_response=False):
        service = client.services.get_service(FEF1) or client.services.get_service(SERVICE_UUID)
        if service is None:
            raise MeshError("Missing CSRmesh GATT service (FEF1 / legacy CSR UUID)")
        self.client = client
        self.without_response = without_response
        self.low = service.get_characteristic(CHARACTERISTIC_LOW)
        self.high = service.get_characteristic(CHARACTERISTIC_HIGH)
        if self.low is None or self.high is None:
            raise MeshError("Missing CSRmesh GATT characteristic 8003 or 8004")

    async def write(self, packet):
        # SG ends each frame on 8004, including frames of exactly 20 bytes.
        parts = [(self.high, packet)]
        if len(packet) > 20:
            parts = [(self.low, packet[:20]), (self.high, packet[20:])]
        if self.without_response:
            # Check both fragments before sending anything.
            for char, _ in parts:
                if "write-without-response" not in char.properties:
                    raise MeshError(
                        f"GATT characteristic {char.uuid} does not support writing without response"
                    )
        for index, (char, chunk) in enumerate(parts):
            if index:
                # Give the receiver time to process 8003 before writing 8004.
                await asyncio.sleep(FRAGMENT_DELAY)
            if not {"write", "write-without-response"}.intersection(char.properties):
                raise MeshError(f"GATT characteristic {char.uuid} is not writable")
            response = not self.without_response and "write" in char.properties
            _LOGGER.debug("GATT write %s, %d bytes, response=%s", char.uuid, len(chunk), response)
            try:
                await self.client.write_gatt_char(char, chunk, response=response)
            except (BleakError, OSError, EOFError) as err:
                raise MeshError(f"GATT write {char.uuid}: {err or type(err).__name__}") from err

    async def request(self, packet, key, match):
        frames = asyncio.Queue()
        first = b""
        low_count = high_count = echoes = 0
        mesh_frames = Counter()

        def low_notify(_, data):
            nonlocal first, low_count
            low_count += 1
            first = bytes(data)

        def high_notify(_, data):
            nonlocal first, high_count
            high_count += 1
            frames.put_nowait(first + bytes(data))
            first = b""

        for char, handler in ((self.low, low_notify), (self.high, high_notify)):
            try:
                await self.client.start_notify(char, handler)
            except (BleakError, OSError, EOFError) as err:
                raise MeshError(f"GATT subscribe {char.uuid}: {err or type(err).__name__}") from err
        await self.write(packet)
        # Disconnecting at the end of the operation releases both subscriptions.
        try:
            async with asyncio.timeout(REPLY_TIMEOUT):
                while True:
                    decoded = decrypt_packet(key, await frames.get())
                    if decoded is None:
                        continue
                    source, data = decoded["source"], decoded["decpayload"]
                    if source == APP:
                        echoes += 1
                        continue
                    opcode = data[2:4].hex().upper()
                    mesh_frames[source, opcode] += 1
                    _LOGGER.debug("Authenticated mesh frame from %04X, opcode %s", source, opcode)
                    result = match(source, data)
                    if result is not None:
                        return result
        except TimeoutError as err:
            received = ", ".join(
                f"{source:04X}/{opcode} ×{count}"
                for (source, opcode), count in mesh_frames.most_common(6)
            )
            raise MeshError(
                f"No matching reply after {REPLY_TIMEOUT} s. "
                f"Notifications 8003={low_count}, 8004={high_count}, "
                f"authenticated mesh frames={mesh_frames.total()}, local echoes={echoes}."
                + (f" Source/opcode: {received}." if received else "")
            ) from err


class Lamp:
    def __init__(self, hass, settings):
        self.hass = hass
        self.name = settings["name"]
        self.address = settings["address"]
        self.group = settings["group"]
        self.power_node = settings.get("power_node")
        self.transport = settings.get("transport")
        self.without_response = (
            self.transport == "gatt_without_response" or settings.get("without_response", False)
        )
        self.location = bytes.fromhex(settings["location"])
        self.key = network_key(settings["password"])
        self.seq = random_seq()
        self.tid = self.seq & 0xFFFF
        self.lock = asyncio.Lock()

    def packet(self, destination, data):
        self.seq = (self.seq + 1) & 0xFFFFFF
        return make_packet(self.key, self.seq, destination.to_bytes(2, "little") + data)

    def next_tid(self):
        self.tid = self.tid % 65535 + 1
        return self.tid

    @asynccontextmanager
    async def connection(self, action):
        stage = "Bluetooth lookup"
        try:
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if device is None:
                raise MeshError("No connectable advertisement in Home Assistant Bluetooth")
            async with asyncio.timeout(25):
                stage = "GATT connect"
                client = await establish_connection(BleakClient, device, self.name, max_attempts=2)
                try:
                    stage = "GATT exchange"
                    yield Link(client, without_response=self.without_response)
                finally:
                    await client.disconnect()
        except (BleakError, OSError, EOFError, TimeoutError, MeshError) as err:
            reason = str(err) or type(err).__name__
            _LOGGER.warning("%s [%s] %s failed (%s): %s", self.name, self.address, action, stage, reason)
            raise MeshError(f"{self.name} [{self.address}] {action} ({stage}): {reason}") from err

    async def power(self, on):
        if self.transport == "advertisement":
            async with self.lock:
                data = power_command(self.location, on, self.next_tid())
                await self._advertise(data, f"FF03 {'ON' if on else 'OFF'}")
            return
        target = self.power_node if self.power_node is not None else self.group
        target_type = "node" if self.power_node is not None else "group"
        action = f"FF03 {'ON' if on else 'OFF'} to {target_type} {target:04X}"
        async with self.lock, self.connection(action) as link:
            tid = self.next_tid()
            if self.power_node is None:
                data = power_command(self.location, on, tid)
            else:
                data = level_command(self.location, on, 0, tid)
            await link.write(self.packet(target, data))
            _LOGGER.debug("%s [%s] %s written to GATT", self.name, self.address, action)
            await asyncio.sleep(WRITE_SETTLE_TIME)

    async def advertised_level(self, percent):
        if not 1 <= percent <= 100:
            raise ValueError("Expected a brightness between 1 and 100 percent")
        async with self.lock:
            data = power_command(self.location, True, self.next_tid(), percent=percent)
            await self._advertise(data, f"FF03 brightness {percent}%")

    async def dim_step(self, up):
        """Send a short hold and release, using the switch's FF23 format."""
        async with self.lock:
            held = False
            try:
                await self._advertise(
                    dim_command(self.location, 1 if up else 2),
                    "FF23 dim up" if up else "FF23 dim down",
                    duration=DIM_HOLD_SECONDS,
                    interval_ms=DIM_ADVERTISEMENT_INTERVAL,
                )
                held = True
            finally:
                # A failed or cancelled start may still have reached the dimmer.
                try:
                    await self._advertise(dim_command(self.location, 3), "FF23 stop")
                except MeshError:
                    if held:
                        raise

    async def _advertise(self, data, command, *, duration=3, interval_ms=None):
        action = f"FEF1 {command} advertisement to group {self.group:04X}"
        try:
            if sys.platform != "linux":
                raise HomeAssistantError("BLE advertising requires a local Linux Bluetooth adapter")
            advertiser = await async_import_module(self.hass, f"{__package__}.advertise")
            info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            packet = self.packet(self.group, data)
            adapter = await advertiser.broadcast(
                packet[:-1] + ADVERTISEMENT_TTL,
                info.source if info else None,
                duration=duration,
                interval_ms=interval_ms,
            )
        except (HomeAssistantError, ImportError) as err:
            _LOGGER.warning("%s [%s] %s failed: %s", self.name, self.address, action, err)
            raise MeshError(f"{self.name} [{self.address}] {action}: {err}") from err
        _LOGGER.debug("%s [%s] %s registered on %s", self.name, self.address, action, adapter)

    async def identify(self):
        """Resolve the receiver's mesh source from its authenticated name reply."""
        async with self.lock, self.connection("FF10 name request / FF11 reply") as link:
            return await link.request(
                self.packet(0, b"\xff\x10" + self.location), self.key,
                lambda source, data: device_name(source, data, self.location, self.name),
            )

    async def _read(self, link, node):
        return await link.request(
            self.packet(node, b"\xff\x04" + self.location), self.key,
            lambda source, data: device_status(source, data, node, self.location),
        )

    async def status(self, node):
        async with self.lock, self.connection("FF04 status request / FF05 reply") as link:
            return await self._read(link, node)

    async def set_level(self, node, percent):
        async with self.lock:
            async with self.connection("FF03 brightness write") as link:
                data = level_command(self.location, True, percent, self.next_tid())
                await link.write(self.packet(node, data))
                await asyncio.sleep(WRITE_SETTLE_TIME)
            # Read on a fresh link after the dimmer has had time to change.
            await asyncio.sleep(1)
            async with self.connection("FF05 brightness read-back") as link:
                return await self._read(link, node)
