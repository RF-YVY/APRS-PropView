#!/usr/bin/env python3
"""Build a Linux executable on the target Linux CPU architecture."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build():
    if not sys.platform.startswith('linux'):
        raise SystemExit('Run this builder on Linux, on the target CPU architecture.')
    subprocess.check_call([sys.executable, str(ROOT / 'native/build_modem.py')])
    subprocess.check_call([
        sys.executable, '-m', 'PyInstaller', '--name', 'APRSPropView',
        '--noconfirm', '--clean', '--onefile', '--console',
        '--specpath', str(ROOT / 'build/linux'), '--workpath', str(ROOT / 'build/linux/work'),
        '--distpath', str(ROOT / 'dist'),
        '--add-data', f"{ROOT / 'static'}{os.pathsep}static",
        '--add-data', f"{ROOT / 'config.toml.example'}{os.pathsep}.",
        '--add-binary', f"{ROOT / 'native/bin/libpropview_modem.so'}{os.pathsep}native/bin",
        '--collect-submodules', 'uvicorn', '--collect-submodules', 'fastapi',
        '--collect-data', 'certifi', '--hidden-import', 'serial.tools.list_ports',
        '--hidden-import', 'sounddevice', '--hidden-import', 'netCDF4',
        str(ROOT / 'main.py'),
    ], cwd=ROOT)
    print('Built:', ROOT / 'dist/APRSPropView')
    print('Install system PortAudio (libportaudio2) on the target machine.')


if __name__ == '__main__':
    build()
