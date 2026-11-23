"""Short, serialized GATT connections through Home Assistant Bluetooth."""

import asyncio
from contextlib import asynccontextmanager
import logging

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.exceptions import HomeAssistantError
from recsrmesh.ble import CHARACTERISTIC_HIGH, CHARACTERISTIC_LOW, SERVICE_UUID
from recsrmesh.mcp_crypto import decrypt_packet, make_packet, random_seq

from .protocol import (
    FEF1, device_name, device_status, level_command, network_key, power_command,
)

_LOGGER = logging.getLogger(__name__)
FRAGMENT_DELAY = 0.025
WRITE_SETTLE_TIME = 0.25


class MeshError(HomeAssistantError):
    """A BLE operation failed or the requested response was not verified."""


class Link:
    def __init__(self, client):
        service = client.services.get_service(FEF1) or client.services.get_service(SERVICE_UUID)
        if service is None:
            raise MeshError("Missing CSRmesh GATT service (FEF1 / legacy CSR UUID)")
        self.client = client
        self.low = service.get_characteristic(CHARACTERISTIC_LOW)
        self.high = service.get_characteristic(CHARACTERISTIC_HIGH)
        if self.low is None or self.high is None:
            raise MeshError("Missing CSRmesh GATT characteristic 8003 or 8004")

    async def write(self, packet):
        # SG ends each frame on 8004, including frames of exactly 20 bytes.
        parts = [(self.high, packet)]
        if len(packet) > 20:
            parts = [(self.low, packet[:20]), (self.high, packet[20:])]
        for index, (char, chunk) in enumerate(parts):
            if index:
                # Give the receiver time to process 8003 before writing 8004.
                await asyncio.sleep(FRAGMENT_DELAY)
            if not {"write", "write-without-response"}.intersection(char.properties):
                raise MeshError(f"GATT characteristic {char.uuid} is not writable")
            try:
                await self.client.write_gatt_char(char, chunk, response="write" in char.properties)
            except (BleakError, OSError, EOFError) as err:
                raise MeshError(f"GATT write {char.uuid}: {err or type(err).__name__}") from err

    async def request(self, packet, key, match):
        frames = asyncio.Queue()
        first = b""

        def low_notify(_, data):
            nonlocal first
            first = bytes(data)

        def high_notify(_, data):
            nonlocal first
            frames.put_nowait(first + bytes(data))
            first = b""

        await self.client.start_notify(self.low, low_notify)
        await self.client.start_notify(self.high, high_notify)
        await self.write(packet)
        # Disconnecting at the end of the operation releases both subscriptions.
        async with asyncio.timeout(8):
            while True:
                decoded = decrypt_packet(key, await frames.get())
                if decoded is not None:
                    result = match(decoded["source"], decoded["decpayload"])
                    if result is not None:
                        return result


class Lamp:
    def __init__(self, hass, settings):
        self.hass = hass
        self.name = settings["name"]
        self.address = settings["address"]
        self.group = settings["group"]
        self.power_node = settings.get("power_node")
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
        try:
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if device is None:
                raise MeshError("No connectable advertisement in Home Assistant Bluetooth")
            async with asyncio.timeout(25):
                client = await establish_connection(BleakClient, device, self.name, max_attempts=2)
                try:
                    yield Link(client)
                finally:
                    await client.disconnect()
        except (BleakError, OSError, EOFError, TimeoutError, MeshError) as err:
            reason = str(err) or type(err).__name__
            _LOGGER.warning("%s [%s] %s failed: %s", self.name, self.address, action, reason)
            raise MeshError(f"{self.name} [{self.address}] {action}: {reason}") from err

    async def power(self, on):
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
