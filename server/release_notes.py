"""Bundled release notes and per-installation update acknowledgement."""
import json
import logging
from pathlib import Path

from server.config_io import atomic_write

logger = logging.getLogger('propview.release')

RELEASES = {
    '1.13.0': [
        'Experimental built-in soundcard modem: RX/TX, millisecond transmit delay, serial/VOX PTT, diagnostics, WAV tests and saved startup settings.',
        'Web and mobile access on port 14501 across LAN and Tailscale, with operator-protected controls.',
        'Operator sessions, OTA activity spots, custom header icons, RF line controls and live digipeater fixes.',
        'Linux/Pi/macOS native builds, deployment support, updated documentation and the full changelog since v1.11.1.',
        'Experimental modem: further testing is needed on Linux, Raspberry Pi and macOS.',
    ],
    '1.13.0-dev.11': [
        'Matched Lines button size to adjacent Appearance buttons.',
        'Moved operator session details into a compact lock-button popover below the map, with sign-in, extend and lock actions.',
        'Rewrote in-app help and full documentation from a shared current-feature user guide, including modem RX/TX, OTA spots, authentication, weather, mapping, integrations and troubleshooting.',
    ],
    '1.13.0-dev.10': [
        'Moved built-in modem setup from the map toolbar to Settings RF Ports.',
        'Renamed the spot button and dialog to Send OTA Activity Spot.',
    ],
    '1.13.0-dev.9': [
        'Added saved Show RF lines toggle and expanded line controls inside Appearance. APRS-IS packet animations remain temporary. RF lines respect source, station and time filters.',
    ],
    '1.13.0-dev.8': [
        'Weather and lightning setup is now visible in Basic Settings under Alerts & Weather, including enable switches, location lookup and display options.',
    ],
    '1.13.0-dev.7': [
        'RF source health now shows Listening when the receiver is connected but no RF packets have been decoded this session, preserving Live and Stale packet freshness states.',
        'Moved Send APRS SPOT to the map toolbar beside the built-in modem control.',
    ],
    '1.13.0-dev.6': [
        'Channel wait toggle now applies immediately and persists across restarts; the active mode is shown beside TX status.',
        'Saved modem RX and enabled TX setup now restore automatically on launch, matching saved audio interfaces by name and host API.',
        'Stop RX disables automatic reception startup; Stop TX disables automatic TX enable. Quitting preserves setup.',
    ],
    '1.13.0-dev.5': [
        'Added Wait for clear channel in modem transmit settings, enabled by default. Disable and apply to bypass carrier waiting for all modem transmissions.',
    ],
    '1.13.0-dev.4': [
        'Built-in modem connection and transmit changes now update dashboard RF status without a separate Settings RF port.',
        'Manual beacon readiness respects modem TX enable; source health recognizes modem reception.',
        'Carrier detection requires sustained tone evidence so short noise peaks do not hold the channel busy.',
    ],
    '1.13.0-dev.3': [
        'Operator passwords can now be 6-256 characters; existing passwords continue to work.',
        'Fixed the NOAA Minimum Kp field step so the default threshold of 5.00 is valid.',
        'Added original native AFSK transmit encoding, radio audio output selection, NOMIC/RTS/DTR/VOX PTT, and a manual RF test packet.',
        'Transmission defaults off each session, defers on a busy channel, and includes a stop control and bounded audio/PTT watchdog.',
    ],
    '1.13.0-dev.2': [
        'Added plain-language explanations of modem readings, audio levels, CRC failures, decoder lanes and processing counters inside the modem setup window.',
    ],
    '1.13.0-dev.1': [
        'Separate development installation, local data, port 14502 and disabled stable-channel updates.',
        'Original native 1200-baud soundcard decoder with live input levels, clipping and receive diagnostics.',
        'Decode recorded PCM WAV files and download a generated test recording without transmitting RF.',
        'Experimental receive-only modem; reception performance still requires real-radio testing.',
    ],
    '1.12.0': [
        'Public dashboards are read-only. Remote operator sessions protect settings, messages, manual transmissions and updates.',
        'Browsers opened by the host application sign in automatically, without unlocking any public viewers.',
        'Set or recover your operator password in a friendly window on the host computer, with no online account required.',
        'Remote sign-in lasts 15 minutes, 1 hour or 8 hours, with a countdown and Lock now control.',
        'The mobile map uses key-free OpenStreetMap tiles, including a locally styled dark theme.',
        'Radar visibility and loop/static controls are available below the main map.',
        'Updates show download progress and setup guidance, relaunch the application, and refresh the existing browser tab.',
        'Send APSPOT activation spots with editable operator callsigns, automatic formatting and routing, plus current-spot filters, test mode and service help.',
        'Fixed KISS frame escaping for channels 12 and 13.',
    ],
    '1.11.1': [
        'Preserved saved MQTT passwords when an unrelated settings save leaves the password field blank.',
        'Fixed Safari settings overlay controls and Windows weather HTTPS certificate handling.',
    ],
}


class ReleaseNotes:
    def __init__(self, path, version, existing_installation=False):
        self.path, self.version = Path(path), version
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(state, dict):
                raise ValueError()
        except (OSError, ValueError):
            state = {}
        previous = state.get('version')
        self.pending = bool(state.get('pending')) if previous == version else bool(version == '1.13.0' or previous or existing_installation)
        self._save()

    def _save(self):
        try:
            atomic_write(self.path, json.dumps({'version': self.version, 'pending': self.pending}))
            return True
        except OSError:
            logger.warning('Could not save release-notice state; the notice may reappear after restart.')
            return False

    def acknowledge(self, version):
        if version != self.version:
            return False
        previous = self.pending
        self.pending = False
        if not self._save():
            self.pending = previous
            return False
        return True

    def snapshot(self, operator=False):
        return {'version': self.version, 'changes': RELEASES.get(self.version, []),
                'changelog_url': '/static/releases/v1.13.0.html' if self.version == '1.13.0' else None,
                'should_show': bool(operator and self.pending)}


def migrate_network_settings(config, config_path, version):
    """One-time migration of the former loopback/dev defaults for v1.13.0."""
    if version != '1.13.0':
        return
    path = Path(config_path)
    try:
        state = json.loads(path.with_name('release-state.json').read_text(encoding='utf-8'))
        if state.get('version') == version:
            return
    except (OSError, ValueError, AttributeError):
        pass
    changed = False
    if config.web.host in {'127.0.0.1', 'localhost', '::1'}:
        config.web.host = '0.0.0.0'
        changed = True
    if config.web.port == 14502:
        config.web.port = 14501
        changed = True
    if changed:
        config.save(path)
