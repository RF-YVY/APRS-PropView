# APRS PropView v1.11.1

Released: October 14, 2026

## Fixes

- MQTT settings now preserve the saved broker password when the password field is left blank. The field indicates when a password is already saved. Saving unrelated settings no longer erases the credential before the next restart.
- Settings now opens outside the sidebar's clipping and compositing ancestors, above the main screen controls. This addresses the Safari report where the settings header, Close button, and bottom Save controls were hidden.
- Weather HTTPS requests now load the bundled CA certificate store in addition to system roots. This addresses missing issuer certificate errors in Windows desktop builds while preserving hostname and certificate verification.

## Platforms and upgrade

- Windows: replace the portable executable or run `APRSPropViewSetup-1.11.1.exe`. Existing configuration and database formats are unchanged.
- Linux and Raspberry Pi: update the source checkout, rerun `scripts/install_linux.sh`, and restart the service.
- macOS: update the source checkout and rebuild with `build_macos.py` on macOS.
- Docker: pull `ghcr.io/rf-yvy/aprs-propview:1.11.1` after the GitHub publishing workflow completes. Images target Linux amd64 and arm64.

## Validation

- All 159 Python tests pass, including MQTT persistence and weather TLS regressions.
- All application JavaScript modules pass syntax checks.
- A live Open-Meteo request succeeds with certificate verification enabled.
- Windows portable and installer executables were rebuilt for v1.11.1. The portable executable passes startup/version checks, a live weather fetch, and MQTT password persistence through an unrelated settings save and a process restart using an isolated configuration.
- The Safari layout change still requires confirmation on macOS Safari; native macOS and Linux builds were not run on the Windows build host.

## Windows artifact SHA-256 checksums

- `APRSPropView.exe`: `01247C8317141B84036BAC3BA7181E798459B58B8E79F1DAF6F97A620A3726A2`
- `APRSPropViewSetup-1.11.1.exe`: `1FB62EACAEF109D72E27E2793ED9747A84B921B35874927D58046CE3574A53E0`
