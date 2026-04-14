# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.lifespan.off', 'websockets', 'aiosqlite', 'aprslib', 'serial', 'serial.tools', 'serial.tools.list_ports', 'geopy', 'geopy.distance', 'pystray', 'pystray._win32']
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('fastapi')


a = Analysis(
    ['C:\\Users\\NCFI Student\\aprs-propview\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\NCFI Student\\aprs-propview\\static', 'static'), ('C:\\Users\\NCFI Student\\aprs-propview\\server', 'server'), ('C:\\Users\\NCFI Student\\aprs-propview\\config.toml.example', '.')],
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
    version='C:\\Users\\NCFI Student\\aprs-propview\\version_info.txt',
    icon=['C:\\Users\\NCFI Student\\aprs-propview\\ico\\favicon.ico'],
    manifest='C:\\Users\\NCFI Student\\aprs-propview\\APRSPropView.manifest',
)
