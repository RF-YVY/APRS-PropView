# APRS PropView v1.10.1

Released: September 11, 2026

This patch release fixes the Longest Path leaderboard failing to load on upgraded installations.

APRS PropView v1.10.0 began storing reception-time coordinates in path history so analytics could distinguish confirmed paths from isolated or contradictory station positions. Existing history correctly retained its distance data with empty coordinate fields. When a legacy coordinate-less row belonged to a callsign that also had a newer confirmed position cluster, the geographic conflict check attempted to compare the missing coordinates and the analytics endpoint returned an HTTP 500 error.

Version 1.10.1 limits geographic conflict comparisons to observations that have valid coordinates. Legacy rows with usable distances remain available as plausible evidence, while positioned observations continue to receive the same confirmation and conflict checks introduced in v1.10.0.

The problem and fix are server-side; the client operating system, browser, and whether the dashboard is opened locally, over a LAN, or through Tailscale/VPN do not change the behavior.

## Upgrade notes

- Windows portable users can replace `APRSPropView.exe`. Installer users can run `APRSPropViewSetup-1.10.1.exe`; supported upgrades preserve `config.toml`, `propview.db`, map tiles, and user audio.
- Linux and Raspberry Pi source/service users should pull the release, rerun `scripts/install_linux.sh`, and restart the service.
- Docker users should pull the `1.10.1` or `latest` image after the release workflow completes.

## Verification

- All 131 tests in the Python unit and APRS compliance suite pass.
- A regression test covers mixed legacy coordinate-less rows and newer confirmed position clusters.
- Windows portable and installer artifacts were rebuilt from the v1.10.1 source.

## Windows artifact checksums

- `APRSPropView.exe`: `DBA53EB845880E8080F89811F96749E4C50CB8F82C6C9AF1DEDE8D2CFCEA3084`
- `APRSPropViewSetup-1.10.1.exe`: `8522FE5126FB353B53C02FBCFC0432F6DFB738E73E6F232FADA3CA459CE0A60F`
