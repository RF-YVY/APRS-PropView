#!/usr/bin/env python3
"""Build APRS PropView into a macOS .app bundle using PyInstaller.

Run this script on macOS:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt pyinstaller pillow
    python build_macos.py

The output is dist/APRS PropView.app. On first launch, the packaged app stores
config.toml, propview.db, map_tile_cache/, and user_audio/ in:

    ~/Library/Application Support/APRS PropView/
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
STATIC_DIR = PROJECT_ROOT / "static"
SERVER_DIR = PROJECT_ROOT / "server"
CONFIG_EXAMPLE = PROJECT_ROOT / "config.toml.example"
ICON_SOURCE = PROJECT_ROOT / "ico" / "apple-touch-icon.png"
APP_NAME = "APRS PropView"
BUNDLE_ID = "com.wickermade.aprspropview"


def check_macos():
    if sys.platform != "darwin":
        print("  This builder must be run on macOS to produce a .app bundle.")
        print("  You can syntax-check it elsewhere, but PyInstaller .app output is macOS-only.")
        sys.exit(1)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401

        print(f"  PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("  PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  PyInstaller installed.")


def ensure_runtime_dependencies():
    missing = []
    for module_name, package_name in [
        ("paho.mqtt.client", "paho-mqtt>=1.6.1"),
        ("PIL", "pillow"),
    ]:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    if missing:
        print(f"  Installing missing build/runtime packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


def build_icns() -> Path | None:
    """Create a temporary .icns file from the project PNG icon when possible."""
    if not ICON_SOURCE.exists():
        print("  No PNG icon found; building without a custom macOS icon.")
        return None

    iconset = PROJECT_ROOT / "build" / "APRSPropView.iconset"
    icns = PROJECT_ROOT / "build" / "APRSPropView.icns"
    iconset.mkdir(parents=True, exist_ok=True)

    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    try:
        from PIL import Image

        src = Image.open(ICON_SOURCE).convert("RGBA")
        for size, filename in sizes:
            src.resize((size, size), Image.Resampling.LANCZOS).save(iconset / filename)
        subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
        print(f"  Generated macOS icon: {icns}")
        return icns
    except Exception as exc:
        print(f"  Warning: could not generate .icns icon: {exc}")
        return None


def clean_build_dirs():
    for name in ("build", "dist"):
        path = PROJECT_ROOT / name
        if path.exists():
            shutil.rmtree(path)
            print(f"  Cleaned {name}/")


def build():
    print("\n=== APRS PropView - Build macOS App ===\n")
    check_macos()
    ensure_pyinstaller()
    ensure_runtime_dependencies()
    clean_build_dirs()
    icon_file = build_icns()

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--specpath",
        str(PROJECT_ROOT / "build"),
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--add-data",
        f"{STATIC_DIR}{os.pathsep}static",
        "--add-data",
        f"{SERVER_DIR}{os.pathsep}server",
        "--add-data",
        f"{CONFIG_EXAMPLE}{os.pathsep}.",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.protocols.http",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "uvicorn.lifespan.off",
        "--hidden-import",
        "websockets",
        "--hidden-import",
        "aiosqlite",
        "--hidden-import",
        "aprslib",
        "--hidden-import",
        "serial",
        "--hidden-import",
        "serial_asyncio",
        "--hidden-import",
        "serial.tools",
        "--hidden-import",
        "serial.tools.list_ports",
        "--hidden-import",
        "paho",
        "--hidden-import",
        "paho.mqtt",
        "--hidden-import",
        "paho.mqtt.client",
        "--hidden-import",
        "geopy",
        "--hidden-import",
        "geopy.distance",
        "--hidden-import",
        "pystray",
        "--hidden-import",
        "pystray._darwin",
        "--hidden-import",
        "certifi",
        "--collect-data",
        "certifi",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "fastapi",
    ]
    if icon_file:
        args.extend(["--icon", str(icon_file)])

    codesign_identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "").strip()
    if codesign_identity:
        args.extend(["--codesign-identity", codesign_identity])

    args.append(str(MAIN_SCRIPT))

    print("\n  Running PyInstaller...\n")
    result = subprocess.run(args, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\n  Build failed with return code {result.returncode}")
        sys.exit(result.returncode)

    app_path = PROJECT_ROOT / "dist" / f"{APP_NAME}.app"
    if not app_path.exists():
        print(f"\n  Build finished, but {app_path} was not found.")
        sys.exit(1)

    print("\n  Build successful!")
    print(f"  App bundle: {app_path}")
    print("\n  To test locally:")
    print(f"    open {app_path!s}")
    print("\n  User data will be created in:")
    print("    ~/Library/Application Support/APRS PropView/")
    print("\n  This build is unsigned unless MACOS_CODESIGN_IDENTITY was set.\n")


if __name__ == "__main__":
    build()
