# APRS PropView v1.7.0

Released: June 23, 2026

## Highlights

- Added watched VHF path opportunity alerts using target bearing, distance, observed RF enhancement, confidence, and radio-horizon context.
- Added callsign-assisted target setup using Callook, HamDB, optional QRZ XML, and HamQTH providers, with worldwide grid and coordinate overrides.
- Added antenna height, transmit power, antenna gain, EIRP, and capability adjustments to watched-path scoring.
- Added a station blocklist supporting exact `CALL-SSID` entries or a base `CALL` that blocks every SSID.
- Hardened APRS position parsing so malformed uncompressed coordinates are rejected instead of being plotted as incorrect compressed positions.
- Added watched-path map line visibility control.
- Redesigned Settings as a full-width category workspace with search, deep links, section reset, validation routing, contextual help, and responsive layouts.
- Added persistent pulsing indicators and modified-section counts for unsaved settings.
- Save confirmations now distinguish settings applied immediately, browser refresh requirements, and full application restart requirements.
- Added Buy Me a Coffee support to About/Help and renamed the tab accordingly.

## Upgrade Notes

- Windows users can install with `APRSPropViewSetup-1.7.0.exe` or use Install Update from About/Help.
- Portable Windows users can replace the executable with `APRSPropView.exe`.
- Linux and Raspberry Pi users should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the service.
- macOS source users should pull the repository, update dependencies, and restart the app. The `.app` bundle must be built on macOS.
- Existing `config.toml`, `propview.db`, cached map tiles, and user audio files are preserved by supported upgrade paths.

## Verification

- Python unit and compliance tests: 115 passed.
- Python bytecode compilation.
- JavaScript syntax checks.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.
- Packaged executable smoke test: `/api/version` returned `1.7.0`.

## Windows Artifact Checksums

- `APRSPropView.exe`: `B92455050D54E94D685F56D51FE86B8E183681100911EB559409F04558DABF81`
- `APRSPropViewSetup-1.7.0.exe`: `2B591DA3D4B70CFD9C06BF0B36E4247F490DB6DC2B51ACEA5C5E3B5FB4B0AC90`
