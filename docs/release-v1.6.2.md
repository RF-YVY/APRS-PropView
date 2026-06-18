# APRS PropView v1.6.2

Released: June 18, 2026

## Highlights

- Fixed the in-app Windows update handoff so the browser is less likely to report a false download error while APRS PropView is intentionally shutting down.
- Changed the update helper to avoid Windows Restart Manager relaunch behavior and let the installer's normal post-install launch checkbox control startup.
- Set the installer post-install launch working directory to the installed APRS PropView folder.

## Upgrade Notes

- Windows users can install fresh with `APRSPropViewSetup-1.6.2.exe` or update from the About tab when the setup asset is attached to the GitHub release.
- During an in-app update, the old browser tab may remain open after the server closes. Open the new dashboard tab/window after APRS PropView relaunches.
- Linux and Raspberry Pi installs should pull the updated repository, rerun `scripts/install_linux.sh`, and restart the systemd service.

## Verification

- Python syntax checks for update and startup modules.
- JavaScript syntax checks for dashboard update UI.
- Windows PyInstaller one-file executable build.
- Windows Inno Setup installer build.
