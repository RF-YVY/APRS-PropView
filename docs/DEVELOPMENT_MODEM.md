# PropView 1.13.0: experimental built-in modem

**Experimental modem:** further testing is needed on Linux, Raspberry Pi and macOS. Performance may vary by platform and audio interface.

The paths below describe Windows. For Linux, Raspberry Pi, macOS and headless operation, see [Cross-platform setup](CROSS_PLATFORM_SETUP.md).

- App: APRS PropView (`APRSPropView.exe`).
- Install folder: `%LOCALAPPDATA%/Programs/APRS PropView`.
- Runtime data: `the installation folder beside the executable`.
- Dashboard: http://127.0.0.1:14501.
- Stable installation settings and data are preserved during upgrade. Separate development data is not imported automatically.

## First test

1. Install the release installer or launch its portable executable.
2. Optionally enable User login in Settings → Security and set a password in the browser. Configure your callsign/location in the application UI as needed.
3. Open **Settings → Radio & TNC → RF Ports → Configure Built-in Modem**.
4. Expand **Test with a WAV recording**. Download the generated test WAV, select it and click **Decode recording**. It should recover one synthetic N0CALL packet. Nothing is transmitted, played or inserted in the live map.
5. To receive radio audio, select the USB audio input (WASAPI preferred when available), choose left/mono or right, and click **Start receiving**. Settings are remembered; successful setup enables automatic reception on subsequent launches.
6. Check levels, clipping, dropped blocks and decoded packets. Live packets appear in the map and packet history.
7. **Stop** releases the input. Closing the modem window leaves reception running; quitting the application stops it.

Compare real receiver recordings with your existing TNC. Supported files: 16-bit PCM WAV, mono/stereo, 8-96 kHz, at most five minutes and 32 MB. The channel selector also applies to WAV decoding. Imported recordings stay offline and cannot trigger digipeating, gating or message acknowledgements.

Before installing a newer development build, use **Stop TX / disable** and quit the running development application to release its audio and PTT connections.

## Transmit testing with RIGblaster NOMIC

Start with a dummy load and a second receiver to verify PTT, tone level and packet reception. The software tests use mocked hardware; NOMIC hardware behavior still needs your validation.

1. Configure your actual station callsign. Start receiving from the local radio input so the channel-busy detector monitors the frequency you will transmit on.
2. Expand **Transmit setup (NOMIC / serial / VOX)**. Select the soundcard playback output physically connected to the NOMIC's audio input. Do not select a PC speaker or VB-CABLE unless that is deliberately part of your radio wiring.
3. Select **RIGblaster NOMIC (RTS)** and its USB/serial COM port. Both RTS and DTR start low; only RTS is asserted for this preset. Generic DTR and VOX modes are also available.
4. Begin with audio amplitude 0.20, TX delay 300 ms and tail 50 ms. Adjust audio level against your radio's deviation requirements; it does not set RF power.
5. Check **Enable RF transmission** and click **Apply transmit settings**. This does not itself generate a test packet, but normal configured beacons, messages, spots and digipeating can now use the modem.
6. **Send RF test packet** sends a single status packet from your configured callsign directly via this modem, without a digipeater path. Confirm it on another receiver/decoder. Normal PropView transmit functions use their existing packet paths.
7. **Stop TX / disable** cancels active audio, releases serial RTS/DTR and disables further transmissions. Stopping reception disables TX. Quitting preserves enabled RX/TX for automatic startup on the next launch. Stop RX and Stop TX save their disabled states. Closing the window leaves the selected operating state running.

Transmission waits for channel clear with a short randomized delay and fails without keying if the channel remains busy. Input decoding pauses while transmitting, then resynchronizes. Audio/serial PTT has a 10-second watchdog; VOX key release also depends on the radio's hang time. Output failures disable TX until settings are applied again. Audio output selection is explicit and never silently falls back to a different speaker. Internet-to-RF gating is off by default and is controlled only in Settings → Radio & TNC → IGate. The modem also requires its general RF transmit enable; no separate modem gating option is needed.

NOMIC references: https://www.westmountainradio.com/product_info.php?products_id=nomicu_comp_usb and https://www.westmountainradio.com/pdf/nomicman4.pdf . USB/serial adapters can briefly change control lines during port opening despite software preset states; verify your adapter/radio on a dummy load.

## Scope

Original experimental Bell 202 1200-baud modem: 132 receive decision/timing lanes, NRZI/HDLC decoding, CRC rejection, and native transmit encoding with continuous-phase AFSK. Serial RTS/DTR and VOX transmission are available only after explicit initial enablement. Existing external TNC features remain available. Only APRS UI frames are supported by the built-in transmitter.

Synthetic and independent reference-signal tests cover sample rates, moderate noise, tone imbalance, timing offsets, stereo selection, chunk boundaries and corrupt checksums. These are not a field-performance benchmark. Weak-signal, radio-specific and 24/7 reliability testing remain necessary. No claim of parity with mature modems is made.

The original native DSP uses C++17 and the available MSVC toolchain, avoiding another build-tool installation. No GrayWolf/Dire Wolf modem source is used. Python and PortAudio provide device access. DSP runs outside the audio callback on a worker thread with bounded queues. Modem/admin endpoints require the development browser's operator session.

## Build

Install Python requirements and MSVC x64 C++ Build Tools. Run `python native/build_modem.py`, `python -m pytest -q`, `python build_exe.py`, then `python build_installer.py --skip-exe-build` (Inno Setup 6 required). Run `dist/APRSPropViewDev.exe --modem-self-test` to verify the packaged decoder and PortAudio without opening audio devices or creating user data.

## Open-squelch receive audio and dashboard status

Open squelch is supported: ordinary hiss should read Channel: clear, while sustained APRS tones read busy. Development build 4 filters short noise peaks before starting the carrier hang timer. If a quiet channel remains busy, check for hum, feedback, or a continuous tone on the selected input; report it with a short WAV recording. RF test packets continue to defer while a carrier is detected.

No additional RF port in Settings is required for the built-in modem. Start receiving to show RF connected; enable and apply transmit settings to make manual RF transmissions available. Station beacons also require station coordinates.

### Optional channel wait

Transmit setup includes **Wait for clear channel**, checked by default. Uncheck it (applies immediately) to bypass carrier waiting for all built-in modem transmissions, including the test packet, beacons and messages. Carrier diagnostics continue running. The choice is saved across application restarts. Saved RX and enabled TX automatically resume at launch. Stop TX, frame validation and the PTT watchdog remain active in either mode.

## v1.14.0 production receiver

The enhanced receiver is integrated into the production modem with one native engine, bounded buffers and no reference decoder or soft-bit search. The offline WAV test section has been removed from the production window; the developer tests described above remain offline regression tools. Run `python scripts/benchmark_modem.py --seconds 10` to measure decoder processing cost on each target host. This measures processing time against a 20 ms audio block budget, not total application CPU. Physical Raspberry Pi audio and PTT testing remains necessary. The built-in modem transmit and clear-channel checkboxes are adjacent in an expanded highlighted panel.
