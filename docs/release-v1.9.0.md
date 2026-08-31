# APRS PropView v1.9.0

Released: August 31, 2026

## Highlights

- Added selectable Off, Basic, and Enhanced live packet-animation modes under Settings - Map & Display.
- Added transmit bursts around station icons whenever a live packet is received.
- Added directional packet movement from a transmitting station toward PropView for direct RF packets.
- Added hop-by-hop animation through positioned digipeaters before the packet reaches PropView.
- Added APRS-IS packet-flow visualization with a distinct visual treatment.
- Enhanced mode adds a bright moving packet head, fading contrail, and a pulse at each reached hop.
- Added bounded animation queues and operating-system reduced-motion support to keep the display responsive and accessible.
- Documented the new visualization controls and persisted the selected animation mode in `config.toml`.

## Upgrade Notes

- Windows users can install with `APRSPropViewSetup-1.9.0.exe` or use Install Update from About/Help.
- Portable Windows users can replace the executable with `APRSPropView.exe`.
- Linux and Raspberry Pi source/service users should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the service.
- Existing `config.toml` files automatically use Basic packet animation unless another mode is selected.
- Existing `propview.db`, cached map tiles, and user audio files are preserved by supported upgrade paths.

## Verification

- Python unit and compliance tests: 123 passed.
- Python bytecode compilation.
- JavaScript syntax checks.
- Live KISS TCP test using valid AX.25 frames through the production packet-ingestion and WebSocket path.
- Visual browser verification of direct RF, positioned digipeater, repeated-packet, and packet-flow animations.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.

## Windows Artifact Checksums

- `APRSPropView.exe`: `7C544C6E80DAC0FF4FD4878F1AA343012EE81BA9DE949236AF353822059F04DA`
- `APRSPropViewSetup-1.9.0.exe`: `60BE92113E112D3C6E9056AD9E316E1CF6D4F7772CF3F8375DB4360EFF7E070D`
