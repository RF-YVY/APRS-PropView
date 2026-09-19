# APRS PropView v1.11.0

Released: September 19, 2026

This release expands propagation and weather situational awareness, adds a club-friendly rotating display, and improves compatibility and map workflows across supported platforms.

## Propagation and source awareness

- Added confidence and event-lifecycle context for propagation evidence, including developing, confirmed/peak, and fading phases.
- Added a unified source-health panel for RF, APRS-IS, weather, alerts, lightning, radar, and satellite data.
- Added QTH and watched-location range scopes, APRS weather-mesh comparisons, NOAA space-weather context, and optional PSK Reporter corroboration.
- Added a configurable read-only club display that rotates through map, propagation, weather, and RF-activity scenes.

## Weather and APRS objects

- Added NOAA GOES GLM lightning visualization and remote weather/lightning awareness for watched locations.
- Weather watch and warning polygons no longer intercept map clicks while APRS object placement is active. Alert popups resume after the object location is chosen or placement is cancelled.

## Compatibility

- Restored Raspberry Pi OS/Debian Bullseye compatibility by replacing SQLite's 3.35-only `RETURNING` clause with a portable row lookup after the atomic station UPSERT.
- Windows, Linux, Raspberry Pi, Docker, and macOS continue to use the same configuration and database formats.

## Upgrade notes

- Windows portable users can replace `APRSPropView.exe`. Installer users can run `APRSPropViewSetup-1.11.0.exe`; supported upgrades preserve `config.toml`, `propview.db`, map tiles, and user audio.
- Linux and Raspberry Pi source/service users should pull the release, rerun `scripts/install_linux.sh`, and restart the service.
- Docker users should pull the `1.11.0` or `latest` image after the release workflow completes.
- macOS users can update their source checkout and rebuild the local app bundle with `build_macos.py`.

## Verification

- The Python unit and APRS compliance suites pass.
- JavaScript syntax checks pass for all application modules.
- The concurrent station-count regression and pre-SQLite-3.35 compatibility regression pass.
- Windows portable and installer artifacts were rebuilt from the v1.11.0 source.

## Windows artifact checksums

- `APRSPropView.exe`: `B020CA175FC35233544736D417F56E1B56FFA9FA6ECACCD50506E2ABC1233B20`
- `APRSPropViewSetup-1.11.0.exe`: `A5973630A70E06CBB5DA8B0B84F19EDE3173465A69482BD643A6D5AEA182DDA4`
