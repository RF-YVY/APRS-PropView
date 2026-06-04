#!/usr/bin/env python3
"""Build the APRS PropView Windows setup executable.

Requires Inno Setup 6:
    winget install JRSoftware.InnoSetup

Usage:
    python build_installer.py

This produces dist/APRSPropViewSetup-<version>.exe.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
APP_EXE = DIST_DIR / "APRSPropView.exe"
ISS_FILE = PROJECT_ROOT / "deploy" / "APRSPropView.iss"


def read_version() -> str:
    main_text = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', main_text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read APP_VERSION from main.py")
    return match.group(1)


def find_iscc() -> Path:
    candidates = [
        PROJECT_ROOT / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    try:
        result = subprocess.run(
            ["where", "ISCC.exe"],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            candidate = Path(line.strip())
            if candidate.exists():
                return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    raise RuntimeError(
        "Inno Setup compiler was not found. Install it with "
        "`winget install JRSoftware.InnoSetup`, then rerun this script."
    )


def ensure_app_exe(skip_build: bool) -> None:
    if APP_EXE.exists() and skip_build:
        return
    if APP_EXE.exists():
        return
    print("APRSPropView.exe not found; building it first.")
    subprocess.check_call([sys.executable, "build_exe.py"], cwd=PROJECT_ROOT)


def build_installer(skip_build: bool = False) -> Path:
    version = read_version()
    ensure_app_exe(skip_build)

    if not APP_EXE.exists():
        raise RuntimeError(f"Expected app executable not found: {APP_EXE}")
    if not ISS_FILE.exists():
        raise RuntimeError(f"Installer script not found: {ISS_FILE}")

    iscc = find_iscc()
    print(f"Using Inno Setup compiler: {iscc}")
    print(f"Building APRS PropView setup v{version}")

    subprocess.check_call(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            str(ISS_FILE),
        ],
        cwd=PROJECT_ROOT,
    )

    setup_path = DIST_DIR / f"APRSPropViewSetup-{version}.exe"
    if not setup_path.exists():
        raise RuntimeError(f"Installer build completed but output was not found: {setup_path}")
    size_mb = setup_path.stat().st_size / (1024 * 1024)
    print(f"\nInstaller built: {setup_path}")
    print(f"Size: {size_mb:.1f} MB")
    return setup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build APRS PropView Windows installer.")
    parser.add_argument(
        "--skip-exe-build",
        action="store_true",
        help="Use the existing dist/APRSPropView.exe instead of invoking build_exe.py.",
    )
    args = parser.parse_args()
    try:
        build_installer(skip_build=args.skip_exe_build)
    except Exception as exc:
        print(f"\nInstaller build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
