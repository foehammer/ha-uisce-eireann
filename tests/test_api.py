"""Tests for the HA-independent ArcGIS client."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.uisce_eireann.api import (
    FieldMap,
    UisceClient,
    UisceResponseError,
    deduplicate,
    epoch_ms_to_datetime,
    haversine_km,
)
from custom_components.uisce_eireann.const import LAYER_URL

from .conftest import HOME, LAYER_METADATA


def test_field_map_resolves_roles() -> None:
    fm = FieldMap.from_layer(LAYER_METADATA)
    assert fm.object_id == "OBJECTID"
    assert fm.roles == {
        "start": "STARTDATE",
        "end": "ENDDATE",
        "status": "STATUS",
        "title": "TITLE",
        "description": "DESCRIPTION",
        "reference": "REFERENCENUM",
        "county": "COUNTY",
        "location": "LOCATION",
        "work_type": "WORKTYPE",
    }
    assert "LASTUPDATE" in fm.date_fields
    assert fm.max_record_count == 2


def test_field_map_falls_back_to_aliases_and_tolerates_gaps() -> None:
    fm = FieldMap.from_layer(
        {
            "fields": [
                {"name": "FID", "type": "esriFieldTypeOID"},
                {"name": "F1", "type": "esriFieldTypeString", "alias": "Notice Title"},
                {"name": "F2", "type": "esriFieldTypeString", "alias": "Case Status"},
                {"name": "F3", "type": "esriFieldTypeDate", "alias": "Start of works"},
            ]
        }
    )
    assert fm.object_id == "FID"
    assert fm.roles == {"title": "F1", "status": "F2", "start": "F3"}
    assert fm.get("county") is None


def test_coded_value_status_is_decoded() -> None:
    from custom_components.uisce_eireann.api import parse_feature

    fm = FieldMap.from_layer(
        {
            "objectIdField": "OBJECTID",
            "fields": [
                {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                {
                    "name": "CASESTATUS",
                    "type": "esriFieldTypeSmallInteger",
                    "domain": {
                        "type": "codedValue",
                        "codedValues": [{"code": 1, "name": "Open"}, {"code": 2, "name": "Closed"}],
                    },
                },
            ],
        }
    )
    assert fm.get("status") == "CASESTATUS"
    open_n = parse_feature({"attributes": {"OBJECTID": 1, "CASESTATUS": 1}}, fm)
    closed_n = parse_feature({"attributes": {"OBJECTID": 2, "CASESTATUS": 2}}, fm)
    assert open_n.status == "Open" and open_n.is_open
    assert closed_n.status == "Closed" and not closed_n.is_open
    assert closed_n.attributes["CASESTATUS"] == "Closed"


def test_field_map_rejects_empty_metadata() -> None:
    with pytest.raises(UisceResponseError):
        FieldMap.from_layer({"fields": []})


def test_dates() -> None:
    assert epoch_ms_to_datetime(1_761_383_527_000).year == 2025
    assert epoch_ms_to_datetime(None) is None
    assert epoch_ms_to_datetime("nope") is None
    # Year-0206 typo seen in the real feed is rejected.
    assert epoch_ms_to_datetime(-55_910_000_000_000) is None


def test_haversine() -> None:
    # Castlebar to Westport is roughly 15 km.
    assert 14 < haversine_km(53.8556, -9.2988, 53.8000, -9.5167) < 16


async def test_query_pages_filters_and_parses(hass: HomeAssistant, fake_layer) -> None:
    client = UisceClient(async_get_clientsession(hass), LAYER_URL)
    pins = await client.async_query_near(*HOME, 5000)

    # 7 features: #4 out of range, #6 has no pin -> 5 pins (incl. closed #5).
    assert sorted(p.object_id for p in pins) == [1, 2, 3, 5, 7]
    assert [p.distance_km for p in pins] == sorted(p.distance_km for p in pins)
    assert fake_layer.query_calls >= 3  # page size 2 forces paging

    by_id = {p.object_id: p for p in pins}
    assert by_id[1].distance_km == 0
    assert by_id[1].category == "Burst Water Main"
    assert by_id[7].category == "Mains Repair Works"  # dash with no trailing space
    assert by_id[7].reference == "MAY00000007"  # padding stripped
    assert by_id[7].start is None  # implausible year dropped
    assert by_id[1].start.isoformat() == "2026-10-25T09:12:07+00:00"
    assert by_id[5].is_open is False
    assert by_id[1].attributes["LASTUPDATE"] is None

    notices = deduplicate(pins)
    first = notices[0]
    assert first.reference == "MAY00000001" and first.pin_count == 2 and first.object_id == 1


async def test_arcgis_error_payload_raises(hass: HomeAssistant, fake_layer) -> None:
    fake_layer.fail_with = {"error": {"code": 400, "message": "Invalid query"}}
    client = UisceClient(async_get_clientsession(hass), LAYER_URL)
    with pytest.raises(UisceResponseError, match="Invalid query"):
        await client.async_query_near(*HOME, 5000)
