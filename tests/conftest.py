"""Fixtures: a fake ArcGIS layer that pages and filters like the real one."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.uisce_eireann.const import LAYER_URL

HOME = (53.8556, -9.2988)  # Castlebar

LAYER_METADATA: dict[str, Any] = {
    "name": "WaterAdvisory",
    "objectIdField": "OBJECTID",
    "maxRecordCount": 2,  # tiny, so paging is exercised
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID"},
        {"name": "TITLE", "type": "esriFieldTypeString", "alias": "Title"},
        {"name": "DESCRIPTION", "type": "esriFieldTypeString", "alias": "Description"},
        {"name": "STATUS", "type": "esriFieldTypeString", "alias": "Status"},
        {"name": "REFERENCENUM", "type": "esriFieldTypeString", "alias": "Reference"},
        {"name": "COUNTY", "type": "esriFieldTypeString", "alias": "County"},
        {"name": "LOCATION", "type": "esriFieldTypeString", "alias": "Location"},
        {"name": "WORKTYPE", "type": "esriFieldTypeString", "alias": "Work Type"},
        {"name": "STARTDATE", "type": "esriFieldTypeDate", "alias": "Start"},
        {"name": "ENDDATE", "type": "esriFieldTypeDate", "alias": "End"},
        {"name": "LASTUPDATE", "type": "esriFieldTypeDate", "alias": "Last Update"},
        {"name": "WATEROUTAGE", "type": "esriFieldTypeSmallInteger", "alias": "Outage"},
    ],
}


def ms(dt: datetime) -> int:
    """Epoch milliseconds."""
    return int(dt.timestamp() * 1000)


def feature(
    oid: int,
    lat: float | None,
    lon: float | None,
    *,
    title: str = "Burst Water Main - Mayo",
    status: str = "Open",
    ref: str | None = None,
    start: int | None = None,
    geometry: Any = "auto",
) -> dict[str, Any]:
    """Build one ArcGIS feature."""
    if geometry == "auto":
        geometry = {"x": lon, "y": lat} if lat is not None else None
    return {
        "attributes": {
            "OBJECTID": oid,
            "TITLE": title,
            "DESCRIPTION": "Repairs to a burst water main may cause supply disruptions.",
            "STATUS": status,
            "REFERENCENUM": ref if ref is not None else f"MAY{oid:08d}",
            "COUNTY": "Mayo",
            "LOCATION": "Castlebar",
            "WORKTYPE": "Unplanned",
            "STARTDATE": start
            if start is not None
            else ms(datetime(2026, 10, 25, 9, 12, 7, tzinfo=UTC)),
            "ENDDATE": ms(datetime(2026, 10, 25, 18, 0, tzinfo=UTC)),
            "LASTUPDATE": None,
            "WATEROUTAGE": 1,
        },
        "geometry": geometry,
    }


def default_features() -> list[dict[str, Any]]:
    """A realistic mix around Castlebar."""
    lat, lon = HOME
    return [
        feature(1, lat, lon, ref="MAY00000001"),  # at home
        feature(2, lat + 0.027, lon, ref="MAY00000001"),  # 2nd pin, ~3 km
        feature(3, lat + 0.018, lon + 0.01, title="Essential Maintenance Works - Mayo"),  # ~2 km
        feature(4, lat + 0.2, lon),  # ~22 km, out of range
        feature(5, lat - 0.01, lon, status="Closed"),  # closed
        feature(6, None, None, geometry="NaN"),  # no pin
        feature(
            7,
            lat + 0.03,
            lon - 0.02,
            ref=" MAY00000007\xa0",  # padded ref
            start=ms(datetime(206, 8, 10, 10, 15, tzinfo=UTC)),
            title="Mains Repair Works -Mayo",
        ),
    ]


class FakeLayer:
    """Answers metadata and paged envelope queries."""

    def __init__(self) -> None:
        self.features = default_features()
        self.metadata = LAYER_METADATA
        self.fail_with: dict[str, Any] | None = None
        self.query_calls = 0

    async def handle(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if self.fail_with is not None:
            return AiohttpClientMockResponse(method, url, json=self.fail_with)
        if not str(url.path).endswith("/query"):
            return AiohttpClientMockResponse(method, url, json=self.metadata)

        self.query_calls += 1
        q = url.query
        assert q["f"] == "json"
        assert q["inSR"] == "4326" and q["outSR"] == "4326"
        assert q["orderByFields"] == "OBJECTID ASC"
        last = int(re.fullmatch(r"OBJECTID > (-?\d+)", q["where"]).group(1))
        xmin, ymin, xmax, ymax = map(float, q["geometry"].split(","))
        page = int(q["resultRecordCount"])

        def inside(f: dict[str, Any]) -> bool:
            g = f["geometry"]
            if not isinstance(g, dict):
                return True  # server returns null-geometry rows too
            return xmin <= g["x"] <= xmax and ymin <= g["y"] <= ymax

        rows = sorted(
            (f for f in self.features if f["attributes"]["OBJECTID"] > last and inside(f)),
            key=lambda f: f["attributes"]["OBJECTID"],
        )
        body = {"features": rows[:page], "exceededTransferLimit": len(rows) > page}
        return AiohttpClientMockResponse(method, url, json=body)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components in tests."""


@pytest.fixture
def fake_layer(aioclient_mock: AiohttpClientMocker) -> FakeLayer:
    """Register the fake ArcGIS service."""
    layer = FakeLayer()
    aioclient_mock.get(re.compile(re.escape(LAYER_URL)), side_effect=layer.handle)
    return layer


@pytest.fixture
def make_entry() -> Callable[..., Any]:
    """Build a config entry for Castlebar."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.uisce_eireann.const import (
        CONF_INCLUDE_CLOSED,
        CONF_LATITUDE,
        CONF_LONGITUDE,
        CONF_RADIUS,
        CONF_SCAN_INTERVAL,
        DOMAIN,
    )

    def _make(radius: int = 5000, include_closed: bool = False) -> MockConfigEntry:
        return MockConfigEntry(
            domain=DOMAIN,
            title="Home",
            unique_id=f"{HOME[0]:.4f}_{HOME[1]:.4f}",
            data={CONF_LATITUDE: HOME[0], CONF_LONGITUDE: HOME[1]},
            options={
                CONF_RADIUS: radius,
                CONF_SCAN_INTERVAL: 15,
                CONF_INCLUDE_CLOSED: include_closed,
            },
        )

    return _make
