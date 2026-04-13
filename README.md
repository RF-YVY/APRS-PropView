# APRS PropView — VHF Propagation Monitor

A real-time APRS digipeater and IGate application focused on visualizing VHF propagation conditions. Features an interactive web dashboard, advanced analytics, band opening alerts, and full APRS-IS policy compliance. Runs from source or as a single portable `.exe`.

## Features

### Core

- **Digipeater** — WIDEn-N compliant packet digipeating via KISS TNC (serial or TCP)
- **IGate** — Bidirectional RF ↔ APRS-IS gateway with proper q-construct handling
- **RF Station Tracking** — Separate list of stations heard directly on RF
- **APRS-IS Station Tracking** — Separate list of stations received from APRS-IS
- **Propagation Map** — Interactive Leaflet map with APRS emoji icons, connecting polylines, and light/dark theme toggle
- **Propagation Indicator** — Live gauge showing current VHF band conditions based on station count and distance trends
- **Filters** — Filter stations by last-heard time, distance, and packet type
- **Real-time Updates** — WebSocket-driven live dashboard

### Analytics

- **Longest Path Leaderboard** — Daily ranking of the longest RF paths heard
- **Propagation Heatmap** — Hour-by-hour visualization of propagation activity over time
- **Station Reliability Scoring** — Grade (A–F) for each station based on packet consistency
- **Best Time of Day** — Identify peak propagation windows from historical data

### Alerts

- **Band Opening Detection** — Automatic alerts when propagation thresholds are exceeded
- **Discord Webhooks** — Push notifications to a Discord channel
- **Email (SMTP)** — Email alerts via any SMTP server
- **SMS Gateway** — Text alerts via carrier email-to-SMS gateways

### Weather

- **Current Conditions Banner** — Live weather banner on the map view (temperature, wind, humidity, pressure, feels-like) powered by Open-Meteo
- **US Zip Code & ICAO Location** — Set your weather location by entering a US zip code or ICAO airport code
- **Severe Weather Alerts** — NWS active alerts displayed as color-coded banners (red for warnings, orange for watches/advisories)
- **Configurable Alert Range** — Select how far from your location to monitor severe weather (default 50 miles)
- **Lightning Detection** — Thunderstorm indicators via WMO weather codes and NWS alert keyword scanning
- **Auto-Refresh** — Configurable refresh interval (default 15 min) with 5-minute alert polling

### APRS Messaging

- **Send & Receive** — Two-way APRS messaging with auto-ACK and retry support
- **Message Log** — Filterable message history (All / Sent / Received)
- **RF + IS Routing** — Messages sent on both RF and APRS-IS simultaneously

### Settings & UX

- **Web-based Configuration** — Edit all settings from the browser (saved to `config.toml`)
- **Pick Location on Map** — Click the map to set your station coordinates
- **APRS Symbol Picker** — Visual icon chooser with both primary and alternate symbol tables
- **Callsign + SSID Selector** — Uppercase callsign input with SSID dropdown (0–15) and descriptions
- **Miles-based Range Filter** — Enter range in miles; auto-generates APRS-IS `r/` filter

### APRS-IS Policy Compliance

- Proper amateur callsign format validation (rejects N0CALL, NOCALL, etc.)
- Minimum 600-second beacon interval enforced per APRS-IS usage policy
- Read-only mode: unverified connections (passcode `-1`) cannot transmit or gate
- IS→RF gated packets do not request further digipeating (no WIDE path)
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
| `[station]` | Callsign, SSID (0–15), position, symbol, beacon interval |
| `[digipeater]` | Enable/disable, WIDEn-N aliases, dedupe window |
| `[igate]` | Enable/disable, RF→IS and IS→RF gating |
| `[aprs_is]` | Server, port, passcode, filter string |
| `[kiss_serial]` | Serial KISS TNC port and baud rate |
| `[kiss_tcp]` | TCP KISS TNC host and port |
| `[web]` | Web interface bind address and port |
| `[tracking]` | Station age limits and cleanup intervals |
| `[database]` | SQLite database path |
| `[alerts]` | Band opening thresholds, Discord/email/SMS notification settings |
| `[weather]` | Weather enabled, location code (zip/ICAO), alert range miles, refresh interval |

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
│   ├── kiss.py             # KISS protocol (serial + TCP)
│   ├── packet_handler.py   # Central packet router
│   ├── station_tracker.py  # Station tracking & propagation
│   ├── analytics.py        # Analytics engine
│   ├── alerts.py           # Band opening alert manager
│   ├── weather.py          # Open-Meteo + NWS weather provider
│   └── websocket_manager.py
└── static/
    ├── index.html           # Single-page dashboard
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

## License

MIT
