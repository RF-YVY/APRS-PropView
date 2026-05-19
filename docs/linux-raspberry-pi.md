# Linux and Raspberry Pi Install

This guide installs APRS PropView as a Python virtualenv application managed by
systemd. It works well on Raspberry Pi OS, Debian, and Ubuntu.

## Recommended Hardware

- Raspberry Pi 4 or newer, Raspberry Pi 3, or any small Linux host
- Raspberry Pi OS 64-bit, Debian, or Ubuntu
- Network access for APRS-IS and the web dashboard
- Optional KISS TNC over USB serial, Bluetooth serial, or TCP
- Optional Direwolf or Soundmodem by uz7ho KISS TCP service

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

## Direwolf Or TCP KISS

For Direwolf or any TCP KISS source running on the same Pi:

```toml
[kiss_tcp]
enabled = true
host = "127.0.0.1"
port = 8001
```

For APRS-IS-only operation, leave both `[kiss_serial]` and `[kiss_tcp]`
disabled.

## MQTT Integration

MQTT is optional and is meant for external dashboards and automation systems,
not for APRS transport. Enable it when you want APRS PropView status available
to a broker such as Mosquitto, Home Assistant, Node-RED, EMQX, or another
monitoring stack.

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
```

Restart APRS PropView after changing MQTT settings in `config.toml`.

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

## Uninstall

Remove the service but keep config, database, and installed files:

```bash
sudo bash ./scripts/uninstall_linux.sh
```

Remove the service and `/opt/aprs-propview`:

```bash
sudo REMOVE_DATA=1 bash ./scripts/uninstall_linux.sh
```
