# APRS PropView v1.6.0

Released: June 15, 2026

## Highlights

- Added stronger TCP TNC connection handling with disconnect/error state reporting and automatic reconnect behavior.
- Added unified RF, APRS-IS, and WebSocket status pills with connected, retrying, and disconnected visual states.
- Added a header notification drawer for RF TCP errors/reconnect events and incoming APRS messages. Band-opening alerts remain outside the drawer.
- Added propagation-panel DXView link centered on the configured station latitude/longitude.
- Added mobile/Tailscale documentation for safely using the mobile companion outside the home network through a private VPN.
- Added browser launch selection for desktop startup behavior, including blank/system-default behavior for headless or service deployments.
- Hardened GPS NMEA serial/TCP/UDP ingestion for chunked streams used by common GPS tools.
- Fixed map-picked longitude normalization issues.
- Kept callsign handling country-neutral for worldwide users, including Guam-issued callsigns.
- Updated About, quick help, full HTML documentation, README, and platform install notes for v1.6.0.
- Refreshed desktop UI density: compact header, connection status area, toolbar, map legend, and propagation panel layout.

## Upgrade Notes

- Windows users can install fresh with `APRSPropViewSetup-1.6.0.exe` or update from the About tab when the setup asset is attached to the GitHub release.
- Linux and Raspberry Pi installs should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the systemd service.
- macOS users can update source installs directly or rebuild the local unsigned `.app` with `build_macos.py` on macOS.
- For headless Pi/VM deployments, keep `[web].launch_browser` blank if no browser should be opened automatically.
- For remote phone access, use Tailscale/WireGuard/private VPN and open `/mobile` through the VPN instead of forwarding the dashboard to the public internet.

## Verification

- APRS compliance and integration test suite.
- Python syntax checks for release-touched modules.
- JavaScript syntax checks for dashboard modules.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build when Inno Setup is installed.
- macOS app bundle must be built on macOS.
