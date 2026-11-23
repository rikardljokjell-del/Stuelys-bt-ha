"""Relative dimming controls for a lamp without reported brightness."""

from homeassistant.components.button import ButtonEntity

from . import device_info


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("advertised_dimming") == "relative":
        lamp = entry.runtime_data
        async_add_entities([DimButton(lamp, True), DimButton(lamp, False)])


class DimButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, lamp, up):
        self.lamp = lamp
        self.up = up
        direction = "dim_up" if up else "dim_down"
        self._attr_translation_key = direction
        self._attr_unique_id = f"{lamp.address}_{direction}"
        self._attr_device_info = device_info(lamp)

    async def async_press(self):
        await self.lamp.dim_step(self.up)
