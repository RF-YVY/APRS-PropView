# APRS PropView v1.5.7.0

Released: June 5, 2026

## Highlights

- Expanded Home Assistant MQTT Discovery with binary sensors for APRS-IS/RF connectivity, band openings, Sporadic-E possibility, message waiting, weather warning state, and interface-down alerts.
- Added retained MQTT status snapshots on `aprs/propview/ha/status` so Home Assistant and Node-RED can track station counts, packet age, connectivity, alerts, and message state without scraping the web UI.
- Added watched callsign MQTT support. Configure callsigns in Settings or `[mqtt].watched_callsigns`; PropView publishes retained presence, last-heard, distance, path, and comment state for each watched station.
- Added typed MQTT event topics such as `aprs/propview/event/message_received` while keeping the existing aggregate event topics for compatibility.
- Improved Sporadic-E analytics with selectable 6-hour, 24-hour, and 7-day windows, RF station diagnostics, strongest analyzed stations, qualifying-distance counts, candidate score gates, and near-miss reporting.
- Added a station-symbol size control to the map toolbar and persisted the choice in browser UI state.
- Added a richer weather analytics dashboard with current conditions, gauges, records, charts, forecast tiles, and map context.
- Added an X button to each severe weather alert banner so users can clear individual alerts from the current view.
- Hardened Windows setup upgrades by stopping a still-running `APRSPropView.exe` before file replacement to avoid access-denied installer updates.
- Refreshed dashboard static asset cache keys so overwritten same-version installers load the new weather dashboard and station symbol-size controls.
- Hardened first-heard logging so each station/source pair is logged once, survives station cleanup, and does not repeatedly trigger first-heard announcements.
- Polished map callsign search with collapsed default state, Enter-to-search, and Esc/collapse handling.

## Upgrade Notes

- Windows users can install fresh with `APRSPropViewSetup-1.5.7.0.exe` or update from the About tab when the setup asset is attached to the GitHub release.
- Linux and Raspberry Pi installs should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the systemd service.
- macOS users can update source installs directly or rebuild the local unsigned `.app` with `build_macos.py`.
- Existing MQTT topics remain available. Home Assistant users should keep the same MQTT Device ID, enable Discovery, and allow the new binary sensors and watched callsign entities to appear.
- Existing databases are migrated automatically to deduplicate `first_heard_log` by callsign/source before creating the new uniqueness index.

## Verification

- APRS compliance and integration test suite.
- Python syntax checks for release-touched modules.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.
