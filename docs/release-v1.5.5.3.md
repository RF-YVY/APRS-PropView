# APRS PropView v1.5.5.3

Released: June 2, 2026

## Highlights

- Added Home Assistant MQTT Discovery for propagation sensors.
- Added MQTT availability publishing on `aprs/propview/status`.
- Added automation-friendly MQTT events on `aprs/propview/event`, including `first_heard` and `new_max_distance`.
- MQTT settings now reconnect live after saving broker, login, topic, or discovery changes.
- Updated MQTT setup documentation for Home Assistant and Node-RED automation workflows.

## Upgrade Notes

- Existing MQTT topics are preserved.
- Enable Home Assistant Discovery from Settings or add the new `[mqtt]` discovery fields to `config.toml`.
- MQTT settings saved from the web UI apply live. Restart APRS PropView only when editing `config.toml` manually.
