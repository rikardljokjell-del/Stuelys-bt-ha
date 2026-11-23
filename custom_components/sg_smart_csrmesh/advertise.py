"""Send a short mesh advertisement through the local BlueZ adapter."""

import asyncio

from dbus_fast import BusType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.errors import DBusFastError
from dbus_fast.service import ServiceInterface, dbus_property, method
from homeassistant.exceptions import HomeAssistantError

from .protocol import FEF1

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
MANAGER = "org.bluez.LEAdvertisingManager1"
ADVERT = "org.bluez.LEAdvertisement1"
PATH = "/org/homeassistant/sg_smart_csrmesh"


class MeshAdvertisement(ServiceInterface):
    def __init__(self, packet):
        super().__init__(ADVERT)
        self.packet = packet

    @dbus_property(access=PropertyAccess.READ, name="Type")
    def advertisement_type(self) -> "s":
        return "broadcast"

    @dbus_property(access=PropertyAccess.READ, name="ServiceData")
    def service_data(self) -> "a{sv}":
        return {FEF1: Variant("ay", self.packet)}

    @method(name="Release")
    def release(self):
        """BlueZ has removed the advertisement."""


def _advertising_adapter(objects, preferred_source):
    candidates = []
    for path, interfaces in objects.items():
        adapter = interfaces.get(ADAPTER)
        if adapter is None or MANAGER not in interfaces or not adapter["Powered"].value:
            continue
        if adapter["Address"].value == preferred_source:
            return path
        candidates.append(path)
    if candidates:
        return candidates[0]
    raise HomeAssistantError("No powered local BlueZ adapter supports BLE advertising")


async def broadcast(packet, preferred_source):
    stage = "connect to the local system D-Bus"
    try:
        bus = MessageBus(bus_type=BusType.SYSTEM)
        try:
            async with asyncio.timeout(12):
                await bus.connect()
                stage = "find a local BlueZ advertising adapter"
                root = bus.get_proxy_object(BLUEZ, "/", await bus.introspect(BLUEZ, "/"))
                objects = await root.get_interface(
                    "org.freedesktop.DBus.ObjectManager"
                ).call_get_managed_objects()
                path = _advertising_adapter(objects, preferred_source)
                adapter = bus.get_proxy_object(BLUEZ, path, await bus.introspect(BLUEZ, path))
                manager = adapter.get_interface(MANAGER)
                bus.export(PATH, MeshAdvertisement(packet))
                stage = f"register a BLE advertisement on {path}"
                await manager.call_register_advertisement(PATH, {})
                await asyncio.sleep(3)
                stage = f"unregister the BLE advertisement on {path}"
                await manager.call_unregister_advertisement(PATH)
        finally:
            # BlueZ also removes the advertisement when its D-Bus owner disconnects.
            bus.disconnect()
    except (DBusFastError, OSError, TimeoutError) as err:
        raise HomeAssistantError(f"Could not {stage}: {err or type(err).__name__}") from err
    return path
