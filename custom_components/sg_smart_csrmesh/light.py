"""One standard Home Assistant light for the tested wall-switch route."""

import asyncio
from datetime import timedelta
import logging
from time import monotonic

from homeassistant.components import bluetooth
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import callback

from . import device_info
from .mesh import MeshError
from .protocol import FEF1, switch_dimming, switch_power

SCAN_INTERVAL = timedelta(minutes=2)
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SGLight(entry)], update_before_add="node" in entry.options)


class SGLight(LightEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry):
        self.lamp = entry.runtime_data
        self.switch = entry.data["switch_id"]
        self.node = entry.options.get("node")
        self.advertised_brightness = entry.options.get("advertised_dimming") == "absolute"
        self._actions = asyncio.Lock()
        self._attr_unique_id = self.lamp.address
        self._attr_device_info = device_info(self.lamp)
        mode = (
            ColorMode.BRIGHTNESS if self.node is not None or self.advertised_brightness
            else ColorMode.ONOFF
        )
        self._attr_supported_color_modes = {mode}
        self._attr_color_mode = mode
        self._attr_assumed_state = self.node is None
        self._attr_should_poll = self.node is not None
        self._attr_is_on = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.node is not None:
            return
        started = monotonic()
        last_seq = None

        @callback
        def on_advert(info, _change):
            nonlocal last_seq
            if info.time < started:
                return
            frame = info.service_data.get(FEF1, b"")
            event = switch_power(self.lamp.key, frame, self.switch)
            if event is None and self.advertised_brightness and self.brightness is not None:
                dimming = switch_dimming(self.lamp.key, frame, self.switch)
                if dimming is not None and dimming[:2] == (self.lamp.group, self.lamp.location):
                    self._attr_brightness = None
                    self.async_write_ha_state()
            if event is None:
                return
            group, location, on, seq = event
            if (group, location) != (self.lamp.group, self.lamp.location) or seq == last_seq:
                return
            last_seq = seq
            self._attr_is_on = on
            self.async_write_ha_state()

        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, on_advert, {"service_data_uuid": FEF1, "connectable": False},
            bluetooth.BluetoothScanningMode.PASSIVE,
        ))

    def _set_status(self, percent):
        self._attr_is_on = percent > 0
        self._attr_brightness = round(percent * 255 / 100)

    def _unknown(self):
        self._attr_is_on = None
        self._attr_brightness = None

    async def async_update(self):
        if self.node is None:
            return
        async with self._actions:
            try:
                self._set_status(await self.lamp.status(self.node))
            except MeshError:
                self._unknown()

    async def _command(self, on, brightness=None):
        async with self._actions:
            mismatch = None
            try:
                if brightness and self.advertised_brightness:
                    percent = max(1, round(brightness * 100 / 255))
                    await self.lamp.advertised_level(percent)
                    self._set_status(percent)
                elif brightness and self.node is not None:
                    percent = max(1, round(brightness * 100 / 255))
                    actual = await self.lamp.set_level(self.node, percent)
                    self._set_status(actual)
                    if actual != percent:
                        mismatch = f"Requested {percent}% but {self.lamp.name} reported {actual}%"
                else:
                    await self.lamp.power(on)
                    if self.node is None:
                        self._attr_is_on = on
                    else:
                        await asyncio.sleep(1)
                        self._set_status(await self.lamp.status(self.node))
                        if self._attr_is_on != on:
                            mismatch = f"{self.lamp.name} reported a different power state after the command"
            except MeshError:
                # A write can succeed even when the subsequent read fails.
                self._unknown()
                raise
            finally:
                self.async_write_ha_state()
            if mismatch:
                _LOGGER.warning("%s", mismatch)
                raise MeshError(mismatch)

    async def async_turn_on(self, **kwargs):
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        await self._command(brightness != 0, brightness)

    async def async_turn_off(self, **kwargs):
        await self._command(False)
