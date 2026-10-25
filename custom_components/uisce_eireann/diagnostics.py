"""Diagnostics: shows which feed fields were matched to which roles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import UisceConfigEntry
from .const import CONF_LATITUDE, CONF_LONGITUDE

TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UisceConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    fields = coordinator.client.field_map
    data = coordinator.data
    sample = data.notices[0] if data and data.notices else None
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "field_map": {
            "object_id": fields.object_id if fields else None,
            "roles": dict(fields.roles) if fields else None,
            "unmatched_roles": sorted(
                {
                    "start",
                    "end",
                    "status",
                    "title",
                    "description",
                    "reference",
                    "county",
                    "location",
                    "work_type",
                }
                - set(fields.roles)
            )
            if fields
            else None,
            "all_fields": list(fields.all_fields) if fields else None,
            "page_size": fields.max_record_count if fields else None,
        },
        "notices_in_range": len(data.notices) if data else None,
        "open_in_range": len(data.open_notices) if data else None,
        "sample_raw_attributes": sample.attributes if sample else None,
    }
