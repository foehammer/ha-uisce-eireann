"""Sensors for Uisce Éireann outages."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UisceConfigEntry
from .const import MAX_DESCRIPTION_LENGTH, MAX_NOTICES_IN_ATTRIBUTES
from .entity import UisceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UisceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities([UisceNoticeCountSensor(coordinator), UisceNearestNoticeSensor(coordinator)])


class UisceNoticeCountSensor(UisceEntity, SensorEntity):
    """Number of notices in range, with the notices as attributes."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "notices"

    def __init__(self, coordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "notices")

    @property
    def native_value(self) -> int:
        """Return the number of open notices."""
        return len(self.coordinator.data.open_notices)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return notices (nearest first) and query details."""
        data = self.coordinator.data
        return {
            "radius_km": round(self.coordinator.radius_m / 1000, 2),
            "last_fetched": data.fetched_at.isoformat() if data.fetched_at else None,
            "total_in_range": len(data.notices),
            "notices": [
                n.summary(MAX_DESCRIPTION_LENGTH) for n in data.notices[:MAX_NOTICES_IN_ATTRIBUTES]
            ],
        }


class UisceNearestNoticeSensor(UisceEntity, SensorEntity):
    """Distance to the nearest open notice."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "nearest")

    @property
    def native_value(self) -> float | None:
        """Return the distance, or unknown when nothing is open in range."""
        notices = self.coordinator.data.open_notices
        return notices[0].distance_km if notices else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the nearest notice."""
        notices = self.coordinator.data.open_notices
        return notices[0].summary(MAX_DESCRIPTION_LENGTH) if notices else {}
