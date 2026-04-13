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
ICON_FILE = None  # Set to path of .ico file if desired

def check_pyinstaller():
    """Ensure PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("  PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  PyInstaller installed.")

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
        # Collect all submodules
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "fastapi",
        # Console mode (shows log output)
        "--console",
    ]

    if ICON_FILE and Path(ICON_FILE).exists():
        args.extend(["--icon", str(ICON_FILE)])

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
