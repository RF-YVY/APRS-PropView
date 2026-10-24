# APRS PropView User Guide

Current version: **1.13.0**. This guide covers the desktop dashboard, mobile companion, settings and built-in modem.

## Getting started

Install the application, launch it, and complete the operator-password window on the host computer. Set your callsign, SSID, symbol and coordinates under **Settings â†’ Station & Location**. Coordinates can be typed, picked on the map or supplied by the configured GPS source. Use your actual licensed station identity before transmitting.

Open **Settings â†’ Radio & TNC â†’ RF Ports** to configure an external TNC or the built-in experimental modem. APRS-IS is an independent internet feed; configure it in the same category if needed. Start with reception, verify the RF/APRS-IS indicators and packet list, then enable the transmit functions you intend to use. Weather and lightning require their own enable switches under **Alerts & Weather**; setting station coordinates alone does not enable them.

Settings offers **Show Advanced / Show Basic**, category navigation, search, collapsible sections, guided setup, connection diagnostics, operating-mode presets, a configuration-readiness summary and transmit-setting protection. Presets stage changes for review; save them to apply. Settings with a restart requirement identify it in the save feedback. Export a configuration backup before changing network or interface settings.

## Operator access and public viewing

Click the small **lock icon in the toolbar below the map** to see whether this browser is a local operator, a signed-in operator or a public viewer, and the remaining session time. The popover provides **Extend session / Operator sign in** and **Lock now**. Extend session opens the password form again. Choose 15 minutes, one hour or eight hours when signing in. Click outside the popover or press Escape to close it.

Authentication belongs to the browser session that signed in. Signing in on the host or through a private VPN does not unlock anyone else's public browser. Public viewers can observe the dashboard; settings, private messages, transmissions, configuration exports and update operations require operator access. Lock now revokes this browser's session. Expiry returns it to read-only viewing; it does not stop the backend modem or previously configured station functions.

The host's password setup window can enable automatic sign-in for browsers opened by the local application. A manually entered dashboard address does not receive that local-launch access automatically. Passwords must be **6â€“256 characters**. For a forgotten password, use **Set/reset operator password** from the host's tray or Start menu. The local GUI sets a replacement password and revokes existing sessions; no email or hosted recovery server is required.

For public hosting, use HTTPS through your reverse proxy and retain operator authentication. A private VPN is another option for remote use. Set the listening host/port as needed and restart when requested. Only expose the intended web interface. See the separate public-hosting guide for session and proxy details.

## Dashboard, map and toolbars

The header shows station identity, direct and regional propagation evidence, RF/APRS-IS/browser connection indicators, Data source health and notifications. Theme controls change the UI separately from the map background. The sidebar contains RF stations, APRS-IS stations, packet history, propagation, analytics, operator messages/settings and About/Help. Collapse the sidebar for more map area.

The bottom map toolbar provides **Send OTA Activity Spot**, **View**, **Stations**, **Layers**, **Appearance** and the operator lock button. The built-in modem is configured in **Settings â†’ Radio & TNC â†’ RF Ports**, not from this toolbar.

- **View:** center on your station, enable the local scope/range rings, fit visible stations or create an APRS object. Auto-fit stops after manual map movement; enable it again to resume.
- **Stations:** show RF and APRS-IS sources, direct RF only, callsign labels and station-type filters. Station lists also filter age, distance, callsign, category and path, and offer sorting.
- **Layers:** use the available map overlays, radar visibility and loop/static controls, and the RF line-history time window. Weather layers also have provider and opacity settings.
- **Appearance:** map light/dark theme, tile caching, station symbol size and **Lines**. Lines is the same size as the adjacent buttons and expands its controls inside Appearance.

In **Appearance â†’ Lines**, **Show RF lines** switches persistent RF paths on or off. Color can follow distance or use a custom color; weight, solid/dash/dot/dash-dot pattern and opacity adjust the drawing. **VHF Paths** independently controls watched-path lines. These preferences are saved in this browser, along with map position, zoom and filters.

Persistent paths describe RF reception only. Direct stations connect to your station; relayed stations follow known used digipeater positions. When a required digipeater position is missing, the path is suppressed rather than drawn as a direct contact. APRS-IS packet animations remain temporary and are not evidence that your radio heard the station. With only APRS-IS stations visible, no persistent RF paths are expected. The line time filter and source/type filters can also hide RF lines.

Click a station for position, distance, bearing, path, source, last-heard and available packet/weather information. Overlapping stations can spread out for selection. Ghosting fades old markers; expiry removes them. Direct-RF-only filtering excludes APRS-IS and relayed RF. Units, font, theme/skin, density, activity effects and dashboard-panel visibility are configurable. Club Display provides a presentation-oriented rotating display with its own layout options.

## Map sources and offline use

Default OpenStreetMap tiles work without a map API key on desktop and mobile. Optional custom/local tile sources have their own URL and attribution requirements; some providers require keys. A tile template needs the appropriate zoom/x/y placeholders. Cache the visible map area while online when planning offline use. Cached tiles and APRS reception do not provide offline weather, radar, internet APRS or other external feeds.

## External RF interfaces, digipeater and IGate

RF Ports supports multiple named serial and TCP interfaces. Serial KISS, TCP KISS and TCP AGWPE server ports are transmit-capable when enabled and connected; TNC2 monitor reception is receive-only. Select the TCP protocol that matches your server. Serial options include flow control and supported initialization profiles/commands. Select the correct COM device, speed or TCP endpoint and any receive-only restrictions. Names appear in packet/station information. TCP interfaces expose connection, error and retry information and reconnect automatically. A green browser connection only confirms the dashboard link, not a radio link.

Digipeater settings control whether received packets may be repeated, including path/deduplication behavior. IGate settings control RF-to-APRS-IS and optional APRS-IS-to-RF traffic, subject to route restrictions. Review paths and station settings before enabling these functions. A receive-only interface is never a transmit path. The built-in modem continues to block APRS-IS-to-RF gating even when its own RF transmit is enabled.

Manual **Transmit Beacon** uses the selected RF, APRS-IS or combined route and requires a valid station position. Connected RF reception and RF transmit availability are separate: the modem can receive while TX is disabled. Scheduled beacon intervals and smart beaconing are station functions, independent of whether a browser is currently open.

**Experimental modem:** further radio and hardware testing is needed on Linux, Raspberry Pi and macOS. Performance may vary by platform and audio interface.

## Built-in modem: reception

This development-only original Bell 202 modem handles 1200-baud AFSK APRS. Open **Settings â†’ Radio & TNC â†’ RF Ports â†’ Configure Built-in Modem**. Select the radio's audio input and left/mono or right channel, then **Start receiving**. Use actual local receiver audio for operating the radio. Avoid microphone noise suppression, automatic gain processing, feedback and clipping. Open squelch is supported; ordinary receiver hiss should not count as an APRS carrier.

Successful RX setup is saved for automatic reception on subsequent application launches. Saved audio devices are matched by name and host API rather than assuming their numeric device IDs are unchanged. If a saved device is unavailable, startup reports an error instead of choosing an unrelated input or output. Refresh devices and reconfigure it. **Stop** reception disables RX automatic startup and stops TX. Closing the modem window leaves the backend operating; quitting releases the devices while preserving the configured startup choices.

**Test with a WAV recording** decodes 16-bit PCM WAV, mono or stereo, 8â€“96 kHz, up to five minutes and 32 MB. Choose the intended audio channel. The generated test WAV is an offline reference. Imported recording results stay out of the live map and cannot cause gating, digipeating or message acknowledgements. A recording decoding successfully while live input does not usually calls for checking the selected input and audio routing.

### Reading modem diagnostics

- **AFSK:** audio-frequency shift keying; APRS data switches between 1200 and 2200 Hz tones. **RX/TX** mean receive/transmit.
- **dBFS RMS / peak:** average and maximum digital audio level. Full scale is 1.0. Green level alone confirms audio is present, not that it contains decodable APRS.
- **CRC failures:** candidate frames failed the checksum and are discarded. Multiple decoder lanes try different timing/decision settings, so failures are not a count of unique lost packets. Some failures alongside successful reception are normal.
- **Clipped samples:** samples near full scale; a rising count suggests lowering input level. **Audio overflows** and **dropped blocks** indicate missing input data or queue pressure.
- **DSP milliseconds:** processing time for each 20 ms audio block. **Channel busy/clear** is the modem's tone/carrier estimate, independent of whether channel waiting is enabled.

## Built-in modem: transmission and NOMIC

Start reception first. In **Transmit setup**, explicitly select the soundcard output wired to the radio interface and the output channel. Choose RIGblaster NOMIC RTS, generic serial RTS, serial DTR or radio VOX. For NOMIC select its USB serial COM port and the soundcard output connected to it. The selected RTS line keys PTT and the unused DTR line is held low. VOX uses audio keying without a serial port. The NOMIC's USB/serial connection is not a substitute for selecting the audio output used by your wiring.

Set audio amplitude, TX delay/lead-in and tail, check **Enable RF transmission**, then **Apply transmit settings**. Initial defaults are amplitude 0.20, lead-in 300 ms and tail 50 ms. Amplitude adjusts audio, not transmitter power; set the radio's deviation using appropriate test equipment or another receiver. Lead-in allows radio/receiver settling. Tail sends closing flags before releasing serial PTT.

**Wait for clear channel** defaults on. Unchecking it applies immediately and saves across restarts; TX status shows **Channel wait OFF**. It bypasses carrier waiting for test packets, beacons, messages, spots and other permitted modem transmissions. Carrier diagnostics still display busy/clear. If waiting is on and busy persists, the packet can fail without keying. Check quiet-channel noise, hum, feedback and tone detection, or turn off the option when deliberately testing without carrier waiting.

**Send RF test packet** sends one identified APRS status packet without a digipeater path. Start with a dummy load and a second receiver. The modem cannot confirm over-the-air reception merely because audio/PTT completed. Successful TX setup restores the enabled transmit state at application launch; existing scheduled transmissions can then operate. **Stop TX / disable** aborts output, releases serial RTS/DTR and saves TX disabled. Locking a browser is not a radio stop control.

The transmit watchdog bounds audio/serial PTT to ten seconds per packet; VOX release also depends on the radio's own hang time. Output/serial failures disable TX until corrected and reapplied. Reception decoding pauses during local transmission and resynchronizes afterward. The modem remains experimental: verify operation with your actual radio/interface, including open squelch and long-running reception. Separate development settings, executable, port and data preserve stable v1.12.0.

## APRS-IS and packet interpretation

Configure callsign, server, port, passcode and filter under **Radio & TNC â†’ APRS-IS**. Unverified/read-only connections can receive; sending requires verification. Filter helpers support fixed station ranges, moving/my ranges and extra APRS-IS filter tokens. The packet list identifies RF versus internet source; internet reports must not be read as local radio propagation evidence.

## Messages, contacts and OTA activity spots

Operator Messages provides station conversations, sent/received history, acknowledgements, retries, route selection and contacts. Message retention and sibling-SSID reception are configurable. Select a usable route and review pending/retry states; sending is not the same as receiving an acknowledgement. Incoming-message notifications can use enabled local audio or external channels.

Click **Send OTA Activity Spot** below the map to use APSPOT. Choose POTA, SOTA, WWFF or SIOTA, then enter the activity's required reference, frequency in MHz, supported mode and any desired comment. The operator callsign is prefilled from the station callsign without its SSID and is editable for another operator on the activation. The application constructs and validates the service message; do not type packet delimiters or destination formatting into the fields. The configured station identity remains unchanged.

Expand **+ more options** for route selection, packet preview, a test spot without publishing, current-spot requests for POTA/SOTA/WWFF with supported filters/result count, and service-help requests with APRS/SMS/Winlink examples. These requests are sent over APRS; the form does not send SMS or Winlink mail itself. Automatic routing chooses usable RF first, otherwise verified APRS-IS, and does not duplicate a send onto another route after an attempted transmission. Replies appear in Messages. APSPOT registration and a working return path may be needed.

Service credit and current service instructions: [APSPOT by Josh, VK2MES](https://apspot.radio/) and [APSPOT getting started](https://apspot.radio/getting-started/).

## Beacons, reports, bulletins, objects and WXnow

Station settings control position beacons, symbol/comment, routing and interval. Smart beaconing selects intervals using GPS speed when configured. Status/DX reports can summarize activity or rotate configured messages, choose ordering and route, and issue configured weather-alert beacons with cooldowns. Preview controls show the generated packet before a test send.

Bulletins and APRS objects have enabled item lists, timing and RF/APRS-IS routing. Objects can also be created from the map and saved into the scheduled list. Use the symbol picker to select primary/alternate APRS symbols. The PHG calculator helps construct station power, antenna height, gain and directivity information for the station beacon. Saved/enabled lists can transmit without an open browser when their route is ready.

WXnow uses a local WXnow.txt file for current conditions and/or scheduled APRS weather packets, with file, route, path, position and preview/test settings. It expects the supported timestamp/weather-body format; stale or invalid files are reported. Optional online condition enrichment is separate from the file's sensor values. Weather beacons, object traffic and status reports share the available transmit interfaces.

## Propagation evidence and watched paths

**My Station** evaluates direct RF reception. **Regional** includes broader RF paths. APRS-IS alone does not raise local RF evidence. Counts, distance and time windows contribute to scores; confidence, freshness and direct/relayed distinctions matter more than the score alone. Evidence views explain their observations and distinguish no data, warming up, active observations and stale history.

Propagation and Analytics offer station/distance histories, longest paths, reliability/time-of-day and day-of-week patterns, heatmaps, bearing sectors, historical comparison, anomalies, first-heard stations, possible Sporadic-E, weather graphs and APRS weather-mesh context. Detection is an indication for investigation, not a guarantee of an opening. Data export supports analysis outside the application.

Watched VHF paths use a callsign, coordinates or Maidenhead grid plus band, mode, frequency and confidence requirements. Bearing tolerance, probe count, target area, maximum age and cooldown govern evidence. Antenna heights, transmitter power and antenna gain add horizon/EIRP/capability context; they do not replace measured propagation evidence. Watched locations can also receive configured weather/lightning awareness within a radius. **VHF Paths** in Lines controls their map drawing independently of RF reception lines.

NOAA space weather adds Kp/context with optional threshold alerts. The default Minimum Kp is **5.00**, a valid value. Optional PSK Reporter reports at 50 MHz and above supply independent digital-mode context rather than pretending to be your RF reception. External feeds have their own freshness and availability.

## Weather, radar, alerts and lightning

Open **Settings â†’ Alerts & Weather â†’ Weather**. The Weather section is visible in both Basic and Advanced Settings. Check **Weather Enabled**, enter a ZIP/ICAO location code and use **Lookup**, select the appropriate current-condition source, then **Save**. Station coordinates alone do not supply this separate weather location. Open-Meteo current conditions require no API key; optional providers can require their own credentials. WXnow can supply local current weather when configured.

Current conditions, wind, precipitation, forecast/ducting context and alerts are displayed when available and their banner/panel settings permit it. Radar visibility, animation versus static, opacity/provider/custom layers, satellite imagery and weather alert polygons have separate controls. The bottom map Layers menu provides radar show/hide and loop/static controls. Provider coverage and valid tile configuration affect availability.

Weather alerts support the configured provider, point or county/zone scope, ranges/groups and optional elevated polling triggers. NWS coverage is US-focused; optional Weatherbit needs its configured key. Weather alert symbols, notifications and APRS alert beaconing are independent options.

For lightning enable **Show Lightning On Map** and, if desired, **Show Lightning Info Card**. GOES GLM satellite selection can be automatic or explicit; history, opacity, stale interval and nearby-alert radius/cooldown are configurable. The card shows source, recent/retained flashes, nearest flash and feed age/error. A healthy feed can show zero nearby flashes; satellite lightning does not mean a ground strike at each plotted coordinate. Inspect Data source health before assuming a blank overlay is a display error.

## Alerts and notification delivery

Propagation thresholds, anomalies, first-heard events, Sporadic-E candidates, messages, weather and lightning can use their configured alert channels. Set cooldowns and quiet hours to reduce repeated notices. The Alert Tuning Helper estimates thresholds from local historical evidence. Watched-location and message channels have their own switches; a global delivery setting alone does not enable every alert type.

Local audio alerts support an output device and event-specific sound files. Discord webhooks, SMTP email and email-to-SMS gateways require working account/provider configuration. Availability of email-to-SMS delivery depends on the gateway. Header notifications retain useful in-app notices and can be cleared. Preview/test tools are available for the applicable settings.

## GPS, mobile, display and remote operation

GPS sources include browser/mobile geolocation, own APRS reports, NMEA serial/TCP/UDP, gpsd and any-supported-source mode. **LOCK** prevents live GPS from overwriting saved station coordinates; moving the displayed marker and saving coordinates are distinct choices. Smart beaconing can use received speed. Browser geolocation requires permission and browser-compatible secure/local access.

Open **/mobile** for the companion map, station, message, propagation and About views. It uses the no-key OSM map by default and can share browser GPS when authorized and configured. A remote phone needs its own operator session for privileged actions. Tailscale or another private VPN can connect the host and phone; use the host's configured port, not an assumed universal port.

Web/Display settings include listening host/port, browser selection or no automatic browser, UI/map appearance, unit system, fonts, marker aging, display density, visualization effects, dashboard panel visibility and Club Display. Browser UI preferences are local to that browser. Server settings and station configuration are shared by all viewers subject to authentication.

## Source health and troubleshooting

**Data â†’ Source Health** separates connection state from data age. RF **LISTENING** means a receiver is connected but no RF packet has been recorded this session; **LIVE** means recent RF data; **STALE** means old observations; **OFFLINE** means unavailable; **OFF** means disabled. Configured tile layers are not a guarantee every external tile request succeeded. Browser live-link state is separate from backend feed health.

- **Weather/lightning OFF:** enable their separate settings and save. If settings are missing, clear Settings search, open Alerts & Weather and expand Weather. Dashboard visibility can still hide a card.
- **Modem audio but no live decode:** verify input/channel/routing, avoid clipping or audio processing, and compare a recording with Test with a WAV recording. Green audio does not establish APRS content.
- **Channel busy blocks TX:** inspect the active Channel wait ON/OFF status. Uncheck Wait for clear channel to bypass it immediately. Check the app version if the new control is missing.
- **RF connected but manual TX unavailable:** enable/apply modem TX or check external-interface receive-only restrictions. A position beacon also requires coordinates. APRS-IS sends require verification.
- **No persistent lines:** RF reception paths require RF stations and known hop positions. Enable Show RF lines, the RF source and a suitable time window. APRS-IS animations are intentionally temporary.
- **Modem startup error:** reconnect the saved radio audio/COM devices, refresh and reapply settings. The application does not choose an unrelated device silently.
- **Map tiles fail:** return to default OSM or check custom/local URL, required key, connectivity and attribution. Previously cached tiles only cover downloaded areas/zooms.
- **Remote changes denied:** sign in using the lock button in that browser. A different computer's local session does not grant access.
- **Messages/notifications missing:** check routes, verification, acknowledgements, retention, quiet hours, cooldowns and provider credentials. Use diagnostics without treating a browser connection as RF proof.

## Updates, data, backups and deployment

About/Help shows version/build, attribution, diagnostics, update information and guide links. **What's new** appears once after an application update and identifies the version and changes. Supported Windows setup releases can download an installer and show download/launch/reconnection progress. Quit or stop transmit before manually replacing a running development installation. Development builds do not automatically install stable-channel updates.

Stable v1.12.0 and the modem development application use separate executables, installation/data directories and configuration. The development default dashboard is **127.0.0.1:14502**. Its Windows data directory is **%LOCALAPPDATA%/APRSPropViewelopment**. The stable/default deployment port may differ; use the address configured for that installation. Do not copy live database files during writes; use supported exports or stop the application for a full data-directory backup. Configuration export/import does not substitute for backing up credentials and the database.

Source, Windows installer/portable, Linux/Raspberry Pi service, Docker and macOS workflows are documented in README and the deployment guides. Run the development modem on supported audio/serial dependencies and verify device access for the account running it. A headless server does not gain browser GPS or radio audio merely because a dashboard is open remotely.

## MQTT, callbook and integration

MQTT publishes configured propagation, station, alert/event and Home Assistant discovery/state data. Set broker, port, topic prefix, credentials, device identity and watched callsigns. Keep Home Assistant discovery identifiers stable and verify a broker subscription when diagnosing delivery. MQTT configuration reconnects live when supported by the save feedback.

Callbook lookup supports configured QRZ/HamQTH credentials and provider selection. Integration availability, source health and credentials are independent of APRS packet reception. Configuration and analytics export/import support backups and external work; protect exported settings containing credentials. The HTTP dashboard/API remains subject to the same public/operator access rules.

## More information

Use **About/Help â†’ Illustrated Quick Start** for the guided tour. The in-app guide and Full HTML Documentation are generated from this guide. Source-distribution companions provide [public-hosting details](PUBLIC_HOSTING.md), [modem test instructions](DEVELOPMENT_MODEM.md), [Linux/Raspberry Pi deployment](linux-raspberry-pi.md), and [Docker deployment](docker.md). License, trademarks and bundled third-party notices remain applicable; the modem is an original implementation, not GrayWolf or Dire Wolf source.
