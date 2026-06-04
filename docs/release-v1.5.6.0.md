# APRS PropView v1.5.6.0

Released: June 4, 2026

## Highlights

- Added Windows setup installer builds with Start Menu shortcuts, optional desktop shortcut, and selectable installation directory.
- Added installer-based in-app updates on Windows. The About tab detects setup assets on GitHub releases, downloads the installer, gracefully closes APRS PropView, and launches setup after shutdown so application files can be replaced cleanly.
- Preserved user data during installer upgrades, including `config.toml`, `propview.db`, `map_tile_cache/`, and `user_audio/`.
- Added platform-aware update UX so Linux, Raspberry Pi, and macOS users still see release notices without being offered a Windows-only installer button.
- Added Home Assistant MQTT Discovery, MQTT availability publishing, and automation-friendly MQTT events for first-heard stations and new maximum-distance records.
- Added live MQTT reconnect after saving broker, credential, topic, or discovery changes.
- Added gpsd GPS ingestion for Linux/Pi/mobile deployments.
- Added visible-map tile caching for offline/field map use.
- Added macOS source and local `.app` build documentation.
- Added a Messages setting to receive sibling SSID addressees for the same base callsign, such as `K5YVY-7` while running `K5YVY-1`.

## Upgrade Notes

- Windows users can install fresh with `APRSPropViewSetup-1.5.6.0.exe` or update from the About tab when the setup asset is attached to the GitHub release.
- Installer upgrades replace bundled application files only and leave user settings, database, cached maps, and uploaded audio intact.
- Linux and Raspberry Pi installs should update from source, rerun `scripts/install_linux.sh`, and restart the systemd service.
- macOS users can run from source or build a local unsigned `.app` with `build_macos.py`; public macOS distribution should be signed and notarized.
- Existing MQTT topics continue to work. Enable Home Assistant Discovery from Settings or add the new `[mqtt]` discovery fields to `config.toml`.

## Verification

- Python syntax checks for release-touched modules.
- JavaScript syntax check for the dashboard app bundle.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.
