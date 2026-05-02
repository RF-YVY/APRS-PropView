# APRS PropView — VHF Propagation Monitor

**Version 1.3.3** | May 2, 2026

A real-time APRS digipeater and IGate application focused on visualizing VHF propagation conditions. Features an interactive web dashboard, advanced analytics, band opening alerts, and full APRS-IS policy compliance. Runs from source or as a single portable `.exe`.

## Features

### Core

- **Digipeater** — WIDEn-N compliant packet digipeating via KISS TNC (serial or TCP)
- **IGate** — Bidirectional RF ↔ APRS-IS gateway with proper q-construct handling and third-party IS→RF forwarding
- **RF Station Tracking** — Separate list of stations heard directly on RF
- **APRS-IS Station Tracking** — Separate list of stations received from APRS-IS
- **Propagation Map** — Interactive Leaflet map with APRS sprite icons (16px markers, 32px in popup), directional arrowed path lines, and light/dark theme toggle
- **Dual Propagation Meters** — Header gauges: "VHF Propagation My Station" (direct-heard RF only) and "Regional VHF Propagation" (all RF including via digipeater), each with configurable scoring thresholds
- **Animated Path Lines** — Dashed propagation lines flow from remote stations toward your position, color-coded by distance (red/orange/green/purple)
- **Callsign Labels** — Toggle persistent callsign labels above each station icon on the map
- **Auto-Fit Zoom** — Automatically zoom the map to fit all visible stations; zooms back in as stations expire; overridden by manual pan/zoom
- **Station Ghosting** — Configurable fade effect (pulsing dashed border) for stations not heard recently
- **Station Expiry** — Automatically remove stations from the map after a configurable "last heard" timeout
- **Mobile Companion** — Touch-optimized `/mobile` page with bottom tab bar for phone browsers (via Tailscale or LAN)
- **Propagation Indicator** — Live gauge showing current VHF band conditions based on station count and distance trends
- **Filters** — Filter stations by last-heard time, distance, and packet type
- **Solar Data Widget** — Live HF propagation summary image (solar flux, K-index, band conditions) from hamqsl.com in the Propagation tab
- **Real-time Updates** — WebSocket-driven live dashboard

### Analytics

- **Longest Path Leaderboard** — Daily ranking of the longest RF paths heard
- **Propagation Heatmap** — Hour-by-hour visualization of propagation activity over time
- **Station Reliability Scoring** — Grade (A–F) for each station based on packet consistency
- **Best Time of Day** — Identify peak propagation windows from historical data

### Alerts

- **Band Opening Detection** — Automatic alerts when propagation thresholds are exceeded
- **Quiet Hours** — Configurable quiet time window (HH:MM 24h) to suppress notifications
- **Message Notifications** — Get notified via Discord/Email/SMS when APRS messages are received
- **Discord Webhooks** — Push notifications to a Discord channel
- **Email (SMTP)** — Email alerts via any SMTP server
- **SMS Gateway** — Text alerts via carrier email-to-SMS gateways

### Weather

- **Current Conditions Banner** - Live weather banner on the map view (temperature, wind, humidity, pressure, feels-like) powered by Open-Meteo
- **US Zip Code & ICAO Location** - Set your weather location by entering a US zip code or ICAO airport code
- **Severe Weather Alerts** - NWS active alerts displayed as color-coded banners (red for warnings, orange for watches/advisories)
- **Configurable Alert Range** - Select how far from your location to monitor severe weather (default 50 miles)
- **NWS Alert Awareness** - Current conditions, animated radar overlays, and NWS alert banners/polygons for weather situational awareness
- **Weather Radar Overlay** - Optional animated radar tiles layered directly on the map with adjustable opacity for fast visual storm tracking
- **NWS Alert Polygons** - Optional map overlay for severe weather polygons, with per-category filters for warnings, watches, flood, winter, marine, fire/heat, and other alerts
- **Adaptive Alert Polling** - Automatically increases alert checks to a 1-minute cadence when selected trigger events, such as Tornado Watch or Severe Thunderstorm Watch, become active
- **Point or County/Zone Scope** - Monitor alerts for your exact station point or switch to a county/forecast-zone UGC target for broader warning coverage
- **Adaptive Refresh Strategy** - Weather condition refresh stays user-configurable while alert polling cadence can increase automatically during elevated severe-weather scenarios

### APRS Messaging

- **Send & Receive** — Two-way APRS messaging with auto-ACK and retry support
- **Click to Reply** — Click any received message to auto-populate the TO callsign for quick reply
- **Message Log** — Filterable message history (All / Sent / Received)
- **RF + IS Routing** — Messages sent on both RF and APRS-IS simultaneously

### Settings & UX

- **Web-based Configuration** — Edit all settings from the browser (saved to `config.toml`)
- **Hot-Reload Settings** — Most settings apply immediately without restarting the server
- **Beacon Path Selector** — Choose digipeater path for beacons (DIRECT, WIDE1-1, WIDE1-1,WIDE2-1, etc.)
- **Minute-based Timers** — All timer settings (beacon interval, dedupe, cleanup, cooldown) displayed in minutes for simplicity
- **Pick Location on Map** — Click the map to set your station coordinates
- **APRS Symbol Picker** — Visual icon chooser with both primary and alternate symbol tables
- **Callsign + SSID Selector** — Uppercase callsign input with SSID dropdown (0–15) and descriptions
- **Miles-based Range Filter** — Enter range in miles; auto-generates APRS-IS `r/` filter
- **Collapsible Sidebar** — Toggle button to collapse/expand the sidebar for a larger map view
- **Persistent Weather Banner** — Weather conditions stay visible on the map unless disabled in settings
- **Font Selector** — Choose from multiple fonts in Settings for crisp, readable text
- **About Tab** — Application version, build info, and attribution
- **Help & User Guide** — In-app help modal covering every feature, control, and setting
- **Update Checker** - Automatically checks the latest GitHub release, supports disabling checks entirely, and lets you control the periodic recheck interval for long-running installs
- **Persistent UI State** — Map toggles, zoom, position, theme, line time filter, station type filters, callsign labels, and auto-fit are saved to the browser and restored on next launch
- **Station Cleanup** — Automatic pruning of stale stations from memory with real-time UI removal

### APRS-IS Policy Compliance

- Lossless APRS packet handling across RF and APRS-IS transports (no UTF-8 re-encoding or trailing-space trimming)
- Proper amateur callsign format validation (rejects N0CALL, NOCALL, etc.)
- Minimum 10-minute beacon interval enforced per APRS-IS usage policy
- Read-only mode: unverified connections (passcode `-1`) cannot transmit or gate
- RF→IS gating does not deduplicate or suppress traffic except for `NOGATE` / `RFONLY`
- IS→RF gated packets do not request further digipeating (no WIDE path)
- IS→RF gated packets use APRS third-party format to avoid loops
- APRS-IS filter token syntax validation
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

### Standalone Executable

```bash
pip install pyinstaller
python build_exe.py
```

This produces `dist/APRSPropView.exe` — a single portable file (~33 MB). On first run it creates `config.toml` next to the exe and launches the browser.

## Configuration

All settings are in `config.toml` and can be edited from the web UI **Settings** tab.

| Section | Purpose |
|---|---|
| `[station]` | Callsign, SSID (0–15), position, symbol, beacon interval, beacon path |
| `[digipeater]` | Enable/disable, WIDEn-N aliases, dedupe window |
| `[igate]` | Enable/disable, RF→IS and IS→RF gating |
| `[aprs_is]` | Server, port, passcode, filter string |
| `[kiss_serial]` | Serial RF TNC port, baud rate, KISS/TNC2 monitor mode, flow control, and optional startup profile |
| `[kiss_tcp]` | TCP KISS TNC host and port |
| `[web]` | Web interface bind address, port, font, ghost time, expire time |
| `[tracking]` | Station age limits and cleanup intervals |
| `[database]` | SQLite database path |
| `[propagation]` | Scoring thresholds for My Station and Regional propagation meters |
| `[alerts]` | Band opening thresholds, Discord/email/SMS notification settings |
| `[weather]` | Weather enabled, location code (zip/ICAO), alert range, radar overlay, alert polygons, alert scope, and adaptive polling |

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

APRS PropView was created by **Brett Wicker** with the assistance of an **AI agent**.

Official project support: [Donate via PayPal](https://www.paypal.com/ncp/payment/2TZHQAECTSDGC)

**Wicker Made, LLC**\
Contact: [madebywicker@gmail.com](mailto:madebywicker@gmail.com)
