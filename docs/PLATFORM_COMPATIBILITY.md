# Platform compatibility review

Reviewed 2026-10-23 against development source 1.13.0-dev.11.
This is an audit, not certification of hardware or a completed portability patch.

## Remediation update (2026-10-23)

The findings below are the original audit. Source remediation has since added:

- Host-native Linux `.so` and macOS `.dylib` compilation/loading alongside Windows DLL support.
- Enumerated, case-preserving Unix serial PTT paths and conflict checks.
- Explicit deployment mode preserving container/service networking and data settings, plus console password setup.
- A native Linux executable builder and a Docker native build with system PortAudio.
- A separate macOS development bundle identity, modem bundling, microphone declaration, audio-input entitlement and final signing. Its background tray is omitted to avoid Cocoa thread violations.
- Non-destructive macOS packaging and platform-aware audio packaging hooks.
- CI jobs for Windows, Linux x86-64/ARM64 and macOS Intel/Apple Silicon, including native self-tests and packaged Linux/macOS checks.

Windows and Ubuntu WSL now both pass all 236 regression tests. Linux native modem
encode/decode and real headless startups from both source and the packaged Linux
executable also pass. Windows source and packaged headless startup and packaged
modem self-tests pass as well. An additional macOS packaging regression test
passes on both hosts with the actual Mac toolchain calls mocked. Packaging/hardware
status and installation instructions are maintained in [CROSS_PLATFORM_SETUP.md](CROSS_PLATFORM_SETUP.md).
No physical Pi or Mac validation has been performed; newly configured CI jobs have
not been dispatched from this workstation. The original limitations below describe
the pre-remediation code, not the current implementation.

## Current status

| Platform | Core protocols and dashboard | Built-in soundcard modem | Packaging |
| --- | --- | --- | --- |
| Linux x86_64 | Protocol/config smoke checks passed under Ubuntu WSL; full web stack untested there | Blocked by Windows DLL loader/build and COM-only PTT | Docker launch configuration conflicts with dev bootstrap |
| Raspberry Pi / Linux ARM64 | Expected to be portable at the Python layer; not tested on Pi | Requires ARM64 native build, platform loader, audio dependencies and serial-path support | Workflow declares linux/arm64, but that does not establish working runtime support |
| Raspberry Pi / 32-bit ARM | Not tested; dependency installation and performance need separate validation | No native ARM build provided | Not included in container workflow targets |
| macOS Intel / Apple Silicon | Python layer appears portable; no Mac runtime test performed | Native macOS library and packaging missing; serial PTT rejects Unix paths | Existing .app builder needs modem, privacy, event-loop and dev-identity updates |

## Confirmed blockers and gaps

1. **Native modem library is Windows-only as shipped.** Both `server/software_modem.py` and `server/modem_transmit.py` load `native/bin/propview_modem.dll`. `native/build_modem.py` uses vswhere, vcvars64.bat, cmd and MSVC. The C++ source has a non-Windows export branch and no obvious Windows-only DSP dependencies, but this does not prove successful compilation or real-time performance on other architectures. Add host-native `.so` and `.dylib` builds and a shared platform-aware loader. Each artifact must match the Python process architecture.

2. **Serial PTT rejects Linux/macOS device names.** `ModemTransmitter.configure()` accepts only `COM...` and uppercases the saved port. Unix device paths are case-sensitive. Accept an exact path returned by serial enumeration and preserve it; keep Windows-specific normalization on Windows. External KISS serial configuration does not have this modem-specific COM restriction.

3. **Container entry point overrides deployment configuration.** `main.py` calls `_development_environment()` on normal entry. This removes all existing `PROPVIEW_*` variables and forces loopback port 14502 and a home-directory data path. The Dockerfile/Compose expect 0.0.0.0:14501 and `/data`. Consequently the published port, health check and persistent volume do not match the application's dev bootstrap. Preserve explicit deployment overrides while retaining sensible isolated dev defaults.

4. **Docker image omits modem artifacts and audio setup.** The Dockerfile never copies/builds `native`. It does not install system PortAudio, nor configure soundcard/serial device access. A core web deployment can be separated from soundcard modem support; enabling soundcard support needs an explicit host audio/device configuration. Installing the Python sounddevice package alone is not sufficient on ordinary Linux installations.

5. **macOS builder is behind the dev feature set.** `build_macos.py` has no native-library build/bundle step or microphone usage description. It retains the stable app name/bundle identity and reports a stable data location, while the dev bootstrap uses `~/APRSPropViewDevelopment`. It also recursively deletes the entire build and dist directories, which may contain other artifacts. Preserve artifacts and align bundle identity, data paths, microphone permissions and native dependencies with the dev application.

6. **macOS tray event-loop mismatch.** `main.py` starts `pystray.Icon.run()` in a background thread. pystray requires the macOS icon loop on the main thread. Rework desktop event-loop integration or omit the tray on unsupported configurations. Headless Linux also needs tray/GUI imports to degrade cleanly and a documented non-GUI operator-password setup path.

7. **Windows audio packaging hook.** `native/hooks/hook-sounddevice.py` assumes `libportaudio64bit.dll`. It must not be reused unchanged for other operating systems/architectures.

8. **Coverage does not establish platform support.** CI declares Ubuntu regression tests and amd64/arm64 image publishing, but includes native tests without a Linux native build. The dev container bootstrap conflicts with the CI health check. There is no macOS or physical Pi/audio test matrix. The built-in update installer is explicitly Windows-only; other platforms need their own update procedure.

## Checks performed

- Read platform branches, requirements, native DSP code, modem loader/transmitter, Docker/Compose, CI workflow, desktop startup and macOS packaging.
- Ubuntu WSL Linux x86_64 / Python 3.14.4: parsed all 45 top-level server/startup/macOS-build Python files successfully.
- Executed Linux smoke checks: AX.25 encode/decode, KISS framing/parser, APRS parsing, WIDE1-1 digipeating and config TOML save/load all passed.
- Attempted to load the actual bundled modem DLL under Linux: failed with `OSError: invalid ELF header`.
- Full Linux web/native tests were not run: this WSL environment lacks FastAPI, sounddevice, Pillow, netCDF4 and a C++ compiler. No dependencies were installed during this audit.
- Docker daemon is unavailable on this host, so no container runtime test was possible.
- No macOS or Raspberry Pi hardware was available; audio quality, latency, CPU use, USB audio and PTT behavior remain untested there.
- The previous 231-test result was on Windows and must not be presented as cross-platform validation.

## Suggested implementation order

1. Preserve deployment overrides; make container networking/storage and headless operation work.
2. Add portable native compiler commands and platform library selection.
3. Remove COM-only PTT assumptions; verify Unix serial permissions and line control.
4. Update macOS packaging, permissions, identity and event-loop handling.
5. Add Linux x86_64, Linux ARM64 and macOS CI builds/native round trips.
6. Test real RX/TX with USB audio and serial PTT on a physical Pi and Mac before claiming full modem compatibility.

## Primary documentation consulted

- [sounddevice installation](https://python-sounddevice.readthedocs.io/en/0.5.4/installation.html): Linux PortAudio installation; Windows/macOS bundled library behavior.
- [pySerial tools](https://pyserial.readthedocs.io/en/latest/tools.html): enumerated device paths across operating systems.
- [pystray usage](https://github.com/moses-palmer/pystray/blob/master/docs/usage.rst): macOS main-thread requirement.
- [Apple microphone usage description](https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSMicrophoneUsageDescription): microphone privacy declaration.
- [PyInstaller](https://pyinstaller.org/en/latest/): builds must be produced on their target operating system; it is not a general cross-compiler.
