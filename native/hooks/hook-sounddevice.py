"""Bundle the sounddevice audio backend for the current build host."""
from PyInstaller.utils.hooks import collect_dynamic_libs
import importlib.util
binaries = collect_dynamic_libs('_sounddevice_data') if importlib.util.find_spec('_sounddevice_data') else []
hiddenimports = ['_sounddevice', '_cffi_backend']
