"""Async client for the Uisce Éireann ArcGIS outage layer.

This module has no Home Assistant imports so it can be tested on its own.

Field names are discovered from the layer's own metadata (``?f=json``) rather
than hard-coded, because the feed is undocumented. Only ``STARTDATE`` and
``ENDDATE`` are known names; every other role is matched against the field
list the service returns, and anything unmatched is still exposed raw.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# The feed has carried hand-typed dates such as year 0206; treat anything
# before this as unusable.
EARLIEST_PLAUSIBLE_YEAR = 2000
DEFAULT_PAGE_SIZE = 1000
MAX_PAGES = 50

STRING_TYPES = {"esriFieldTypeString"}
DATE_TYPES = {"esriFieldTypeDate", "esriFieldTypeDateOnly", "esriFieldTypeTimestampOffset"}

# Roles resolved from layer metadata, in resolution order. Each entry is
# (role, allowed field types, exact names to prefer, fallback regex over
# name and alias). A field is only ever assigned to one role.
_ROLE_RULES: tuple[tuple[str, set[str], tuple[str, ...], str], ...] = (
    ("start", DATE_TYPES, ("STARTDATE",), r"start"),
    ("end", DATE_TYPES, ("ENDDATE",), r"\bend|end.?date|finish"),
    ("status", STRING_TYPES, (), r"status"),
    ("title", STRING_TYPES, (), r"title|heading|subject"),
    ("description", STRING_TYPES, (), r"desc|detail|message|comment"),
    ("reference", STRING_TYPES, (), r"ref"),
    ("county", STRING_TYPES, (), r"county"),
    ("location", STRING_TYPES, (), r"location|area|address|town"),
    ("work_type", STRING_TYPES, (), r"work.?type|outage.?type|planned"),
)

_TITLE_SPLIT = re.compile(r"\s+[-–—]\s*|\s*[-–—]\s+")


class UisceError(Exception):
    """Base error for the client."""


class UisceConnectionError(UisceError):
    """The service could not be reached."""


class UisceResponseError(UisceError):
    """The service answered with an error or an unexpected payload."""


@dataclass(slots=True)
class FieldMap:
    """Mapping from semantic roles to the layer's actual field names."""

    object_id: str
    roles: dict[str, str]
    date_fields: frozenset[str]
    all_fields: tuple[str, ...]
    max_record_count: int = DEFAULT_PAGE_SIZE
    domains: dict[str, dict[Any, str]] = field(default_factory=dict)

    def decode(self, name: str, value: Any) -> Any:
        """Translate a coded-value domain code to its label."""
        coded = self.domains.get(name)
        if coded is None or value is None:
            return value
        return coded.get(value, coded.get(str(value), value))

    def get(self, role: str) -> str | None:
        """Return the field name for a role, if one was resolved."""
        return self.roles.get(role)

    @classmethod
    def from_layer(cls, layer: dict[str, Any]) -> FieldMap:
        """Build a field map from a layer's ``?f=json`` metadata."""
        fields = layer.get("fields")
        if not isinstance(fields, list) or not fields:
            raise UisceResponseError("Layer metadata has no field list")

        object_id = layer.get("objectIdField")
        if not object_id:
            object_id = next(
                (f["name"] for f in fields if f.get("type") == "esriFieldTypeOID"),
                "OBJECTID",
            )

        date_fields = frozenset(
            f["name"] for f in fields if f.get("type") in DATE_TYPES and f.get("name")
        )
        domains: dict[str, dict[Any, str]] = {}
        for f in fields:
            domain = f.get("domain")
            if isinstance(domain, dict) and domain.get("type") == "codedValue":
                domains[f["name"]] = {
                    cv["code"]: str(cv["name"])
                    for cv in domain.get("codedValues") or []
                    if "code" in cv and "name" in cv
                }
        taken: set[str] = {object_id}
        roles: dict[str, str] = {}

        for role, types, exact, pattern in _ROLE_RULES:
            candidates = [
                f
                for f in fields
                if f.get("name")
                and f["name"] not in taken
                # A coded-value field can carry text roles whatever its storage type.
                and (f.get("type") in types or (types is STRING_TYPES and f["name"] in domains))
            ]
            match = next(
                (f for name in exact for f in candidates if f["name"].upper() == name),
                None,
            )
            if match is None:
                regex = re.compile(pattern, re.IGNORECASE)
                match = next(
                    (
                        f
                        for f in candidates
                        if regex.search(f["name"]) or regex.search(f.get("alias") or "")
                    ),
                    None,
                )
            if match is not None:
                roles[role] = match["name"]
                taken.add(match["name"])

        try:
            max_records = int(layer.get("maxRecordCount") or DEFAULT_PAGE_SIZE)
        except (TypeError, ValueError):
            max_records = DEFAULT_PAGE_SIZE

        return cls(
            object_id=object_id,
            roles=roles,
            date_fields=date_fields,
            all_fields=tuple(f["name"] for f in fields if f.get("name")),
            max_record_count=max(1, min(max_records, DEFAULT_PAGE_SIZE)),
            domains=domains,
        )


@dataclass(slots=True)
class Notice:
    """One published notice (map pin)."""

    object_id: int
    latitude: float | None
    longitude: float | None
    attributes: dict[str, Any]
    title: str | None = None
    description: str | None = None
    status: str | None = None
    reference: str | None = None
    county: str | None = None
    location: str | None = None
    work_type: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    distance_km: float | None = None
    pin_count: int = 1

    @property
    def key(self) -> str:
        """Stable identity: the reference number, else the object id."""
        return self.reference or f"oid:{self.object_id}"

    @property
    def is_open(self) -> bool:
        """Whether the notice is open. Unknown status counts as open."""
        if self.status is None:
            return True
        return self.status.strip().lower() == "open"

    @property
    def category(self) -> str | None:
        """Kind of work, taken from a 'Category - County' style title."""
        if not self.title:
            return None
        return _TITLE_SPLIT.split(self.title, maxsplit=1)[0].strip() or None

    def summary(self, max_description: int | None = None) -> dict[str, Any]:
        """Compact, JSON-safe representation for attributes and events."""
        description = self.description
        if description and max_description and len(description) > max_description:
            description = description[: max_description - 1].rstrip() + "…"
        return {
            "reference": self.reference,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "county": self.county,
            "location": self.location,
            "work_type": self.work_type,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "distance_km": self.distance_km,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "pins": self.pin_count,
            "description": description,
        }


def epoch_ms_to_datetime(value: Any) -> datetime | None:
    """Convert ArcGIS epoch milliseconds to an aware UTC datetime."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or math.isnan(value):
        return None
    try:
        result = EPOCH + timedelta(milliseconds=value)
    except OverflowError:
        return None
    if result.year < EARLIEST_PLAUSIBLE_YEAR:
        return None
    return result


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bounding_envelope(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """WGS84 envelope (xmin, ymin, xmax, ymax) enclosing a circle."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def _geometry_point(geometry: Any) -> tuple[float, float] | None:
    """Representative (lat, lon) for a point, polyline or polygon."""
    if not isinstance(geometry, dict):
        return None
    x, y = geometry.get("x"), geometry.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        if math.isnan(x) or math.isnan(y):
            return None
        return float(y), float(x)
    parts = geometry.get("rings") or geometry.get("paths")
    if isinstance(parts, list) and parts and isinstance(parts[0], list):
        coords = [
            c
            for c in parts[0]
            if isinstance(c, list)
            and len(c) >= 2
            and all(isinstance(v, (int, float)) for v in c[:2])
        ]
        if coords:
            return (
                sum(c[1] for c in coords) / len(coords),
                sum(c[0] for c in coords) / len(coords),
            )
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    return text or None


def parse_feature(feature: dict[str, Any], fields: FieldMap) -> Notice | None:
    """Turn one ArcGIS feature into a Notice, or None if it is unusable."""
    attrs = feature.get("attributes")
    if not isinstance(attrs, dict):
        return None
    try:
        object_id = int(attrs[fields.object_id])
    except (KeyError, TypeError, ValueError):
        return None

    converted: dict[str, Any] = {}
    for name, value in attrs.items():
        if name in fields.date_fields:
            dt = epoch_ms_to_datetime(value)
            converted[name] = dt.isoformat() if dt else None
        else:
            converted[name] = fields.decode(name, value)

    def text(role: str) -> str | None:
        name = fields.get(role)
        return _clean_text(fields.decode(name, attrs.get(name))) if name else None

    def date(role: str) -> datetime | None:
        name = fields.get(role)
        return epoch_ms_to_datetime(attrs.get(name)) if name else None

    point = _geometry_point(feature.get("geometry"))
    return Notice(
        object_id=object_id,
        latitude=point[0] if point else None,
        longitude=point[1] if point else None,
        attributes=converted,
        title=text("title"),
        description=text("description"),
        status=text("status"),
        reference=text("reference"),
        county=text("county"),
        location=text("location"),
        work_type=text("work_type"),
        start=date("start"),
        end=date("end"),
    )


def deduplicate(notices: list[Notice]) -> list[Notice]:
    """Collapse pins sharing a reference into the nearest one."""
    best: dict[str, Notice] = {}
    counts: dict[str, int] = {}
    for notice in notices:
        key = notice.key
        counts[key] = counts.get(key, 0) + 1
        current = best.get(key)
        if current is None or _sort_distance(notice) < _sort_distance(current):
            best[key] = notice
    result = []
    for key, notice in best.items():
        notice.pin_count = counts[key]
        result.append(notice)
    result.sort(key=_sort_distance)
    return result


def _sort_distance(notice: Notice) -> float:
    return notice.distance_km if notice.distance_km is not None else math.inf


class UisceClient:
    """Read-only client for the outage layer."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        layer_url: str,
        *,
        timeout: float = 30,
    ) -> None:
        self._session = session
        self._layer_url = layer_url.rstrip("/")
        self._timeout = timeout
        self._fields: FieldMap | None = None

    @property
    def field_map(self) -> FieldMap | None:
        """The resolved field map, once fetched."""
        return self._fields

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UisceConnectionError(f"Error talking to ArcGIS: {err}") from err
        except ValueError as err:
            raise UisceResponseError(f"Invalid JSON from ArcGIS: {err}") from err
        if not isinstance(data, dict):
            raise UisceResponseError("Unexpected response from ArcGIS")
        if "error" in data:
            error = data["error"] or {}
            raise UisceResponseError(f"ArcGIS error {error.get('code')}: {error.get('message')}")
        return data

    async def async_get_field_map(self, *, refresh: bool = False) -> FieldMap:
        """Fetch layer metadata and resolve field roles (cached)."""
        if self._fields is None or refresh:
            layer = await self._get_json(self._layer_url, {"f": "json"})
            self._fields = FieldMap.from_layer(layer)
            _LOGGER.debug(
                "Resolved field roles %s (object id %s)",
                self._fields.roles,
                self._fields.object_id,
            )
        return self._fields

    async def async_query_near(
        self, latitude: float, longitude: float, radius_m: float
    ) -> list[Notice]:
        """Return every notice within ``radius_m`` metres, nearest first.

        Queries a bounding envelope server-side (supported by every hosted
        layer), pages by object id, then filters to the true circle.
        """
        fields = await self.async_get_field_map()
        oid = fields.object_id
        xmin, ymin, xmax, ymax = bounding_envelope(latitude, longitude, radius_m)
        radius_km = radius_m / 1000

        notices: list[Notice] = []
        last_id = -1
        for _ in range(MAX_PAGES):
            data = await self._get_json(
                f"{self._layer_url}/query",
                {
                    "where": f"{oid} > {last_id}",
                    "geometry": f"{xmin},{ymin},{xmax},{ymax}",
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": 4326,
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": 4326,
                    "orderByFields": f"{oid} ASC",
                    "resultRecordCount": fields.max_record_count,
                    "f": "json",
                },
            )
            features = data.get("features")
            if not isinstance(features, list):
                raise UisceResponseError("Query response has no feature list")
            if not features:
                break

            page_max = last_id
            for feature in features:
                notice = parse_feature(feature, fields)
                if notice is None:
                    continue
                page_max = max(page_max, notice.object_id)
                if notice.latitude is None or notice.longitude is None:
                    continue
                notice.distance_km = round(
                    haversine_km(latitude, longitude, notice.latitude, notice.longitude), 2
                )
                if notice.distance_km <= radius_km:
                    notices.append(notice)

            if page_max <= last_id:
                raise UisceResponseError("Paging made no progress")
            last_id = page_max
            if not data.get("exceededTransferLimit") and len(features) < fields.max_record_count:
                break
        else:
            _LOGGER.warning("Stopped after %s pages; results may be incomplete", MAX_PAGES)

        notices.sort(key=_sort_distance)
        return notices
