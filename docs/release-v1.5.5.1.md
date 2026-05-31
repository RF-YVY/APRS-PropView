# APRS PropView v1.5.5.1

Released May 31, 2026.

## Highlights

- Added the Band Opening Alert Tuning Helper in Settings.
- The helper analyzes recent RF path history as rolling one-hour windows over the last 24 hours.
- Recommendations include direct station count, direct max distance, regional station count, regional max distance, and alert cooldown.
- Suggested station thresholds are placed above the recent 90th percentile so normal baseline traffic is less likely to trigger routine alerts.
- Suggestions can be applied to the settings form, then saved normally by the user.

## Upgrade Notes

- This is a follow-up release to v1.5.5.0. Existing config files do not need any manual changes.
- The helper needs RF path history to be useful. For best results, let the app collect at least 24 hours of normal traffic before applying suggestions.
- Public APRS-IS behavior remains unchanged: transmit and IS-to-RF gating require a verified login.

## Verification

- Full pytest suite
- JavaScript syntax checks for all dashboard scripts
- Windows PyInstaller executable build
