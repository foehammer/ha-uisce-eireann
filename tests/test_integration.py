"""End-to-end tests through Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.uisce_eireann.const import (
    CONF_INCLUDE_CLOSED,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    EVENT_NOTICE_CLEARED,
    EVENT_NOTICE_NEW,
)

from .conftest import HOME, feature

COUNT = "sensor.water_outages_home_open_notices"
NEAREST = "sensor.water_outages_home_nearest_notice"
ACTIVE = "binary_sensor.water_outages_home_outage_nearby"


def geo_states(hass: HomeAssistant) -> list:
    return [
        s for s in hass.states.async_all("geo_location") if s.attributes.get("source") == DOMAIN
    ]


async def test_config_flow_creates_entry(hass: HomeAssistant, fake_layer) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Home",
            "location": {"latitude": HOME[0], "longitude": HOME[1], "radius": 120},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {"latitude": HOME[0], "longitude": HOME[1]}
    assert result["options"][CONF_RADIUS] == 500  # clamped up to the minimum
    await hass.async_block_till_done()

    # Same location again is rejected.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Again", "location": {"latitude": HOME[0], "longitude": HOME[1], "radius": 5000}},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_config_flow_cannot_connect(hass: HomeAssistant, fake_layer) -> None:
    fake_layer.fail_with = {"error": {"code": 500, "message": "down"}}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Home", "location": {"latitude": HOME[0], "longitude": HOME[1], "radius": 5000}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_entities_events_and_map(
    hass: HomeAssistant, fake_layer, make_entry, freezer: FrozenDateTimeFactory
) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # Open in range after dedup: MAY00000001 (2 pins), #3, #7. Closed #5 excluded.
    count = hass.states.get(COUNT)
    assert count.state == "3"
    assert [n["reference"] for n in count.attributes["notices"]] == [
        "MAY00000001",
        "MAY00000003",
        "MAY00000007",
    ]
    assert count.attributes["notices"][0]["pins"] == 2
    assert hass.states.get(NEAREST).state == "0.0"
    assert hass.states.get(ACTIVE).state == STATE_ON
    assert len(geo_states(hass)) == 3

    new_events = async_capture_events(hass, EVENT_NOTICE_NEW)
    cleared_events = async_capture_events(hass, EVENT_NOTICE_CLEARED)

    # A notice closes, another one opens.
    lat, lon = HOME
    fake_layer.features = [f for f in fake_layer.features if f["attributes"]["OBJECTID"] != 3]
    fake_layer.features.append(feature(8, lat + 0.005, lon, title="Low Pressure - Mayo"))
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert [e.data["reference"] for e in new_events] == ["MAY00000008"]
    assert new_events[0].data["category"] == "Low Pressure"
    assert [e.data["reference"] for e in cleared_events] == ["MAY00000003"]
    assert hass.states.get(COUNT).state == "3"
    assert sorted(s.attributes["reference"] for s in geo_states(hass)) == [
        "MAY00000001",
        "MAY00000007",
        "MAY00000008",
    ]

    # Everything clears.
    fake_layer.features = []
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(COUNT).state == "0"
    assert hass.states.get(NEAREST).state == STATE_UNKNOWN
    assert hass.states.get(ACTIVE).state == STATE_OFF
    assert geo_states(hass) == []
    assert len(cleared_events) == 4

    # Feed outage makes entities unavailable rather than falsely "clear".
    fake_layer.fail_with = {"error": {"code": 500, "message": "down"}}
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_change_reloads(hass: HomeAssistant, fake_layer, make_entry) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_RADIUS: 30000, CONF_SCAN_INTERVAL: 30, CONF_INCLUDE_CLOSED: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    count = hass.states.get(COUNT)
    # #4 (~22 km) is now in range; the closed notice is listed but not counted.
    assert count.state == "4"
    assert count.attributes["total_in_range"] == 5
    assert count.attributes["radius_km"] == 30
    assert entry.runtime_data.update_interval == timedelta(minutes=30)


async def test_setup_retries_when_feed_down(hass: HomeAssistant, fake_layer, make_entry) -> None:
    fake_layer.fail_with = {"error": {"code": 500, "message": "down"}}
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(hass: HomeAssistant, hass_client, fake_layer, make_entry) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diag["entry"]["data"]["latitude"] == "**REDACTED**"
    assert diag["field_map"]["roles"]["title"] == "TITLE"
    assert diag["field_map"]["unmatched_roles"] == []
    assert diag["open_in_range"] == 3
