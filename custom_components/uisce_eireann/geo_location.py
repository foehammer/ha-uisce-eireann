"""Map pins for open notices (geo_location platform)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import UisceConfigEntry
from .api import Notice
from .const import ATTRIBUTION, GEO_SOURCE, MAX_DESCRIPTION_LENGTH
from .coordinator import UisceCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UisceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create and remove one entity per open notice as the feed changes."""
    coordinator = entry.runtime_data
    entities: dict[str, UisceNoticeGeoEvent] = {}

    @callback
    def _sync() -> None:
        current = {n.key: n for n in coordinator.data.open_notices if n.latitude is not None}
        for key in entities.keys() - current.keys():
            hass.async_create_task(entities.pop(key).async_remove(force_remove=True))
        to_add = []
        for key, notice in current.items():
            if key in entities:
                entities[key].update_notice(notice)
            else:
                entities[key] = UisceNoticeGeoEvent(coordinator, notice)
                to_add.append(entities[key])
        if to_add:
            async_add_entities(to_add)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class UisceNoticeGeoEvent(GeolocationEvent):
    """One notice shown on the map."""

    _attr_should_poll = False
    _attr_source = GEO_SOURCE
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator: UisceCoordinator, notice: Notice) -> None:
        """Initialise the event entity."""
        self._entry_title = coordinator.config_entry.title
        self._notice = notice
        self._apply(notice)

    def _apply(self, notice: Notice) -> None:
        self._notice = notice
        self._attr_name = notice.title or notice.reference or f"Notice {notice.object_id}"
        self._attr_latitude = notice.latitude
        self._attr_longitude = notice.longitude
        self._attr_distance = notice.distance_km

    @callback
    def update_notice(self, notice: Notice) -> None:
        """Refresh from a newer copy of the same notice."""
        self._apply(notice)
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return notice details."""
        attrs = self._notice.summary(MAX_DESCRIPTION_LENGTH)
        attrs.pop("latitude", None)
        attrs.pop("longitude", None)
        attrs.pop("distance_km", None)
        attrs["monitored_location"] = self._entry_title
        return attrs
