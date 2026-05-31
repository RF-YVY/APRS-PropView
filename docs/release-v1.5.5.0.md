# APRS PropView v1.5.5.0

Released May 31, 2026.

## Highlights

- Added scheduled APRS BLN bulletins and APRS objects with preview, one-shot transmit, RF/APRS-IS routing, and configurable RF paths.
- Added map-created APRS objects from the new `Obj` map control.
- Added optional smart beaconing that changes station beacon interval from GPS speed.
- Improved private/local APRS-IS server receive support, including bannerless or `logresp`-less local feeds. Unverified connections remain read-only.
- Added station-to-station map line style controls for color mode, custom color, weight, opacity, and solid/dashed/dotted patterns.
- Improved bidirectional station line readability by offsetting directional arrows.
- Improved digipeater path visualization so via-digipeater RF packets draw TX-to-digi-to-RX paths when the digipeater position is known.
- Fixed AGWPE raw K-frame payload handling for feeds that include an extra leading TNC byte.
- Updated station filtering/sorting, APRS-IS/RF path display, and in-app help text for the new controls.
- Updated Linux/Raspberry Pi notes for multi-port RF, AGWPE TCP, private APRS-IS feeds, scheduled packets, and smart beaconing.

## Upgrade Notes

- Existing `config.toml` files are preserved. Compare `config.toml.example` if you want to add the new `[smart_beaconing]`, `[bulletins]`, or `[aprs_objects]` sections manually.
- Public APRS-IS behavior remains conservative: transmit and IS-to-RF gating require a verified login.
- For Linux/Pi installs, run the installer again after pulling the release so dependencies and the systemd service are refreshed:

```bash
git pull
sudo bash ./scripts/install_linux.sh
sudo systemctl restart aprs-propview
```

## Verification

- Full pytest suite
- JavaScript syntax checks for all dashboard scripts
- Windows PyInstaller executable build
