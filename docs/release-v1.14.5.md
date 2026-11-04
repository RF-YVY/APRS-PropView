# APRS PropView release notes

## v1.14.5 — reliability and security hardening

Released: November 4, 2026.

Thanks to @denmojo for the fixes and documentation contributed in PRs #31–#38.

- Corrected APRS callsign/path validation, limited digipeating to UI frames and eight path addresses, and carried rounded position minutes into degrees correctly.
- Improved APRS-IS startup and recovery after configuration changes, clean disconnects and dead connections, with reconnect backoff.
- Moved first-heard alert delivery and threshold recommendations off the packet-processing path.
- Improved unattended operation by ignoring unknown configuration keys, retrying failed NWS zone lookups and bounding station cleanup settings.
- Hardened per-address login throttling and public WebSocket allocation, and restricted tile-proxy zoom to the selected source.
- Added a Content-Security-Policy that forbids inline scripts, with external desktop/mobile theme and application scripts.
- Fixed the external TNC status counting an unused built-in modem as a disconnected port.
- Fixed callsign lookups for names matching JavaScript prototype properties, and closed Connection Diagnostics when opening Settings.
- Updated deployment guidance for trusted proxies, CSP, public limits and configuration ranges. Rebuilt platform packages as version 1.14.5.
