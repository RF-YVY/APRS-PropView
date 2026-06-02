# APRS PropView v1.5.5.2

Released June 2, 2026.

## Highlights

- Added Packets tab sorting for newest-first or oldest-first display.
- Added a Packets tab filter for packets digipeated by your station, with a DIGI badge.
- Recent packet history now loads into the Packets tab on startup instead of showing only packets received after the browser opened.
- Stale RF map markers are removed when the same moving callsign later appears via APRS-IS at a newer, different position.
- NWS alerts without native polygon geometry can use affected county/zone geometry as a fallback for weather alert overlays.
- Weather alert banners/beacons and map polygons can use separate NWS ranges: radius alert scope controls local banners, while the polygon overlay range can show storms farther out.
- Weather alert distance settings are grouped together so banner range and polygon range are easier to compare.
- Severe weather warning banners now use a subtle five-second pulse until the user clicks the banner.
- Expanded weather alert banners now hide map search/legend controls and scroll when alert text is long.
- Packaged EXE startup now reports port conflicts clearly and keeps the console open for readable fatal errors.

## Upgrade Notes

- Existing config files do not need manual changes.
- The packet database gains a `digipeated_by_me` column automatically on startup.
- Existing packet rows before this release will not be backfilled as digipeated-by-me unless they are received again.
- Browser cache-busters were updated to ensure the dashboard loads the new JavaScript and CSS.

## Verification

- Full unittest suite
- Browser smoke check against the local dashboard
- Live NWS fallback geometry sanity check
- Windows PyInstaller executable build
