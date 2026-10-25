"""Binary sensor: is there an open notice in range."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UisceConfigEntry
from .entity import UisceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UisceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([UisceNoticeActiveBinarySensor(entry.runtime_data)])


class UisceNoticeActiveBinarySensor(UisceEntity, BinarySensorEntity):
    """On while at least one open notice is within the radius."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, "active")

    @property
    def is_on(self) -> bool:
        """Return True if any open notice is in range."""
        return bool(self.coordinator.data.open_notices)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the titles and references of open notices."""
        return {
            "titles": [n.title for n in self.coordinator.data.open_notices],
            "references": [n.reference for n in self.coordinator.data.open_notices],
        }
