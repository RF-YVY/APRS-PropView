# APRS PropView Node-RED Dashboard and Alexa Flow

This folder contains an importable Node-RED flow for APRS PropView:

- `aprs-propview-alexa-dashboard-flow.json`

It builds a live Node-RED dashboard from APRS PropView MQTT topics and exposes Alexa-discoverable virtual devices for common PropView actions.

## Required Node-RED Palettes

Install these from **Menu > Manage palette > Install**:

- `node-red-dashboard`
- `node-red-contrib-alexa-home`

The Alexa palette emulates a local Philips Hue bridge. Alexa discovery requires the Alexa device and Node-RED host to be on the same IPv4 LAN with multicast/SSDP allowed.

## APRS PropView Settings

In APRS PropView, open **Settings > MQTT Integration** and enable MQTT:

- Broker: your MQTT broker host, often `localhost`, `homeassistant.local`, or a LAN IP
- Port: usually `1883`
- Topic prefix: `aprs/propview`
- Home Assistant Discovery: optional for this Node-RED flow, but useful if Home Assistant is also present

APRS PropView publishes retained state on:

- `aprs/propview/propagation`
- `aprs/propview/ha/status`
- `aprs/propview/score`
- `aprs/propview/level`

It also publishes live automation payloads on:

- `aprs/propview/event`
- `aprs/propview/alert`

## Import and Configure

1. In Node-RED, choose **Menu > Import**.
2. Import `deploy/node-red/aprs-propview-alexa-dashboard-flow.json`.
3. Open the **APRS PropView MQTT broker** config node and set your broker host, port, username, and password.
4. Deploy the flow.
5. Open the dashboard at `http://<node-red-host>:1880/ui`.

The flow assumes APRS PropView is reachable from Node-RED at:

```text
http://127.0.0.1:14501
```

If PropView runs on another machine, add an Inject or Change node that runs once at startup:

```js
flow.set("aprsPropViewBaseUrl", "http://192.168.1.50:14501")
```

Replace the IP with the host running APRS PropView.

## Alexa Devices

The flow exposes these devices:

- `APRS PropView Beacon`
- `APRS PropView WX Now`
- `APRS PropView Bulletins`
- `APRS PropView Objects`
- `APRS PropView Band Opening`

Voice examples:

```text
Alexa, discover devices.
Alexa, turn on APRS PropView Beacon.
Alexa, turn on APRS PropView WX Now.
Alexa, turn on APRS PropView Bulletins.
Alexa, turn on APRS PropView Objects.
```

`APRS PropView Band Opening` is state-oriented. It follows PropView's `band_opening_active` MQTT state so it can appear in the Alexa app as a discoverable device.

## Alexa Port Note

Modern Alexa devices generally require the emulated bridge on port `80` for HTTP or `443` for HTTPS. The flow's Alexa controller defaults to port `80`.

If Node-RED cannot bind to port `80`, either run Node-RED with suitable privileges, use the Alexa palette's **Use Node-RED Server** option with Node-RED itself on port `80`, or forward port `80` to the Node-RED/Alexa bridge port on your host.

## Dashboard Contents

The dashboard includes:

- My-station and regional propagation gauges
- Regional score and max-distance charts
- RF/APRS-IS status
- Last RF packet age
- Message waiting, weather warning, and band-opening state
- Latest event/alert display with toast notifications
- Manual action buttons for beacon, WXnow, bulletins, and objects
