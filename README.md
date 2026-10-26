# Uisce Éireann Water Outages for Home Assistant

Unofficial Home Assistant integration that tracks the water supply notices Uisce Éireann publishes on the [Supply and Service Updates](https://www.water.ie/supply-and-service-updates) map, for one or more locations you choose.

It reads the same public ArcGIS layer the map uses. No account or API key is needed.

## What you get

For each monitored location (default: your Home zone, 5 km radius):

| Entity | What it shows |
|---|---|
| `binary_sensor.water_outages_<name>_outage_nearby` | On while any open notice is within the radius |
| `sensor.water_outages_<name>_open_notices` | Number of open notices; attributes list them nearest first (up to 20) |
| `sensor.water_outages_<name>_nearest_notice` | Distance in km to the nearest open notice |
| `geo_location.*` (source `uisce_eireann`) | One map pin per open notice, created and removed as notices come and go |

Each notice carries: `reference`, `title`, `category` (e.g. "Burst Water Main"), `status`, `county`, `location`, `work_type`, `start`, `end`, `distance_km`, `pins`, `description`.

Two events fire on the HA event bus:

- `uisce_eireann_notice_new` when an open notice appears in range
- `uisce_eireann_notice_cleared` when one closes, is dropped from the feed, or leaves the radius

Both events are detected by polling, so they fire up to one update interval after the feed changes (15 minutes by default). The first poll after a restart or reload fires no events, so existing notices aren't reported as new. Each event carries the notice fields above plus `name` (the name you gave the location) and `config_entry_id`.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository's URL, category **Integration**.
2. Install **Uisce Éireann Water Outages** and restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *Uisce Éireann Water Outages*.
4. Pick a point on the map and drag the circle to set the radius.

Add the integration again for each extra place you care about (work, a relative's house).

**Options:** radius (500 m to 100 km), update interval (5 to 240 min, default 15), and whether closed notices are listed in the attributes. Closed notices never count towards the sensors.

## Example automations

### Notify when a new notice appears

```yaml
alias: Water outage notice near home
triggers:
  - trigger: event
    event_type: uisce_eireann_notice_new
    event_data:
      name: Home
actions:
  - action: notify.mobile_app_phone
    data:
      title: "💧 {{ trigger.event.data.category or 'Water notice' }}"
      message: >
        {{ trigger.event.data.title }} ({{ trigger.event.data.distance_km }} km).
        {{ trigger.event.data.description or 'No description provided.' }}
        Ref {{ trigger.event.data.reference }}.
```

Paste these into Settings → Automations → ⋮ → **Edit in YAML**. If you keep automations in `automations.yaml`, add a `- ` before `alias:` and indent the rest by two spaces.

`event_data: name:` must match the name you gave the location when adding the integration (case and spacing included), or the automation never fires. Remove the `event_data` block to trigger for every monitored location.

To ignore non-disruptive works, add a condition on `trigger.event.data.category`.

### Notify when a notice clears

```yaml
alias: Water outage notice cleared near home
triggers:
  - trigger: event
    event_type: uisce_eireann_notice_cleared
    event_data:
      name: Home
actions:
  - action: notify.mobile_app_phone
    data:
      title: "✅ Water notice cleared"
      message: >
        {{ trigger.event.data.title }} (Ref {{ trigger.event.data.reference }})
        is no longer listed. Closures lag behind the works, so supply may have returned earlier.
```

### Daily summary of the latest notice

The open notices sensor lists up to 20 notices in its `notices` attribute, nearest first. This picks the one with the latest `start`. Adjust the entity ID and notify service to match yours.

```yaml
alias: Latest water notice near home
triggers:
  - trigger: time
    at: "08:00:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.water_outages_home_open_notices
    above: 0
actions:
  - variables:
      latest: >
        {{ state_attr('sensor.water_outages_home_open_notices', 'notices')
           | selectattr('status', 'eq', 'Open')
           | selectattr('start', 'ne', none)
           | sort(attribute='start', reverse=true)
           | first }}
  - action: notify.mobile_app_phone
    data:
      title: "💧 {{ latest.category or 'Water notice' }}"
      message: >
        {{ latest.title }} ({{ latest.distance_km }} km away).
        {{ latest.description or 'No description provided.' }}
        Started {{ as_timestamp(latest.start) | timestamp_custom('%d %b %H:%M') }}.
        Ref {{ latest.reference }}.
```

"Most recent" means most recently published or edited (see the note on start/end below), not when the outage began. Descriptions are shortened to a fixed length with "…".

## How it works, and the data's quirks

- Every poll queries a bounding box around your point, pages through results by object id, and keeps only notices inside the circle.
- **Field names are discovered at runtime.** The feed is undocumented, so the integration reads the layer's field list and matches fields to roles (title, status, reference and so on) by name and alias. If Uisce Éireann renames a field, unmatched roles show as empty and the raw attributes are still kept. Settings → the integration → ⋮ → **Download diagnostics** shows exactly which field was matched to which role.
- **Multiple pins, one event.** Notices sharing a reference number are merged into the nearest pin, and `pins` shows how many there were.
- **Start/end are publication timestamps**, stamped by the feed's software when a notice is posted or edited. They are not the moment supply was lost or restored. Dates before the year 2000 (seen in the feed as typos) are dropped.
- **Closures lag.** Uisce Éireann typically marks notices closed some days after the works finish, so a notice can stay "open" after your water is back. A notice that simply disappears from the feed is treated as cleared.
- If the feed is unreachable, the entities go **unavailable** rather than reporting "no outage".

The data-quality findings above come from the [baz8080/uisce](https://github.com/baz8080/uisce) project, which archives this feed.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```

Tests run against a fake ArcGIS server that pages and filters like the real one.

## Disclaimer

Not affiliated with or endorsed by Uisce Éireann. For anything urgent, check [water.ie](https://www.water.ie) or call 1800 278 278.
