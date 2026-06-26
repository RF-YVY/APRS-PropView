# APRS PropView v1.8.0

Released: June 26, 2026

## Highlights

- Added Docker support with a persistent `/data` directory, health check, Compose file, and app-registry friendly environment overrides.
- Added TrueNAS SCALE custom app reference values, Portainer stack, Unraid template, and a Direwolf TCP KISS Compose example.
- Added GitHub Container Registry publishing workflow with multi-architecture image metadata and a container smoke test before publish.
- Tightened Watched Paths alerts so non-target scoring only uses directly heard stations near the watched target area, reducing false alerts from high-profile digipeaters.
- Kept RF map line behavior conservative: direct stations draw to my station, known digipeater paths draw station-to-digi-to-me, and unknown-position digipeater paths do not draw a misleading line.
- Added popup guidance when a via-digipeater RF station cannot draw a map path because the digipeater has not yet sent a known position.
- Added richer `/api/health?full=true` diagnostics for containers, including runtime paths, uptime, update-check state, and first-run configuration warnings.
- Improved Windows in-app update handoff so the installer starts after the running app has had more time to exit cleanly.
- Added an explicit `Do not open automatically` browser launch option for headless/service deployments.
- Added SQLite indexes for high-volume packet and path-history queries.

## Upgrade Notes

- Windows users can install with `APRSPropViewSetup-1.8.0.exe` or use Install Update from About/Help.
- Portable Windows users can replace the executable with `APRSPropView.exe`.
- Docker users can run `docker compose pull && docker compose up -d` after the image is published.
- TrueNAS SCALE, Portainer, and Unraid users should preserve the `/data` mount during upgrades.
- Linux and Raspberry Pi source/service users should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the service.
- Existing `config.toml`, `propview.db`, cached map tiles, and user audio files are preserved by supported upgrade paths.

## Verification

- Python unit and compliance tests: 110 passed.
- Python bytecode compilation.
- JavaScript syntax checks.
- Docker Compose config validation.
- Docker image build and `/api/health?full=true` smoke test.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.

## Windows Artifact Checksums

- `APRSPropView.exe`: `760879B090BC88D777A8265FA71BEA94E4097AEDE4A5F76A541D14713CA20ED8`
- `APRSPropViewSetup-1.8.0.exe`: `AC6B2E88A7BA8C4B8F61B10C8AEEBAF7790042055F0A7939889602A1DE10C9E6`
