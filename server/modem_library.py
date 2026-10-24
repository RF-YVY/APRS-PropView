"""Locate host-native DSP libraries in source and packaged installations."""
import ctypes
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def library_name(platform=None):
    platform = platform or sys.platform
    if platform == 'win32':
        return 'propview_modem.dll'
    if platform == 'darwin':
        return 'libpropview_modem.dylib'
    if platform.startswith('linux'):
        return 'libpropview_modem.so'
    raise RuntimeError(f'Built-in modem is not supported on {platform}.')


def load_modem_library():
    path = ROOT / 'native' / 'bin' / library_name()
    try:
        return ctypes.CDLL(str(path))
    except OSError as exc:
        raise RuntimeError(
            f'Could not load modem library {path.name}. '
            'Source installs: run python native/build_modem.py on this computer. '
            'Packaged installs: use a build matching your OS and CPU architecture.'
        ) from exc
