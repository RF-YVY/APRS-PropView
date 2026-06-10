# APRS PropView — VHF Propagation Monitor

**Version 1.5.7.0** | June 5, 2026

[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/RF-YVY/APRS-PropView/total)
![GitHub Tag](https://img.shields.io/github/v/tag/RF-YVY/APRS-PropView)
![GitHub Release Date](https://img.shields.io/github/release-date/RF-YVY/APRS-PropView?display_date=published_at&style=plastic)
![YouTube Channel Views](https://img.shields.io/youtube/channel/views/UC0qq--bOgSHn442vvenO0xg)



<li style="display: inline-block; margin-right: 0.25rem;"><a href="https://www.buymeacoffee.com/k5yvy"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" width="150"/></a></li>

*Thanks to Contributions and Suggestions from many that emailed or submitted issues.*

*Special thanks to Kyle (galaxie67w) and Joe M. for many suggestions and bug finds.*

<img width="1536" height="1024" alt="APRS PropView promo img" src="https://github.com/user-attachments/assets/9942c9df-1599-485c-80a2-4f475c9ff2ae" />


A real-time APRS digipeater and IGate application focused on visualizing VHF propagation conditions. Features an interactive web dashboard, advanced analytics, band opening alerts, and full APRS-IS policy compliance. Runs from source or as a single portable `.exe`.

Version 1.5.7.0 expands Home Assistant MQTT Discovery with binary status sensors and watched callsign entities, adds a retained MQTT status snapshot feed, improves Sporadic-E diagnostics, adds a station-symbol size control, adds a full weather analytics dashboard, and hardens first-heard station tracking so duplicate or cleaned-up stations are not announced repeatedly.

Linux and Raspberry Pi installs are covered in [docs/linux-raspberry-pi.md](docs/linux-raspberry-pi.md).

## Features

### Core

- **Digipeater** — WIDEn-N compliant packet digipeating via KISS TNC (serial or TCP)
- **IGate** — Bidirectional RF ↔ APRS-IS gateway with proper q-construct handling and third-party IS→RF forwarding
- **RF Station Tracking** — Separate list of stations heard directly on RF
- **APRS-IS Station Tracking** — Separate list of stations received from APRS-IS
- **Propagation Map** — Interactive Leaflet map with APRS sprite icons, adjustable marker size, directional arrowed path lines, map-created APRS objects, and light/dark theme toggle
- **Custom/Offline Map Tiles** — Point the map at a local XYZ tile server or cache the visible map area for offline/field use
- **Dual Propagation Meters** — Header gauges: "VHF Propagation My Station" (direct-heard RF only) and "Regional VHF Propagation" (all RF including via digipeater), each with configurable scoring thresholds
- **Configurable Path Lines** — Directional station-to-station lines support distance or custom coloring, weight, opacity, solid/dashed/dotted patterns, and offset arrows for bidirectional paths
- **Digipeater-Routed Lines** — RF stations heard through known digipeaters draw TX-to-digi-to-RX paths instead of misleading direct-heard lines
- **Moving Station Cleanup** — If APRS-IS later reports the same moving callsign at a newer different position, the stale RF marker and path line are removed from the map
- **Callsign Labels** — Toggle persistent callsign labels above each station icon on the map
- **Map Callsign Search** — Expandable/collapsible map search box with Enter-to-jump and Esc-to-collapse keyboard handling
- **Auto-Fit Zoom** — Automatically zoom the map to fit all visible stations; zooms back in as stations expire; overridden by manual pan/zoom
- **Station Ghosting** — Configurable fade effect (pulsing dashed border) for stations not heard recently
- **Station Expiry** — Automatically remove stations from the map after a configurable "last heard" timeout
- **Mobile Companion** — Touch-optimized `/mobile` page with bottom tab bar for phone browsers (via Tailscale or LAN)
- **Propagation Indicator** — Live gauge showing current VHF band conditions based on station count and distance trends
- **Filters** — Filter stations by last-heard time, distance, packet type, callsign, source, and direct/via-digipeater RF path
- **Solar Data Widget** — Live HF propagation summary image (solar flux, K-index, band conditions) from hamqsl.com in the Propagation tab
- **Real-time Updates** — WebSocket-driven live dashboard

### Analytics

- **Longest Path Leaderboard** — Daily ranking of the longest RF paths heard
- **Propagation Heatmap** — Hour-by-hour visualization of propagation activity over time
- **Station Reliability Scoring** — Grade (A–F) for each station based on packet consistency
- **Best Time of Day** — Identify peak propagation windows from historical data
- **Sporadic-E Diagnostics** — Select 6-hour, 24-hour, or 7-day analysis windows and see RF station counts, strongest stations, qualifying-distance counts, near misses, and path-quality weighting details
- **Weather Analytics Dashboard** — Pop-out dashboard for current weather, gauges, history, records, forecast, and map context

### Alerts

- **Band Opening Detection** — Automatic alerts when propagation thresholds are exceeded
- **Alert Tuning Helper** — Analyze recent RF path history and recommend more selective band-opening thresholds from your local baseline
- **Status/DX Reports** — Optional compact APRS status beacons with the best direct DX station, bearing, counts, and propagation level
- **Dynamic, MHeard, and Weather Alert Beacons** — Rotate preset status messages, beacon direct-heard RF stations, or beacon severe weather alert text with preview-before-transmit controls
- **Scheduled Bulletins and APRS Objects** — Periodically transmit configured BLN bulletins and APRS objects over RF, APRS-IS, or both, with preview and one-shot transmit controls
- **Alert Destination Tests** — Send preformatted test messages to selected Discord, Email, and SMS destinations from Settings
- **Quiet Hours** — Configurable quiet time window (HH:MM 24h) to suppress notifications
- **Message Notifications** — Get notified via Discord/Email/SMS when APRS messages are received
- **MQTT Publishing** — Publish retained propagation metrics, score/level topics, Home Assistant Discovery sensors and binary sensors, watched callsign entities, status snapshots, typed automation events, and alert events to brokers such as Mosquitto, Home Assistant, Node-RED, or EMQX
- **Discord Webhooks** — Push notifications to a Discord channel
- **Email (SMTP)** — Email alerts via any SMTP server
- **SMS Gateway** — Text alerts via carrier email-to-SMS gateways

### Weather

- **Current Conditions Banner** - Live weather banner on the map view (temperature, wind, humidity, pressure, feels-like) powered by Open-Meteo
- **WXnow.txt Transmit** - Beacon APRS weather packets from a local `WXnow.txt` file, with weather SSID, RF/APRS-IS routing, optional position, and stale-file cutoff
- **WXnow Condition Fallback** - Use local WXnow measurements while still querying Open-Meteo for general condition text/icon
- **APRS Weather Station Popups** - Decode and show human-readable APRS weather station data, including non-timestamped position weather packets
- **Metric/Imperial Weather Display** - Switch map weather and APRS WX station displays between °F/mph/in and °C/m/s/mm
- **US Zip Code & ICAO Location** - Set your weather location by entering a US zip code or worldwide ICAO airport code
- **Severe Weather Alerts** - NWS active alerts displayed as color-coded banners (red for warnings, orange for watches/advisories)
- **Configurable Alert Range** - Select how far from your location to monitor severe weather banners/beacons in radius mode (default 40 miles)
- **NWS Alert Awareness** - Current conditions, animated radar overlays, and NWS alert banners/polygons for weather situational awareness
- **Weather Radar Overlay** - Optional animated radar tiles layered directly on the map with adjustable opacity for fast visual storm tracking
- **NWS Alert Polygons** - Optional US map overlay for severe weather polygons, with an independent map-only radius (default 80 miles) and per-category filters for warnings, watches, flood, winter, marine, fire/heat, and other alerts
- **NWS Zone Geometry Fallback** - Watches or zone-based alerts without native polygons can draw affected county/zone geometry when available
- **Adaptive Alert Polling** - Automatically increases alert checks to a 1-minute cadence when selected trigger events, such as Tornado Watch or Severe Thunderstorm Watch, become active
- **Point or County/Zone Scope** - Monitor alerts for your exact station point or switch to a county/forecast-zone UGC target for broader warning coverage
- **Adaptive Refresh Strategy** - Weather condition refresh stays user-configurable while alert polling cadence can increase automatically during elevated severe-weather scenarios

### APRS Messaging

- **Send & Receive** — Two-way APRS messaging with auto-ACK and retry support
- **Click to Reply** — Click any received message to auto-populate the TO callsign for quick reply
- **Message Log** — Filterable message history (All / Sent / Received)
- **Message Sort Order** — Switch messages between newest-first and oldest-first ordering
- **Sibling SSID Inbox Option** — Optionally receive messages addressed to the same base callsign with another SSID, such as `K5YVY-7` while running `K5YVY-1`
- **Packet Sort and Digipeat Filter** — The Packets tab loads recent packet history, sorts newest or oldest first, and can show packets your station digipeated
- **Mobile Message Refresh** — Mobile UI includes a manual message refresh button and closer parity with desktop message behavior
- **RF + IS Routing** — Messages sent on both RF and APRS-IS simultaneously

### Settings & UX

- **Web-based Configuration** — Edit all settings from the browser (saved to `config.toml`)
- **First-Run Checklist** — Guided setup reminders for callsign, location, APRS-IS passcode/filter, RF port, beacon path, save, and test transmit
- **Settings Import/Export** — Back up or restore `config.toml` before experimenting with RF, APRS-IS, host, or port settings
- **Hot-Reload Settings** — Most settings apply immediately without restarting the server
- **Preview and Transmit Now** — Preview station, WXnow, status, MHeard, dynamic, and weather-alert beacon text before one-shot transmit
- **Last Transmitted History** — Settings panel shows recent station, WXnow, status, MHeard, and weather-alert transmissions
- **Beacon Path Selector** — Choose digipeater path for beacons (DIRECT, WIDE1-1, WIDE1-1,WIDE2-1, etc.)
- **Minute-based Timers** — All timer settings (beacon interval, dedupe, cleanup, cooldown) displayed in minutes for simplicity
- **Pick Location on Map** — Click the map to set your station coordinates
- **GPS Ingestion** — Use browser/mobile GPS, own APRS position packets, NMEA serial/TCP/UDP streams, or gpsd to move the map marker or update station coordinates
- **Smart Beaconing** — Optional GPS-speed-aware station beacon intervals for mobile/portable use
- **Map Object Creation** — Drop APRS objects from the map, choose symbol/comment/routing, and save them into the scheduled object list
- **APRS Symbol Picker** — Visual icon chooser with both primary and alternate symbol tables
- **Callsign + SSID Selector** — Uppercase callsign input with SSID dropdown (0–15) and descriptions
- **APRS-IS Filter Helpers** — Generate fixed `r/35/-79/80` or `r/35.5/-79.8/80` range filters, or moving/mobile `m/80` filters, with support for additional javAPRS filter tokens
- **Metric System Option** — General unit preference controls distances, weather temperature, wind, and precipitation displays
- **Collapsible Sidebar** — Toggle button to collapse/expand the sidebar for a larger map view
- **Persistent Weather Banner** — Weather conditions stay visible on the map unless disabled in settings
- **Font Selector** — Choose from multiple fonts in Settings for crisp, readable text
- **About Tab** — Application version, build info, and attribution
- **Help & User Guide** — In-app help modal covering every feature, control, and setting
- **Installer-Based Updates** - Windows setup installs can detect GitHub setup assets, download the newer installer from the About tab, close APRS PropView cleanly, and launch setup while keeping user settings and data intact
- **Update Checker** - Automatically checks the latest GitHub release, supports disabling checks entirely, hides Windows-only installer actions on Linux/macOS, and lets you control the periodic recheck interval for long-running installs
- **Persistent UI State** — Map toggles, zoom, position, theme, line time filter, station type filters, callsign labels, and auto-fit are saved to the browser and restored on next launch
- **Linux/Pi Friendly Configuration** — Example config and install guide include multi-port RF, AGWPE TCP, private APRS-IS feeds, scheduled packets, and smart beaconing notes
- **Station Cleanup** — Automatic pruning of stale stations from memory with real-time UI removal

### APRS-IS Policy Compliance

- Lossless APRS packet handling across RF and APRS-IS transports (no UTF-8 re-encoding or trailing-space trimming)
- Country-neutral callsign handling with APRS-safe character checks and APRS-IS placeholder protection
- Minimum 10-minute beacon interval enforced per APRS-IS usage policy
- Read-only mode: unverified connections (passcode `-1`) cannot transmit or gate
- Private/local APRS-IS-style servers that omit banners or `logresp` can still feed received packets; without verification the connection remains read-only
- RF→IS gating does not deduplicate or suppress traffic except for `NOGATE` / `RFONLY`
- IS→RF gated packets do not request further digipeating (no WIDE path)
- IS→RF gated packets use APRS third-party format to avoid loops
- APRS-IS filter token syntax validation
- APRS-IS range filter guidance for fixed and mobile clients
- Policy guidance displayed in the settings UI

### Security

- Input validation and TOML injection prevention
- XSS-safe HTML escaping on all user-supplied data
- CORS middleware with configurable origins
- Passcode masked in API responses
- WebSocket connection limits (max 20)
- Error messages sanitized (no internal paths or stack traces exposed)

## Requirements

- Python 3.11+
- A KISS TNC (serial or TCP) connected to a VHF radio for RF *(optional — APRS-IS–only mode works without a TNC)*
- An APRS-IS account (callsign + passcode) for internet connectivity

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run (config.toml is created automatically on first launch)
python main.py
```

The web interface opens automatically at `http://localhost:14501`.

### Run From Source On macOS

Install Python 3.11 or newer, then run APRS PropView from a terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The web interface opens at `http://localhost:14501`. Serial TNC/GPS devices on
macOS usually appear as `/dev/cu.usbserial-*`, `/dev/cu.usbmodem-*`, or similar
paths rather than Windows-style `COM` ports. If a USB serial adapter does not
appear, install the vendor's macOS driver and grant any requested permissions.

### Standalone Executable

```bash
pip install pyinstaller
python build_exe.py
```

This produces `dist/APRSPropView.exe` — a single portable file (~33 MB). On first run it creates `config.toml` next to the exe and launches the browser.

### Windows Setup Installer

Install Inno Setup 6, then build a versioned setup executable:

```bash
winget install JRSoftware.InnoSetup
python build_installer.py
```

This produces `dist/APRSPropViewSetup-<version>.exe`. The installer defaults
to a per-user install under `%LOCALAPPDATA%\Programs\APRS PropView`, lets users
choose a different install folder, creates Start Menu shortcuts, and installs
the current `APRSPropView.exe`.

Installer upgrades replace the application executable and bundled files only.
User data such as `config.toml`, `propview.db`, `map_tile_cache/`, and
`user_audio/` is left in place. Publish both `APRSPropView.exe` and the setup
asset on GitHub releases; assets named like `APRSPropViewSetup-1.5.7.0.exe` are
detected by the in-app update checker so users can click **Install Update** in
the About tab. On Linux, Raspberry Pi, and macOS, users still see release
notices but installer-based update buttons are hidden because those platforms
update from source or platform-specific builds.

### macOS App Bundle

Build the local test `.app` bundle on a macOS machine:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller pillow
python build_macos.py
```

This produces `dist/APRS PropView.app`. On first launch, the app stores
`config.toml`, `propview.db`, `map_tile_cache/`, and `user_audio/` in:

```text
~/Library/Application Support/APRS PropView/
```

The local `.app` build is unsigned unless you set `MACOS_CODESIGN_IDENTITY`
before running `build_macos.py`. Unsigned builds are suitable for local testing,
but public macOS releases should be code-signed and notarized.

## Configuration

All settings are in `config.toml` and can be edited from the web UI **Settings** tab.

| Section | Purpose |
|---|---|
| `[station]` | Callsign, SSID (0–15), position, symbol, beacon interval, beacon path |
| `[digipeater]` | Enable/disable, WIDEn-N aliases, dedupe window |
| `[igate]` | Enable/disable, RF→IS and IS→RF gating |
| `[aprs_is]` | Server, port, passcode, filter string |
| `[kiss_serial]` / `[kiss_tcp]` | Legacy single-port settings kept for older config files |
| `[[rf_ports]]` | Named multi-port RF setup for serial KISS/TNC2 monitor and TCP KISS ports; preferred for all new setups |
| `[web]` | Web interface bind address, port, font, custom map tile source, ghost time, expire time |
| `[tracking]` | Station age limits and cleanup intervals |
| `[messaging]` | APRS message history retention and sibling-SSID inbox behavior |
| `[database]` | SQLite database path |
| `[propagation]` | Scoring thresholds for My Station and Regional propagation meters |
| `[status]` | Compact APRS status beacon settings: DX summaries, dynamic preset text, direct-RF MHeard summaries, and optional severe weather alert beacons |
| `[smart_beaconing]` | Optional GPS-speed-aware station beacon intervals for mobile operation |
| `[bulletins]` | Scheduled APRS BLN bulletin packets, route, interval, and message list |
| `[aprs_objects]` | Scheduled APRS object packets, route, interval, symbols, positions, and comments |
| `[alerts]` | Band opening thresholds, Discord/email/SMS notification settings |
| `[weather]` | Weather enabled, location code (zip/ICAO), WXnow/Open-Meteo current-condition options, banner alert range, radar overlay, map-only alert polygon range, alert scope, and adaptive polling |
| `[wxnow]` | APRS weather transmit from `WXnow.txt`, including SSID, beacon interval, stale cutoff, position mode, path, and RF/APRS-IS route |
| `[gps]` | Browser, own-packet, serial, TCP, UDP, and gpsd GPS ingestion |
| `[mqtt]` | Optional broker settings for propagation, Home Assistant Discovery, watched callsigns, retained status snapshots, automation events, and alert publishing |

### Offline Map Tiles

APRS PropView uses standard Leaflet XYZ tiles. For grid-down or field setups,
run a local tile server and point the web map at it:

```toml
[web]
map_tile_source = "custom"
map_tile_url = "http://127.0.0.1:8080/tile/{z}/{x}/{y}.png"
map_tile_attribution = "OpenStreetMap contributors"
map_tile_max_zoom = 14
```

The local server can be backed by downloaded OpenStreetMap data or a prepared
tile archive. Keep the max zoom realistic for the area you cache; zoom levels
above 14 grow quickly.

The map's **Cache** control downloads the currently visible base-map tiles at
the current zoom into `map_tile_cache/`. Cached tiles are served by APRS
PropView itself, so already-cached areas remain visible later without internet
access.

### Receiver Feed Roadmap

ADS-B/dump1090 and AIS receiver overlays are planned integration targets. A
useful implementation should ingest local receiver feeds, normalize aircraft
and vessel positions into dedicated map layers, expire stale targets, and keep
them visually distinct from APRS stations. They are not APRS packets, so they
should be added as separate situational-awareness layers instead of mixed into
RF/APRS-IS station history.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  KISS TNC   │────▶│              │────▶│  APRS-IS    │
│  (RF)       │◀────│ PacketHandler│◀────│  Server     │
└─────────────┘     │              │     └─────────────┘
                    │  Digipeater  │
                    │  IGate       │
                    │  Tracker     │
                    │  Analytics   │
                    │  Alerts      │
                    └──────┬───────┘
                           │ WebSocket + REST API
                    ┌──────▼───────┐
                    │  Web Browser │
                    │  Map + Lists │
                    │  Analytics   │
                    │  Settings    │
                    └──────────────┘
```

## Project Structure

```
aprs-propview/
├── main.py                 # Entry point
├── build_exe.py            # PyInstaller build script
├── config.toml.example     # Example configuration
├── requirements.txt        # Python dependencies
├── server/
│   ├── app.py              # FastAPI routes & validation
│   ├── aprs_is.py          # APRS-IS TCP client
│   ├── aprs_parser.py      # APRS packet parser
│   ├── ax25.py             # AX.25 frame encode/decode
│   ├── config.py           # TOML config dataclasses
│   ├── database.py         # SQLite via aiosqlite
│   ├── digipeater.py       # WIDEn-N digipeater
│   ├── igate.py            # RF ↔ APRS-IS gateway
│   ├── kiss.py             # KISS protocol plus legacy TNC2 monitor serial support
│   ├── packet_handler.py   # Central packet router
│   ├── scheduled_packets.py # Scheduled BLN bulletin and APRS object transmitter
│   ├── station_tracker.py  # Station tracking & propagation
│   ├── analytics.py        # Analytics engine
│   ├── alerts.py           # Band opening alert manager
│   ├── weather.py          # Open-Meteo + NWS weather provider
│   └── websocket_manager.py
└── static/
    ├── index.html           # Single-page dashboard
    ├── mobile.html          # Mobile companion SPA
    ├── css/style.css
    └── js/
        ├── app.js           # Main UI logic
        ├── map.js           # Leaflet map
        ├── stations.js      # Station list management
        ├── icons.js         # APRS symbol → emoji mapping
        ├── analytics.js     # Analytics charts & tables
        ├── messages.js      # APRS messaging UI
        ├── weather.js       # Weather banner & alerts
        └── websocket.js     # WebSocket client
```

## Support

If APRS PropView is useful to you, you can support continued development through
the official donation link:

- [Donate via PayPal](https://www.paypal.com/ncp/payment/2TZHQAECTSDGC)

## License

This project is licensed under the Apache License, Version 2.0. See
[LICENSE](LICENSE), [NOTICE](NOTICE), and [TRADEMARKS.md](TRADEMARKS.md).

## About

APRS PropView was created by **Brett Wicker - K5YVY** with the assistance of an **AI agent**.

Official project support: [Donate via PayPal](https://www.paypal.com/ncp/payment/2TZHQAECTSDGC)

**Wicker Made, LLC**\
Contact: [madebywicker@gmail.com](mailto:madebywicker@gmail.com)
