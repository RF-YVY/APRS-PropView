# APRS PropView changelog

## v1.14.2

Released: October 27, 2026.

- Security audit and fixes. Updating is recommended for all users.

## v1.14.1 — one APRS-IS to RF control

Released: October 24, 2026.

- [FIX] Removed the duplicate APRS-IS → RF checkbox from the built-in modem. Settings → Radio & TNC → IGate is the single place to enable or disable gating.
- [FIX] Built-in modem routing now follows the IGate controls and its general RF transmit enable. Old modem-specific gating flags no longer block or override the IGate setting.
- [FIX] IGate master and direction changes apply live, including when IGate was disabled at startup. Both gating directions stop when the IGate master switch is off.
- [FIX] Updated setup guidance and documentation to match the single control. New installations still default APRS-IS → RF to off; saved IGate choices are retained.
- [FIX] Corrected the About release date and current documentation; About now receives its date from release metadata when documentation is generated.


## v1.14.0 — enhanced receiver and clearer operating controls

- [NEW] Integrated the enhanced Bell 202 receiver proven in Dev modem: 132 parallel timing and tone-decision lanes, varied filter windows, tone offsets and pre/de-emphasis hypotheses, and adaptive clock tracking.
- [NEW] Production runs one native receiver, with bounded queues and frame buffers. The legacy comparison engine and experimental bit-repair search are not included. A repeatable processing benchmark is available for Windows, Linux/ARM64 and macOS; physical Raspberry Pi/audio performance still requires hardware validation.
- [NEW] Built-in modem APRS-IS → RF gating is now an explicit opt-in, off by default. Modem TX and IGate IS→RF must also be enabled, and existing message routing and duplicate checks still apply.
- [FIX] Removed the offline Test with a WAV recording section from the production modem window. Internal offline regression tests and packaged self-tests remain available to developers.
- [FIX] Enable RF transmission and Wait for clear channel are larger, adjacent controls in a highlighted panel; transmit setup starts expanded and stacks on small screens. Existing TX opt-in, clear-channel default and saved settings are preserved.
- [FIX] Setup guidance recognizes built-in modem reception, beaconing, digipeating and permitted gated-transmit routes without requiring a duplicate Serial/TCP RF port.
- [FIX] Desktop and mobile uptime roll over to DD:HH:MM:SS at 24 hours, retaining HH:MM:SS below one day.
- [FIX] Added the visible word Login beside the map-toolbar lock icon.
- [FIX] Updated release notices, help, native version metadata and platform release packaging for v1.14.0.


## v1.13.1 — text encoding correction

Released October 23, 2026.

- Repaired corrupted Unicode characters throughout the application, settings, modem help, weather text, Markdown guides and generated changelog/documentation pages.
- Fixed the View, Stations, Layers and Appearance dropdown indicators. CSS chevrons now use encoding-independent character escapes.
- Repaired both single and repeated UTF-8/Windows-code-page conversion errors while preserving intended symbols and emoji.
- Made text-file encoding explicit in maintenance/configuration code, added UTF-8 editor defaults, and added regression checks for invalid UTF-8 and common corruption patterns.
- Regenerated bundled documentation from the corrected Markdown sources and rebuilt platform packages. The experimental-modem disclaimer and the full changes since v1.11.1 remain included.

## v1.13.0 — changes since v1.11.1

Released October 23, 2026. This release consolidates the unpublished v1.12.0 work and the v1.13.0 development series into one public release.

### Experimental built-in soundcard modem

**The built-in modem is experimental. Further radio and hardware testing is needed on Linux, Raspberry Pi and macOS. Reception, transmission and PTT behavior may vary by platform and audio interface.** Software tests are not a substitute for validating your radio setup.

- Added an original native 1200-baud Bell 202/AFSK modem with AX.25 framing, FCS checking, HDLC bit stuffing and NRZI encoding/decoding. External KISS serial, KISS TCP and AGWPE connections remain available.
- Added soundcard reception with selectable radio audio input and mono/left or right stereo channel. Four decoder lanes attempt reception with different thresholds.
- Added input level, peak, clipping, carrier detection, decoded-frame, CRC-failure, dropped-block and audio-overflow diagnostics, with explanations of what the readings mean.
- Added offline 16-bit PCM WAV decoding and a downloadable generated test recording. Imported test recordings do not enter the live RF map and cannot trigger digipeating, iGating or message acknowledgements.
- Added native transmit audio encoding, selectable radio audio output/channel, adjustable amplitude, **Transmit delay (ms)** and transmit tail. Delay accepts 50–1500 ms, defaults to 300 ms, and supplies opening flags before packet data.
- Added RIGblaster NOMIC/serial RTS, serial DTR and radio VOX PTT modes, plus an RF test-packet control. The unused serial control line stays low.
- Added Stop TX, bounded audio/PTT operation, a ten-second keying watchdog, frame validation and error reporting for audio underruns and unavailable interfaces.
- Added **Wait for clear channel**, enabled by default. Its checkbox sits beside its label, changes apply immediately, the selected mode is visible, and the choice survives restarts. Carrier detection requires sustained tone evidence to reduce busy indications from short noise peaks.
- Saved RX and enabled TX settings restore at launch, matching audio interfaces by name and host API. Stop RX disables reception auto-start; Stop TX disables TX auto-start. Transmission is initially disabled until configured and enabled.
- Integrated the modem into RF connection status, source health, manual transmission readiness, configured beacons, messages, OTA spots and digipeating without requiring a duplicate external RF port. APRS-IS-to-RF gating remains disabled on the built-in modem interface.
- Moved modem setup into **Settings → Radio & TNC → RF Ports**. Added an experimental-platform notice directly in the modem window.

### Remote access, web server and mobile dashboard

- Restored the normal release port to **14501** and default listening address to **0.0.0.0**. The server accepts connections on local, LAN and Tailscale interfaces instead of being limited to loopback.
- The desktop dashboard is at `/`; the mobile page is at `/mobile` on the same server and port. Use `http://<host-or-Tailscale-IP>:14501/` or `http://<host-or-Tailscale-IP>:14501/mobile`.
- On the first v1.13.0 startup, saved loopback-only defaults are migrated to the shared listener, and the former dev port 14502 is migrated to 14501. Explicit environment overrides and other custom ports remain supported. Subsequent user settings changes are preserved.
- Removed the dev-launch behavior that discarded deployment settings. Container and service deployments retain their configured host, port, config and database locations.
- Mobile maps now use key-free OpenStreetMap tiles, including a locally styled dark map.
- Existing host firewall rules and Tailscale access policies still govern access to the listening service.

### Operator access and privacy

- Public dashboards are read-only. Settings, private messages, transmission actions, configuration exports and update installation require an operator session.
- Added local operator-password setup and recovery without an online account. Passwords support 6–256 characters, and existing credentials continue to work.
- Added remote sign-in durations of 15 minutes, one hour or eight hours; session countdown, extension and immediate locking controls are available in the compact map-toolbar lock popover.
- Browsers opened by the host application can sign in automatically. This does not grant operator access to other browsers or public viewers.
- Added per-browser sessions, HttpOnly authentication cookies, origin/CSRF checks, sanitized public responses, private-message filtering and non-cacheable session-dependent API responses.
- Added an owner-only local shortcut handoff and single-use update-session handoff. Restart/update continuation does not unlock other browsers.
- Added terminal-based `--set-operator-password` for headless Linux/Pi/container installations; passwords are prompted without echo or command-line arguments.

### OTA activity spotting and messaging

- Added **Send OTA Activity Spot** on the map toolbar, with APSPOT command preview and routing for supported POTA, SOTA, WWFF and SIOTA references.
- Added editable operator callsign, activity/reference, frequency, mode, comment and RF/APRS-IS delivery selection, including validation and service instructions/credit.
- Added current-spot filtering and test-mode support.
- APRS-IS reception filters include replies to a selected spotting callsign without discarding the operator's configured filter. Relevant APSPOT replies are recorded and acknowledged with the corresponding sender identity.
- Callsign examples in editable fields and the illustrated setup guide now use W1AW or a fictitious placeholder. User-entered callsigns and creator/service credits are preserved.

### RF processing and source health

- Fixed KISS escaping of command bytes on channels 12 and 13.
- Fixed digipeater enabling after startup: the service remains available when the operator enables it in Settings.
- Digipeater callsign, aliases and duplicate-window changes now apply live rather than retaining startup values.
- Retained explicit alias matching and duplicate suppression. A request for WIDE2-2 requires that alias to be configured; the default WIDE1-1/WIDE2-1 aliases do not automatically authorize every WIDEn-N request.
- A connected receiver with no decoded packet this session is shown as listening. Stale data uses a yellow indicator and label; red indicates offline/error conditions. The combined health indicator follows the same distinction.
- Improved RF readiness/status integration for the built-in modem and preserved receive-only port restrictions.

### Map, settings and appearance

- Added a saved **Show RF lines** control and expanded line options under **Appearance**. RF lines respect source, station and time filters; APRS-IS packet animations remain temporary.
- Matched the Lines control sizing to adjacent Appearance controls.
- Added a custom header icon beside the application name/version. PNG, JPEG, WebP, GIF, BMP and ICO uploads up to 10 MB are normalized and resized proportionally to fit the header, preserving transparency where supported.
- Header-icon changes save immediately, survive restarts and include **Restore default icon**. Invalid uploads preserve the previously saved image.
- Weather/lightning enablement, location lookup and display options are visible in Basic Settings under **Alerts & Weather**.
- Fixed the NOAA Minimum Kp input step so the default threshold 5.00 is accepted.

### Updates, release notes and documentation

- Added download progress, installation guidance, relaunch handling and refresh of the existing browser tab for Windows updates.
- Preserved existing configuration/database files and local operator state across updates. Build scripts no longer delete unrelated artifacts or user data from the entire distribution directory.
- Added this consolidated Markdown changelog for GitHub, the PropView website and bundled documentation. The full changelog appears on first v1.13.0 use, including new installations, and remains pending until an operator acknowledges it.
- Rewrote the in-app Help & User Guide and full HTML documentation from a shared Markdown user guide, covering modem RX/TX, remote access, mobile use, spotting, weather, maps, integrations and troubleshooting.
- Added cross-platform setup, headless deployment, native-build and compatibility documentation.

### Linux, Raspberry Pi, macOS and packaging

- Added platform-aware native-library loading: Windows DLL, Linux `.so` and macOS `.dylib`. The native build script now uses MSVC on Windows and a host C++17 compiler on Linux/macOS, including native ARM builds.
- Serial PTT now accepts enumerated Unix device paths and preserves case; device conflicts remain blocked.
- Added a Linux executable builder and updated Windows/macOS packaging to include the native modem and required audio dependencies.
- macOS packaging includes a microphone usage declaration, audio-input entitlement and final bundle signing. The incompatible background-thread menu-bar icon is omitted; the browser dashboard remains available.
- Docker builds the modem for the image architecture, includes system PortAudio and uses the intended listening port and persistent volume. Images target Linux amd64 and arm64.
- Added platform CI for Windows, Linux x86-64/ARM64 and Intel/Apple Silicon macOS, with regression suites, native modem tests and packaging/startup checks.
- Windows and Linux source suites and packaged modem/headless web smoke tests were exercised locally during remediation. Native Mac builds, physical Raspberry Pi/Mac USB audio and PTT performance, and 32-bit Pi support still require platform/hardware validation. Linux binaries must match the target architecture and compatible system-library versions; rebuild from source when needed.

### Upgrade notes

- Windows: install `APRSPropViewSetup-1.13.0.exe` over the stable installation, or replace the portable `APRSPropView.exe`. Quit the existing application first. Existing stable data remains in place; the separate dev installation/data is not silently imported.
- Linux/Pi/macOS: update the source and dependencies, build the native modem on the target host, then restart or rebuild the application. See [cross-platform setup](docs/CROSS_PLATFORM_SETUP.md).
- Docker: use the v1.13.0 image once its publishing workflow completes, or build the included Dockerfile. Supply device/group access when using serial/audio hardware.
- Configure your own licensed station identity before transmitting. For remote viewing, use the host's LAN/Tailscale address, not localhost; the mobile path is `/mobile`.

## v1.11.1 — previous published baseline

Released October 14, 2026. Preserved saved MQTT passwords during unrelated settings saves, corrected Safari settings-overlay clipping, and improved Windows weather HTTPS certificate handling. Those fixes remain included in v1.13.0.
