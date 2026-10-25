"""Constants for the Uisce Éireann Water Outages integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "uisce_eireann"

# Public ArcGIS layer behind the "Supply and Service Updates" map on water.ie.
LAYER_URL: Final = (
    "https://services2.arcgis.com/OqejhVam51LdtxGa/arcgis/rest/services/"
    "WaterAdvisoryCR021_DeptView/FeatureServer/0"
)

ATTRIBUTION: Final = "Data provided by Uisce Éireann (unofficial integration)"
MANUFACTURER: Final = "Uisce Éireann (unofficial)"

CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_LOCATION: Final = "location"
CONF_RADIUS: Final = "radius"  # metres
CONF_SCAN_INTERVAL: Final = "scan_interval"  # minutes
CONF_INCLUDE_CLOSED: Final = "include_closed"

DEFAULT_NAME: Final = "Home"
DEFAULT_RADIUS: Final = 5000
MIN_RADIUS: Final = 500
MAX_RADIUS: Final = 100_000
DEFAULT_SCAN_INTERVAL: Final = 15
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 240
DEFAULT_INCLUDE_CLOSED: Final = False

# Events fired on the HA bus (not on the first refresh after start-up).
EVENT_NOTICE_NEW: Final = f"{DOMAIN}_notice_new"
EVENT_NOTICE_CLEARED: Final = f"{DOMAIN}_notice_cleared"

# Keep state attributes well under the recorder's 16 KB limit.
MAX_NOTICES_IN_ATTRIBUTES: Final = 20
MAX_DESCRIPTION_LENGTH: Final = 300

GEO_SOURCE: Final = DOMAIN
