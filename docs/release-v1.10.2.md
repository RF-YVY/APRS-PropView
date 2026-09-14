# APRS PropView v1.10.2

Released: September 14, 2026

This release makes advanced station setup clearer and safer, especially for configurations that combine digipeating, one-way IGating, APRS-IS, station beaconing, and multiple hardware or location sources.

## Settings and operating modes

- The Operating Mode Preset selector now shows **Custom configuration** whenever the current form does not exactly match a built-in preset. It remains a preset staging control rather than an inaccurate description of a manually configured station.
- A contextual **Complete This Setup** guide summarizes the saved or staged topology and links directly to the relevant TNC/port, APRS-IS, IGate, digipeater, GPS-source, and station-beacon controls.
- Applying a preset continues to stage changes for review; it does not save or activate them automatically.

## Transmit safeguards and backups

- Saving settings that newly enable transmit-capable functions now presents a final review of the exact capabilities being enabled.
- **Protect transmit settings** can block those saves until deliberately unlocked and is located with **Settings Backup** in Overview.
- The setup guide can reload the last saved configuration, and backup guidance directs users to the existing **Export Settings** action before experimenting.

## APRS Objects

- APRS Objects now presents a prominent **Create Object on Map** action that closes Settings and starts map placement with the guided object editor.
- The saved-object text field is labeled for reviewing, modifying, or removing existing records. The raw pipe-delimited schema is no longer presented as the normal creation workflow.

## Upgrade notes

- Windows portable users can replace `APRSPropView.exe`. Installer users can run `APRSPropViewSetup-1.10.2.exe`; supported upgrades preserve `config.toml`, `propview.db`, map tiles, and user audio.
- Linux and Raspberry Pi source/service users should pull the release, rerun `scripts/install_linux.sh`, and restart the service.
- Docker users should pull the `1.10.2` or `latest` image after the release workflow completes.

## Verification

- All 137 tests in the Python unit and APRS compliance suite pass.
- JavaScript syntax checks pass for the changed application modules.
- The Settings and APRS Objects workflows were visually and interactively checked in the local live preview.
- Windows portable and installer artifacts were rebuilt from the v1.10.2 source.

## Windows artifact checksums

- `APRSPropView.exe`: `1F64B46F2A257674776CB7EFAE71E7C5BC407F3CB5BFD1F0DC8BE31AF2B17F55`
- `APRSPropViewSetup-1.10.2.exe`: `6C016372BE442CC349627B597C086669C1DFF74F2EA9259C7DE00AFBC0D0A440`
