# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- README section on showing the notice pins on a dashboard with a Map card.
- This changelog, and a tagged-release workflow that publishes GitHub releases from it.

## [0.1.0]

First version, as it stood before releases were tracked.

### Added

- Tracks open Uisce Éireann supply notices within a chosen radius (500 m to 100 km) of one or more locations.
- `binary_sensor` for an outage nearby, plus sensors for the number of open notices and the distance to the nearest one.
- One `geo_location` pin per open notice.
- `uisce_eireann_notice_new` and `uisce_eireann_notice_cleared` events for automations.
- Configurable update interval (5 to 240 minutes, default 15) and an option to list closed notices.
- Example automations in the README.

[Unreleased]: https://github.com/foehammer/ha-uisce-eireann/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/foehammer/ha-uisce-eireann/releases/tag/v0.1.0
