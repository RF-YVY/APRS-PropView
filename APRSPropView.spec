# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(__file__).resolve().parent

datas = [
    (str(PROJECT_ROOT / 'static'), 'static'),
    (str(PROJECT_ROOT / 'server'), 'server'),
    (str(PROJECT_ROOT / 'config.toml.example'), '.'),
]
datas += collect_data_files('certifi')

hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'websockets',
    'aiosqlite',
    'aprslib',
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
    'geopy',
    'geopy.distance',
    'pystray',
    'pystray._win32',
    'certifi',
]
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('fastapi')


a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='APRSPropView',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(PROJECT_ROOT / 'version_info.txt'),
    icon=[str(PROJECT_ROOT / 'ico' / 'favicon.ico')],
    manifest=str(PROJECT_ROOT / 'APRSPropView.manifest'),
)
