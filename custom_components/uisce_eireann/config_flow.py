"""Config and options flow for Uisce Éireann outages."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, UnitOfLength
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .api import UisceClient, UisceError
from .const import (
    CONF_INCLUDE_CLOSED,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    DEFAULT_INCLUDE_CLOSED,
    DEFAULT_NAME,
    DEFAULT_RADIUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LAYER_URL,
    MAX_RADIUS,
    MAX_SCAN_INTERVAL,
    MIN_RADIUS,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _clamp_radius(value: Any) -> int:
    return int(min(max(float(value or DEFAULT_RADIUS), MIN_RADIUS), MAX_RADIUS))


class UisceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a location to monitor."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a name and a location with radius."""
        errors: dict[str, str] = {}

        if user_input is not None:
            location = user_input[CONF_LOCATION]
            lat = float(location[CONF_LATITUDE])
            lon = float(location[CONF_LONGITUDE])
            radius = _clamp_radius(location.get(CONF_RADIUS))

            await self.async_set_unique_id(f"{lat:.4f}_{lon:.4f}")
            self._abort_if_unique_id_configured()

            client = UisceClient(async_get_clientsession(self.hass), LAYER_URL)
            try:
                await client.async_get_field_map()
            except UisceError as err:
                _LOGGER.warning("Could not reach the Uisce Éireann feed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_LATITUDE: lat, CONF_LONGITUDE: lon},
                    options={
                        CONF_RADIUS: radius,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_INCLUDE_CLOSED: DEFAULT_INCLUDE_CLOSED,
                    },
                )

        defaults = user_input or {
            CONF_NAME: DEFAULT_NAME,
            CONF_LOCATION: {
                CONF_LATITUDE: self.hass.config.latitude,
                CONF_LONGITUDE: self.hass.config.longitude,
                CONF_RADIUS: DEFAULT_RADIUS,
            },
        }
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults[CONF_NAME]): TextSelector(),
                vol.Required(CONF_LOCATION, default=defaults[CONF_LOCATION]): LocationSelector(
                    LocationSelectorConfig(radius=True)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return UisceOptionsFlow()


class UisceOptionsFlow(OptionsFlow):
    """Adjust radius, polling interval and closed-notice handling."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_RADIUS: _clamp_radius(user_input[CONF_RADIUS]),
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_INCLUDE_CLOSED: bool(user_input[CONF_INCLUDE_CLOSED]),
                }
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIUS, default=options.get(CONF_RADIUS, DEFAULT_RADIUS)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_RADIUS,
                        max=MAX_RADIUS,
                        step=500,
                        unit_of_measurement=UnitOfLength.METERS,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_INCLUDE_CLOSED,
                    default=options.get(CONF_INCLUDE_CLOSED, DEFAULT_INCLUDE_CLOSED),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
