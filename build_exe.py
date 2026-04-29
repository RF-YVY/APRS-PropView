#!/usr/bin/env python3
"""Build APRS PropView into a standalone one-file executable using PyInstaller.

Usage:
    pip install pyinstaller
    python build_exe.py

This creates dist/APRSPropView.exe - a single portable executable.
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
STATIC_DIR = PROJECT_ROOT / "static"
ICON_FILE = PROJECT_ROOT / "ico" / "favicon.ico"

def check_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("  PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  PyInstaller installed.")


def _rebuild_ico_png(ico_path):
    """Rebuild the ICO file with PNG-compressed entries (needed for Explorer)."""
    try:
        from PIL import Image
        import struct, io

        src = Image.open(ico_path)
        sizes = sorted(src.info.get("sizes", set()), key=lambda s: s[0])
        if not sizes:
            sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

        entries = []
        for sz in sizes:
            frame = src.copy()
            frame = frame.resize(sz, Image.Resampling.LANCZOS)
            frame = frame.convert("RGBA")
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            png_data = buf.getvalue()
            w = sz[0] if sz[0] < 256 else 0
            h = sz[1] if sz[1] < 256 else 0
            entries.append((w, h, png_data))

        # Write ICO file
        num = len(entries)
        header = struct.pack("<HHH", 0, 1, num)
        offset = 6 + num * 16
        dir_entries = b""
        data_parts = b""
        for w, h, png_data in entries:
            size = len(png_data)
            dir_entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, size, offset)
            data_parts += png_data
            offset += size

        with open(ico_path, "wb") as f:
            f.write(header + dir_entries + data_parts)
        print(f"  Rebuilt ICO with PNG compression ({len(entries)} sizes)")
    except ImportError:
        print("  Pillow not available — using existing ICO as-is")
    except Exception as e:
        print(f"  Warning: Could not rebuild ICO: {e}")


def _write_manifest(path):
    """Write a custom application manifest with unique assemblyIdentity.

    This prevents Windows from matching the exe against the PyInstaller
    bootloader's AppCompat signature and substituting a Python icon.
    """
    content = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity
    type="win32"
    name="WickerMade.APRSPropView"
    version="1.3.0.0"
    processorArchitecture="amd64"
  />
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"/>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">permonitorv2,permonitor</dpiAwareness>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls"
        version="6.0.0.0" processorArchitecture="*"
        publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated custom application manifest")


def _write_version_info(path):
    """Write a Windows VERSIONINFO resource file for PyInstaller."""
    content = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 3, 0, 0),
    prodvers=(1, 3, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Wicker Made, LLC'),
            StringStruct(u'FileDescription', u'APRS PropView - VHF Propagation Monitor'),
            StringStruct(u'FileVersion', u'1.3.0.0'),
            StringStruct(u'InternalName', u'APRSPropView'),
            StringStruct(u'OriginalFilename', u'APRSPropView.exe'),
            StringStruct(u'ProductName', u'APRS PropView'),
            StringStruct(u'ProductVersion', u'1.3.0.0'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Generated version info resource")

def build():
    print("\n=== APRS PropView — Build Executable ===\n")
    check_pyinstaller()

    # Clean previous builds
    for d in ["build", "dist"]:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p)
            print(f"  Cleaned {d}/")

    spec_file = PROJECT_ROOT / "APRSPropView.spec"
    if spec_file.exists():
        spec_file.unlink()

    # Build args
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "APRSPropView",
        "--noconfirm",
        "--clean",
        # Include static files
        "--add-data", f"{STATIC_DIR}{os.pathsep}static",
        # Include server package
        "--add-data", f"{PROJECT_ROOT / 'server'}{os.pathsep}server",
        # Include config example
        "--add-data", f"{PROJECT_ROOT / 'config.toml.example'}{os.pathsep}.",
        # Hidden imports for dynamic loading
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.lifespan.off",
        "--hidden-import", "websockets",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "aprslib",
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools",
        "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "geopy",
        "--hidden-import", "geopy.distance",
        "--hidden-import", "pystray",
        "--hidden-import", "pystray._win32",
        # Collect all submodules
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "fastapi",
        # Console mode (shows log output)
        "--console",
    ]

    if ICON_FILE and Path(ICON_FILE).exists():
        # Rebuild ICO with PNG compression (required for Windows Explorer)
        _rebuild_ico_png(ICON_FILE)
        args.extend(["--icon", str(ICON_FILE)])

    # Generate version info resource so Windows associates the icon properly
    version_file = PROJECT_ROOT / "version_info.txt"
    _write_version_info(version_file)
    args.extend(["--version-file", str(version_file)])

    # Custom manifest with unique assemblyIdentity — prevents Windows from
    # matching the bootloader against Python's AppCompat cache entry
    manifest_file = PROJECT_ROOT / "APRSPropView.manifest"
    _write_manifest(manifest_file)
    args.extend(["--manifest", str(manifest_file)])

    # One-file mode: single portable executable
    args.append("--onefile")
    args.append(str(MAIN_SCRIPT))

    print(f"\n  Running PyInstaller...\n")
    result = subprocess.run(args, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        dist_dir = PROJECT_ROOT / "dist"
        exe_path = dist_dir / "APRSPropView.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\n  \u2705 Build successful!")
            print(f"  Executable: {exe_path}")
            print(f"  Size:       {size_mb:.1f} MB")

            # Copy config example alongside for reference
            example_cfg = PROJECT_ROOT / "config.toml.example"
            if example_cfg.exists():
                shutil.copy2(example_cfg, dist_dir / "config.toml.example")
                print(f"  Copied config.toml.example to dist/")

            print(f"\n  To run: dist\\APRSPropView.exe")
            print(f"  On first run, config.toml is created next to the exe and the app starts immediately.\n")
        else:
            print(f"\n  ⚠ Build completed but exe not found at expected path.")
    else:
        print(f"\n  ❌ Build failed with return code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    build()
