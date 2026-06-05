# Linux and Raspberry Pi Install

This guide installs APRS PropView as a Python virtualenv application managed by
systemd. It works well on Raspberry Pi OS, Debian, and Ubuntu.

## Recommended Hardware

- Raspberry Pi 4 or newer, Raspberry Pi 3, or any small Linux host
- Raspberry Pi OS 64-bit, Debian, or Ubuntu
- Network access for APRS-IS and the web dashboard
- Optional KISS TNC over USB serial, Bluetooth serial, or TCP
- Optional Direwolf KISS TCP or AGWPE TCP service

## Install System Packages

On Raspberry Pi OS, Debian, or Ubuntu:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip rsync
```

## Get The Source

```bash
git clone https://github.com/RF-YVY/APRS-PropView.git
cd APRS-PropView
```

If you already have the source on the Pi, run the installer from the repository
root.

## Update To v1.5.7.0

For an existing Linux or Raspberry Pi service install, update the repository,
rerun the installer so `/opt/aprs-propview` receives the new application files,
and restart the service:

```bash
git pull
sudo bash ./scripts/install_linux.sh
sudo systemctl restart aprs-propview
```

Version 1.5.7.0 adds expanded MQTT/Home Assistant status entities, optional
watched callsign MQTT publishing, richer Sporadic-E diagnostics, station symbol
sizing, weather analytics dashboard updates, and first-heard log deduplication.
Existing `config.toml`, `propview.db`, cached map tiles, and user audio files
are preserved by the installer.

## Install As A Service

```bash
sudo bash ./scripts/install_linux.sh
```

By default this installs to `/opt/aprs-propview`, creates a virtualenv, installs
Python dependencies, writes `/etc/systemd/system/aprs-propview.service`, enables
the service, and adds the install user to the `dialout` group when that group
exists.

To install for a specific Linux user:

```bash
sudo APRS_PROPVIEW_USER=pi bash ./scripts/install_linux.sh
```

To choose a different install directory or service name:

```bash
sudo INSTALL_DIR=/srv/aprs-propview SERVICE_NAME=aprs-propview bash ./scripts/install_linux.sh
```

## Configure

The installer creates `/opt/aprs-propview/config.toml` from
`config.toml.example` if no config exists yet.

Start the service:

```bash
sudo systemctl start aprs-propview
```

Then open the web UI:

```text
http://<pi-ip-address>:14501
```

If the web UI should be reachable from other machines on the LAN, set this in
`/opt/aprs-propview/config.toml`:

```toml
[web]
host = "0.0.0.0"
port = 14501
```

Restart after changing the file:

```bash
sudo systemctl restart aprs-propview
```

## Service Commands

```bash
sudo systemctl start aprs-propview
sudo systemctl stop aprs-propview
sudo systemctl restart aprs-propview
sudo systemctl status aprs-propview
journalctl -u aprs-propview -f
```

## Troubleshooting Dependency Installs

If `pip install -r requirements.txt` fails while building `uvloop` on a
Raspberry Pi or other 32-bit ARM Linux system, update to the latest APRS
PropView requirements and reinstall. `uvloop` is an optional Uvicorn performance
extra, not required by APRS PropView.

For an existing virtualenv created from older requirements:

```bash
source /opt/aprs-propview/.venv/bin/activate
pip uninstall -y uvloop
pip install -r /opt/aprs-propview/requirements.txt
```

## Serial TNC Notes

USB serial TNCs commonly appear as:

```text
/dev/ttyUSB0
/dev/ttyACM0
```

Use that device path in `config.toml`:

```toml
[kiss_serial]
enabled = true
port = "/dev/ttyUSB0"
baudrate = 9600
mode = "kiss"
flow_control = "none"
```

The installer adds the service user to the `dialout` group when available. Log
out and back in, or reboot, if you are testing serial access manually as that
user.

## GPS Ingestion Notes

APRS PropView can use live GPS data on Linux/Pi systems after GPS ingestion is
enabled in Settings. The most common Pi/mobile options are:

- **This browser/device** - Use a phone, tablet, or laptop browser that has
  location permission. This is useful when the Pi is running the service but the
  browser device is what knows the current position.
- **Own APRS position packets** - Use position packets from your own radio,
  tracker, or TNC setup. This works well with mobile APRS setups where the TNC
  or radio is already feeding current position packets into APRS PropView.
- **NMEA serial GPS** - Use a USB GPS puck or GPS-enabled TNC that exposes NMEA
  sentences on a serial device such as `/dev/ttyUSB0` or `/dev/ttyACM0`.
- **NMEA TCP stream** - Connect to a local or network service that emits NMEA
  GPS sentences over TCP.
- **NMEA UDP listener** - Listen for NMEA sentences sent over UDP from another
  app or device on the LAN.
- **gpsd daemon** - Connect to gpsd on the Pi or another LAN host. This is a
  good default for Linux systems where gpsd already owns the USB GPS device.
- **Any source** - Accept the latest valid fix from any supported GPS source.
  This is helpful for testing or fallback setups, but a specific source gives
  clearer status if a device is missing.

For serial GPS on Linux, use the device path in Settings or `config.toml`:

```toml
[gps]
enabled = true
source = "nmea_serial"
serial_port = "/dev/ttyUSB0"
serial_baudrate = 9600
map_update_enabled = true
update_station_position = false
station_position_locked = true
```

Keep `station_position_locked = true` if GPS should move only the map marker and
not overwrite the configured station latitude/longitude.

For gpsd, leave gpsd on its normal port and select `gpsd`:

```toml
[gps]
enabled = true
source = "gpsd"
gpsd_host = "127.0.0.1"
gpsd_port = 2947
map_update_enabled = true
update_station_position = false
station_position_locked = true
```

## Offline Map Tiles

The web map can use a local XYZ tile server, which is the simplest path for
field or grid-down use after you have cached the area you care about:

```toml
[web]
map_tile_source = "custom"
map_tile_url = "http://127.0.0.1:8080/tile/{z}/{x}/{y}.png"
map_tile_attribution = "OpenStreetMap contributors"
map_tile_max_zoom = 14
```

Prepare the OpenStreetMap tiles ahead of time and keep the cached zoom range
modest. Higher zoom levels multiply storage quickly, especially for wide-area
mobile use.

The map **Cache** button stores the current view and zoom in `map_tile_cache/`.
Use it while internet is available for the areas you expect to need offline.

## Smart Beaconing

Smart beaconing can vary the station beacon interval from GPS speed. This is
useful for portable and mobile Pi installs where a stopped station should beacon
slowly, but a moving station should update more often.

```toml
[smart_beaconing]
enabled = true
slow_interval = 1800
fast_interval = 120
speed_threshold_mph = 10.0
```

APRS PropView keeps APRS-IS-safe minimums when saving settings. Enable GPS
ingestion first so the app has a current speed source.

## Direwolf, AGWPE, Or TCP RF Ports

For Direwolf or any TCP KISS source running on the same Pi:

```toml
[[rf_ports]]
name = "Direwolf KISS"
enabled = true
type = "tcp"
host = "127.0.0.1"
tcp_port = 8001
protocol = "kiss"
rx_only_rf = false
rx_only_is = false
```

For an AGWPE-compatible TCP source:

```toml
[[rf_ports]]
name = "AGWPE"
enabled = true
type = "tcp"
host = "127.0.0.1"
tcp_port = 8000
protocol = "agwpe"
rx_only_rf = false
rx_only_is = false
```

The legacy `[kiss_tcp]` and `[kiss_serial]` blocks still load for older configs,
but new Linux/Pi installs should prefer `[[rf_ports]]` so multiple receivers,
transmit-capable ports, and receive-only ports can be managed together.

For APRS-IS-only operation, leave `[kiss_serial]`, `[kiss_tcp]`, and all
`[[rf_ports]]` entries disabled.

## Private Or Local APRS-IS Servers

APRS PropView can receive from private/local APRS-IS-style servers and simple
TNC2 TCP feeds that do not send the usual public-server banner or `logresp`.
Packets arriving immediately after login are treated as receive traffic instead
of being discarded.

If the server does not verify the login with a `logresp`, PropView keeps the
connection read-only. This allows local packet collection and map population
without accidentally enabling APRS-IS transmit or IS-to-RF gating on an
unverified private feed.

## Scheduled Bulletins And APRS Objects

Scheduled packet settings work the same on Linux and Pi as on Windows. They can
be edited from Settings or in `config.toml`:

```toml
[bulletins]
enabled = true
interval = 1800
mode = "both"
path = "WIDE1-1"
items = [{ id = "1", text = "Club net tonight 7PM" }]

[aprs_objects]
enabled = true
interval = 1800
mode = "both"
path = "WIDE1-1"
items = [
  { name = "NET", latitude = 35.0000, longitude = -80.0000, symbol_table = "/", symbol_code = "r", comment = "Weekly net" }
]
```

The map `Obj` control can also create and save object entries after you click a
map location. Use preview buttons before enabling scheduled transmit.

## MQTT Integration

MQTT is optional and is meant for external dashboards and automation systems,
not for APRS transport. Enable it when you want APRS PropView status available
to a broker such as Mosquitto, Home Assistant, Node-RED, EMQX, or another
monitoring stack.

The source install uses `requirements.txt`, which includes `paho-mqtt`. If an
older virtualenv reports that `paho-mqtt` is missing, reinstall requirements
inside the service virtualenv:

```bash
source /opt/aprs-propview/.venv/bin/activate
pip install -r /opt/aprs-propview/requirements.txt
```

Common uses:

- Show propagation level or score on a shack dashboard.
- Trigger Home Assistant or Node-RED automations from propagation alerts.
- Log propagation metrics in another time-series or observability system.
- Feed a small LAN display without scraping the web UI.

Example local Mosquitto install:

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

Example configuration:

```toml
[mqtt]
enabled = true
broker = "127.0.0.1"
port = 1883
topic_prefix = "aprs/propview"
username = ""
password = ""
discovery_enabled = true
discovery_prefix = "homeassistant"
device_name = "APRS PropView"
device_id = "aprs_propview"
```

With the default prefix, APRS PropView publishes:

- `aprs/propview/propagation` - retained JSON propagation metrics.
- `aprs/propview/score` - retained regional propagation score.
- `aprs/propview/level` - retained regional propagation level.
- `aprs/propview/event` - automation events such as `first_heard` and
  `new_max_distance`.
- `aprs/propview/alert` - alert events such as band openings, anomalies,
  Sporadic-E, and first-heard direct RF alerts.
- `aprs/propview/status` - retained `online`/`offline` availability for
  Home Assistant entities.

When `discovery_enabled` is true, APRS PropView also publishes retained Home
Assistant MQTT Discovery configs under `homeassistant/sensor/<device_id>/...`.
Home Assistant will create sensors for My Station score/level, Regional
score/level, RF stations heard in the last hour, and max RF distance. Keep
`device_id` stable after discovery so Home Assistant does not create duplicate
entities.

MQTT settings saved from the web UI reconnect live. If you edit `config.toml`
manually, restart APRS PropView so the running process loads those file changes.

## Firewall

If a firewall is enabled, allow the web UI port:

```bash
sudo ufw allow 14501/tcp
```

## Updating

From your source checkout:

```bash
git pull
sudo bash ./scripts/install_linux.sh
sudo systemctl restart aprs-propview
```

The installer preserves an existing `/opt/aprs-propview/config.toml`.
New settings are added to `config.toml.example`; compare that file after
updating if you want to adopt new sections such as smart beaconing, bulletins,
APRS objects, gpsd, MQTT Discovery, or map tile caching in an older install.

The in-app About tab can still show that a newer GitHub release exists on
Linux and Raspberry Pi systems, but Windows setup installer actions are hidden.
Use the source update flow above for service installs.

## Uninstall

Remove the service but keep config, database, and installed files:

```bash
sudo bash ./scripts/uninstall_linux.sh
```

Remove the service and `/opt/aprs-propview`:

```bash
sudo REMOVE_DATA=1 bash ./scripts/uninstall_linux.sh
```
