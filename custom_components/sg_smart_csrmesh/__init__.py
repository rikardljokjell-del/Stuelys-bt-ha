"""SG Smart CSRmesh for an existing wall switch and dimmer."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .mesh import Lamp

DOMAIN = "sg_smart_csrmesh"
PLATFORMS = [Platform.LIGHT, Platform.BUTTON]


def device_info(lamp: Lamp) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, lamp.address)},
        connections={(CONNECTION_BLUETOOTH, lamp.address)},
        name=f"SG Smart {lamp.name}",
        manufacturer="SG Armaturen",
        model="LEDDim Smart Pill (CSRmesh)",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.runtime_data = Lamp(hass, entry.data)
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
