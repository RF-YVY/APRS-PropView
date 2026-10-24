# Linux, Raspberry Pi and macOS builds

The built-in modem now builds a host-native library on Windows, Linux and macOS.
Run Python 3.11 or newer. Build on the target OS and CPU architecture: a Windows
DLL or executable cannot be used as a native Linux/Pi/macOS application.

## Linux / Raspberry Pi OS

Prefer 64-bit Raspberry Pi OS on an ARM64 Pi. ARM64 is in the CI matrix; a physical
Pi and 32-bit ARM have not been validated locally. Native modem compilation uses
the host compiler without x86-specific instructions. Dependency availability and
real-time audio performance still need checking for older or 32-bit Pi models.

For Debian/Ubuntu/Raspberry Pi OS, install the build and audio requirements:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev g++ libportaudio2 libnetcdf-dev libhdf5-dev
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python native/build_modem.py
.venv/bin/python main.py --modem-self-test
.venv/bin/python main.py
```

The compiler produces `native/bin/libpropview_modem.so`. The dashboard defaults
to port 14501. Desktop application data lives under
`${XDG_DATA_HOME:-$HOME/.local/share}/aprs-propview`.
Select your USB audio interface under Settings â†’ Radio & TNC. Linux serial
ports such as `/dev/ttyUSB0` are supported, including case-sensitive enumerated
device paths. The application account needs permission to use the selected
audio and serial devices; on Debian-derived systems those are commonly managed
through `audio` and `dialout` groups. Log in again after changing group membership.

For a portable executable:

```sh
.venv/bin/python -m pip install pyinstaller
.venv/bin/python build_linux.py
dist/APRSPropView --modem-self-test
```

Build on the oldest Linux distribution you intend to support. PyInstaller does
not bundle glibc; an executable built on a newer distribution may not run on an
older distribution. The target also needs system PortAudio (`libportaudio2`).

## macOS (Intel or Apple Silicon)

Install Python 3.11+ for your Mac architecture and Xcode command line tools
(`xcode-select --install` if needed), then:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python native/build_modem.py
.venv/bin/python main.py --modem-self-test
.venv/bin/python main.py
```

The compiler produces `native/bin/libpropview_modem.dylib`. A pip installation
of sounddevice normally includes PortAudio on macOS. Grant microphone access
to the terminal/Python host for source runs, or to the app for packaged runs.
Serial PTT accepts enumerated `/dev/cu.*` paths and preserves their case.
Application data is stored in
`~/Library/Application Support/APRS PropView/`.
The dashboard works without a macOS menu-bar icon; the incompatible background
tray is deliberately omitted. Use the browser dashboard and the normal OS app
controls, or Ctrl+C when running from a terminal.

Build the .app on the Mac itself:

```sh
.venv/bin/python -m pip install pyinstaller pystray
.venv/bin/python build_macos.py
open 'dist/APRS PropView.app'
```

The app includes the native modem, microphone usage declaration and audio-input
entitlement. It uses the stable application bundle identity. An optional `MACOS_CODESIGN_IDENTITY`
selects a signing identity; otherwise it is ad-hoc signed for local testing.
Notarization/distribution approval is a separate release step. Intel and Apple
Silicon builds are separate; use matching Python and compiler architectures.

## Headless servers and containers

Set `PROPVIEW_DEPLOYMENT=1` to preserve explicit `PROPVIEW_*` configuration.
Explicit environment settings are honored by the release runtime.

```sh
export PROPVIEW_DEPLOYMENT=1
export PROPVIEW_DATA_DIR="$HOME/propview-data"
export PROPVIEW_HOST=0.0.0.0
export PROPVIEW_PORT=14501
export PROPVIEW_LAUNCH_BROWSER=none
.venv/bin/python main.py --set-operator-password
.venv/bin/python main.py
```

The password command prompts on the host terminal without echoing the password.
It writes credentials beside this deployment's config. The web dashboard remains
subject to the existing operator authentication and CSRF protections.

The Dockerfile now builds the Linux modem for the image's architecture, includes
PortAudio, and honors `/data`, `0.0.0.0:14501` and the existing health check.
Use `docker compose up --build` after choosing a local `build: .` configuration,
or build explicitly with `docker build -t aprs-propview:dev .`.
An existing published `latest` image does not acquire local source changes.
TCP KISS works without exposing local hardware. USB serial/audio modem use needs
explicit device access and matching group permissions, for example:

```sh
docker run --rm -p 14501:14501 -v propview-data:/data \
  --device /dev/snd --device /dev/ttyUSB0 \
  --group-add "$(stat -c %g /dev/snd/controlC0)" \
  --group-add "$(stat -c %g /dev/ttyUSB0)" aprs-propview:dev
```

Adjust device paths to the host; this example assumes direct ALSA devices, not a
host PipeWire/PulseAudio socket. The service template sets deployment mode and
uses `/var/lib/aprs-propview`; adjust its user/group to your host.

## Validation

```sh
.venv/bin/python scripts/run_tests.py
.venv/bin/python scripts/platform_smoke.py
.venv/bin/python main.py --modem-self-test
```

The smoke test checks a real isolated headless startup, configured HTTP port,
health endpoint, dashboard and explicit database path without enabling RF.
CI includes Windows, Linux x86-64/ARM64 and macOS Intel/Apple Silicon; configured
jobs are not proof of success until they run. Physical USB audio and PTT tests
remain necessary on each intended radio/interface/platform combination.
