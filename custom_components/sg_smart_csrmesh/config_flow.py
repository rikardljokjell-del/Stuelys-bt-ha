"""Learn the existing switch route and test the light before offering dimming."""

import asyncio
import logging
import re
from time import monotonic

try:
    import probatio as vol
except ImportError:  # Older Home Assistant versions
    import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import DOMAIN
from .mesh import Lamp, MeshError
from .protocol import FEF1, network_key, switch_power

_LOGGER = logging.getLogger(__name__)


def is_pill(info):
    return re.fullmatch(r"@MC[0-9A-Fa-f]{4}", info.name or "") and FEF1 in info.service_uuids


class SGConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.preselected = None
        self.settings = {}
        self.lamp = None
        self.unsubscribe = None
        self.read_back = False
        self.test_status = {}

    async def async_step_bluetooth(self, discovery_info):
        if not is_pill(discovery_info):
            return self.async_abort(reason="not_pill")
        self.preselected = discovery_info.address
        await self.async_set_unique_id(self.preselected)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        devices = {
            info.address: info.name
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if is_pill(info) and (not self.preselected or info.address == self.preselected)
        }
        if not devices:
            _LOGGER.warning("No connectable @MC receiver advertising FEF1 in Home Assistant Bluetooth")
            return self.async_abort(reason="no_devices")
        errors = {}
        if user_input is not None:
            address = user_input["address"]
            if address not in devices:
                return self.async_abort(reason="no_devices")
            if re.fullmatch(r"(?:0[xX])?[a-fA-F0-9]{1,4}", user_input["switch_id"].strip()):
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self.settings = {
                    "address": address, "name": devices[address],
                    "password": user_input["password"],
                    "switch_id": int(user_input["switch_id"].strip(), 16),
                    "transport": user_input.get("transport", "gatt"),
                }
                return await self.async_step_learn()
            errors["switch_id"] = "invalid_id"
        choices = {address: f"{name} ({address})" for address, name in devices.items()}
        return self.async_show_form(
            step_id="user", errors=errors, data_schema=vol.Schema({
                vol.Required("address", default=next(iter(choices))): vol.In(choices),
                vol.Required("password"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required("switch_id"): str,
                vol.Optional("transport", default="gatt"): SelectSelector(SelectSelectorConfig(
                    options=["gatt", "gatt_without_response", "advertisement"],
                    translation_key="transport",
                )),
            }),
        )

    async def async_step_learn(self, user_input=None):
        if self.lamp is not None and user_input is not None:
            return await self.async_step_off()
        errors = {}
        if user_input is not None:
            _LOGGER.warning("No fresh authenticated ON from switch %04X; check PIN, switch ID and Bluetooth reception",
                            self.settings["switch_id"])
            errors["base"] = "no_press"
        if self.unsubscribe is None:
            key = network_key(self.settings["password"])
            started = monotonic()

            @callback
            def on_advert(info, _change):
                if info.time < started or self.lamp is not None:
                    return
                event = switch_power(key, info.service_data.get(FEF1, b""), self.settings["switch_id"])
                if event is None or not event[2]:
                    return
                group, location, _, _ = event
                self.settings.update(group=group, location=location.hex())
                self.lamp = Lamp(self.hass, self.settings)
                self._stop_listening()

            self.unsubscribe = bluetooth.async_register_callback(
                self.hass, on_advert, {"service_data_uuid": FEF1, "connectable": False},
                bluetooth.BluetoothScanningMode.PASSIVE,
            )
        return self.async_show_form(step_id="learn", data_schema=vol.Schema({}), errors=errors)

    @callback
    def _stop_listening(self):
        if self.unsubscribe is not None:
            self.unsubscribe()
            self.unsubscribe = None

    @callback
    def async_remove(self):
        self._stop_listening()
        super().async_remove()

    async def _test(self, step, user_input, on, next_step):
        detail = ""
        if user_input is not None:
            try:
                await self.lamp.power(on)
            except MeshError as err:
                detail = str(err)
            else:
                if self.read_back and self.lamp.power_node is not None:
                    await asyncio.sleep(1)
                    try:
                        percent = await self.lamp.status(self.lamp.power_node)
                    except MeshError as err:
                        self.test_status[step] = str(err)
                    else:
                        self.test_status[step] = f"FF05: {percent} %"
                        _LOGGER.debug("%s direct %s test read back %d%%", self.lamp.name, step, percent)
                return await next_step()
        step_id = f"direct_{step}" if self.lamp.power_node is not None else step
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema({}),
            errors={"base": "ble_failed"} if detail else {},
            description_placeholders={"detail": detail, "name": self.settings["name"],
                                      "group": f'{self.settings["group"]:04X}'},
        )

    async def async_step_off(self, user_input=None):
        return await self._test("off", user_input, False, self.async_step_on)

    async def async_step_on(self, user_input=None):
        return await self._test("on", user_input, True, self.async_step_confirm)

    async def async_step_direct(self, user_input=None):
        detail = ""
        if user_input is not None:
            try:
                node = await self.lamp.identify()
            except MeshError as err:
                detail = str(err)
            else:
                self.settings["power_node"] = self.lamp.power_node = node
                self.read_back = user_input["read_back"]
                return await self.async_step_direct_off()
        return self.async_show_form(
            step_id="direct",
            data_schema=vol.Schema({vol.Required("read_back", default=True): bool}),
            errors={"base": "no_name_reply"} if detail else {},
            description_placeholders={"name": self.settings["name"], "detail": detail},
        )

    async def async_step_direct_off(self, user_input=None):
        return await self._test("off", user_input, False, self.async_step_direct_on)

    async def async_step_direct_on(self, user_input=None):
        return await self._test("on", user_input, True, self.async_step_confirm)

    async def async_step_confirm(self, user_input=None):
        report = {
            "off_status": self.test_status.get("off", "—"),
            "on_status": self.test_status.get("on", "—"),
        }
        if user_input is not None:
            if user_input["observed"]:
                return self.async_create_entry(title=self.settings["name"], data=self.settings)
            if self.lamp.transport == "advertisement":
                _LOGGER.warning("%s did not respond to the BLE advertisement power test", self.lamp.name)
                return self.async_abort(reason="no_advertisement_response")
            if self.lamp.power_node is None:
                _LOGGER.info("%s did not respond to the group power test", self.lamp.name)
                return await self.async_step_direct()
            _LOGGER.warning(
                "%s did not respond to the direct power test. OFF %s | ON %s",
                self.lamp.name, report["off_status"], report["on_status"],
            )
            return self.async_abort(reason="no_lamp_response", description_placeholders=report)
        step_id = "confirm" if self.lamp.power_node is None else "direct_confirm"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("observed", default=False): bool}),
            description_placeholders=report,
        )

    async def async_step_direct_confirm(self, user_input=None):
        return await self.async_step_confirm(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SGOptionsFlow()


class SGOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        detail = ""
        if user_input is not None:
            if not user_input["dimming"]:
                return self.async_create_entry(title="", data={})
            lamp = self.config_entry.runtime_data
            try:
                node = lamp.power_node if lamp.power_node is not None else await lamp.identify()
                await lamp.status(node)
            except MeshError as err:
                detail = str(err)
            else:
                return self.async_create_entry(title="", data={"node": node})
        return self.async_show_form(
            step_id="init", errors={"base": "no_status"} if detail else {},
            description_placeholders={"detail": detail},
            data_schema=vol.Schema({
                vol.Required("dimming", default="node" in self.config_entry.options): bool,
            }),
        )
