# APRS PropView v1.10.0

Released: September 10, 2026

This release adds a zoom-dependent Maidenhead overlay with click-to-select integration for the watched-path builder. A clearly labeled and highlighted Target station / label field now appears immediately below map-selection feedback.

A six-step illustrated Quick Start now opens on the first browser visit. Skip and Close remember dismissal in that browser, and the guide remains available from About/Help and the full Help dialog.

Setup guidance now continues into an actionable checklist, configuration readiness report, Basic/Advanced settings view, and staged operating-mode presets. Clicking the RF, APRS-IS, or WebSocket header status opens diagnostics with direct links to the relevant settings. Empty states also link to their setup steps, common APRS terms have in-app explanations, and the alert panel includes a baseline-to-test setup assistant.

The mobile map now follows the desktop Off/Basic/Enhanced packet-animation setting. Basic motion draws a compact packet trace; Enhanced adds a brighter moving trail and known digipeater hops when their locations are available. A mobile Motion button can pause the effect locally, and reduced-motion preferences disable it.

The About page now uses “Give Thanks” and “Support” wording. Package metadata now matches the repository's Apache-2.0 license.

It also includes the approved code, performance, and usability improvements while keeping the existing access model.

- Direct RF evidence survives subsequent relayed or positionless packets. Historical range, longest paths, heatmaps, and sectors use timestamped observations.
- The longest-path leaderboard now holds out impossible coordinates, contradictory location jumps, and isolated paths of 800 km or more until a nearby reception confirms them. Operators can reveal these entries as clearly marked unconfirmed positions.
- The header notification drawer now opens in a top-level fixed layer and stays readable above the map and side panels at desktop and mobile sizes.
- Browser delivery uses bounded per-client queues, coalesces replaceable updates, and disconnects slow consumers without waiting in packet processing.
- Station and packet lists reuse rows and batch updates; hidden panels defer rendering. Full refreshes are less frequent while the WebSocket is healthy.
- Configurable raw-packet and detailed-history retention defaults to 7 and 30 days, with daily RF summaries and database size reporting.
- Configuration saves persist atomically with a last-known-good backup before applying runtime changes. Imports also use atomic replacement and backup.
- Propagation meters explain evidence, freshness, and baseline readiness. Sporadic-E is explicitly an unconfirmed hypothesis scored from matching observations.
- Shared coordinate/path rules and extracted history analytics/routes reduce duplicated logic. Zero-valued coordinates are accepted.
- Test discovery rejects empty suites; CI runs the tests. The executable builder preserves the dist directory.

## Upgrade notes

- Windows portable users can replace `APRSPropView.exe`. Installer users can run `APRSPropViewSetup-1.10.0.exe`; supported upgrades preserve `config.toml`, `propview.db`, map tiles, and user audio.
- Existing detailed history remains available. Historical rows recorded before reception coordinates were stored cannot provide retroactive position confirmation for the longest-path quality filter.
- Linux and Raspberry Pi source/service users should pull the release, rerun `scripts/install_linux.sh`, and restart the service.

## Verification

- 130 Python unit and APRS compliance tests passed.
- Python bytecode compilation and JavaScript syntax checks passed.
- Desktop and mobile browser checks covered setup guidance, Maidenhead selection, settings navigation, and the top-level notification drawer.
- The packaged Windows executable started with an isolated receive-only configuration.
- Longest-path evidence grading was tested with invalid, conflicting, isolated extreme, and repeated long-distance positions.

## Windows artifact checksums

- `APRSPropView.exe`: `951856C57D3D1827D46CA0C5153BDA9BCAD0D747A892C8193BA0FAE181AB78BF`
- `APRSPropViewSetup-1.10.0.exe`: `F493E5F283109825FDFCE1745DAC75D9C392641071E3F0C13E717DB7934F8286`
