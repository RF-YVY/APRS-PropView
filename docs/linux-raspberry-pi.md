# Linux and Raspberry Pi Install

This guide installs APRS PropView as a Python virtualenv application managed by
systemd. It works well on Raspberry Pi OS, Debian, and Ubuntu.

## Recommended Hardware

- Raspberry Pi 4 or newer, Raspberry Pi 3, or any small Linux host
- Raspberry Pi OS 64-bit, Debian, or Ubuntu
- Network access for APRS-IS and the web dashboard
- Optional KISS TNC over USB serial, Bluetooth serial, or TCP
- Optional Direwolf KISS TCP service

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
