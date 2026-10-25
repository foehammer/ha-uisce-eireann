"""Data update coordinator for Uisce Éireann outages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Notice, UisceClient, UisceError, deduplicate
from .const import (
    CONF_INCLUDE_CLOSED,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    DEFAULT_INCLUDE_CLOSED,
    DEFAULT_RADIUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_NOTICE_CLEARED,
    EVENT_NOTICE_NEW,
    MAX_DESCRIPTION_LENGTH,
)

if TYPE_CHECKING:
    from . import UisceConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UisceData:
    """Snapshot of notices around the configured location."""

    notices: list[Notice] = field(default_factory=list)
    fetched_at: datetime | None = None

    @property
    def open_notices(self) -> list[Notice]:
        """Open notices, nearest first."""
        return [n for n in self.notices if n.is_open]


class UisceCoordinator(DataUpdateCoordinator[UisceData]):
    """Polls the ArcGIS layer for notices near one location."""

    config_entry: UisceConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UisceConfigEntry, client: UisceClient) -> None:
        """Initialise the coordinator."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client

    @property
    def latitude(self) -> float:
        """Configured latitude."""
        return float(self.config_entry.data[CONF_LATITUDE])

    @property
    def longitude(self) -> float:
        """Configured longitude."""
        return float(self.config_entry.data[CONF_LONGITUDE])

    @property
    def radius_m(self) -> float:
        """Configured search radius in metres."""
        return float(self.config_entry.options.get(CONF_RADIUS, DEFAULT_RADIUS))

    async def _async_update_data(self) -> UisceData:
        include_closed = self.config_entry.options.get(CONF_INCLUDE_CLOSED, DEFAULT_INCLUDE_CLOSED)
        try:
            pins = await self.client.async_query_near(self.latitude, self.longitude, self.radius_m)
        except UisceError as err:
            raise UpdateFailed(str(err)) from err

        notices = deduplicate(pins)
        if not include_closed:
            notices = [n for n in notices if n.is_open]

        new = UisceData(notices=notices, fetched_at=dt_util.utcnow())
        self._fire_events(self.data, new)
        return new

    def _fire_events(self, old: UisceData | None, new: UisceData) -> None:
        """Fire new/cleared events, skipping the first refresh."""
        if old is None:
            return
        old_open = {n.key: n for n in old.open_notices}
        new_open = {n.key: n for n in new.open_notices}
        base = {"config_entry_id": self.config_entry.entry_id, "name": self.config_entry.title}

        for key in new_open.keys() - old_open.keys():
            self.hass.bus.async_fire(
                EVENT_NOTICE_NEW, {**base, **new_open[key].summary(MAX_DESCRIPTION_LENGTH)}
            )
        for key in old_open.keys() - new_open.keys():
            # Closed, dropped from the feed, or moved out of range.
            self.hass.bus.async_fire(
                EVENT_NOTICE_CLEARED, {**base, **old_open[key].summary(MAX_DESCRIPTION_LENGTH)}
            )
