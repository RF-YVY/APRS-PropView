# APRS PropView v1.6.1

Released: June 18, 2026

## Highlights

- Added clickable tropospheric ducting details with score factors, points, and measurement context.
- Added local alert-audio test controls and per-alert playback status so operators can confirm browser-side audio before relying on it.
- Added a dashboard-only Node-RED project flow as the default `flows.json`, while keeping the optional Alexa flow available for manual import.
- Added `/api/diagnostics` for quick app, MQTT, weather, alert-audio, and connection status checks without exposing secrets.
- Centralized dashboard asset cache busting through the application version.
- Expanded README, in-app help, full HTML documentation, and Linux/Pi notes for the map **Cache** feature and offline tile behavior.
- Kept the optional Alexa Node-RED flow available at `deploy/node-red/aprs-propview-alexa-dashboard-flow.json`.

## Upgrade Notes

- Windows users can install fresh with `APRSPropViewSetup-1.6.1.exe` or update from the About tab when the setup asset is attached to the GitHub release.
- Linux and Raspberry Pi installs should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the systemd service.
- Node-RED Projects now load a dashboard-only `flows.json` by default. Import the Alexa flow manually only after installing `node-red-contrib-alexa-home`.
- Cached map tiles in `map_tile_cache/`, `config.toml`, `propview.db`, and `user_audio/` are preserved by normal upgrades.

## Verification

- APRS compliance and weather test suite.
- Python syntax checks for release-touched modules.
- JavaScript syntax checks for dashboard modules.
- Node-RED dashboard and Alexa flow JSON validation.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build when Inno Setup is installed.
