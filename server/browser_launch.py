"""Browser discovery and launch helpers for opening the PropView UI."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class BrowserCandidate:
    id: str
    name: str
    windows_paths: tuple[str, ...] = ()
    mac_app: str = ""
    linux_commands: tuple[str, ...] = ()


BROWSER_CANDIDATES: tuple[BrowserCandidate, ...] = (
    BrowserCandidate(
        id="edge",
        name="Microsoft Edge",
        windows_paths=(
            r"{PROGRAMFILES}\Microsoft\Edge\Application\msedge.exe",
            r"{PROGRAMFILES(X86)}\Microsoft\Edge\Application\msedge.exe",
            r"{LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe",
        ),
        mac_app="Microsoft Edge",
        linux_commands=("microsoft-edge", "microsoft-edge-stable", "msedge"),
    ),
    BrowserCandidate(
        id="chrome",
        name="Google Chrome",
        windows_paths=(
            r"{PROGRAMFILES}\Google\Chrome\Application\chrome.exe",
            r"{PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
            r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
        ),
        mac_app="Google Chrome",
        linux_commands=("google-chrome", "google-chrome-stable", "chrome"),
    ),
    BrowserCandidate(
        id="firefox",
        name="Mozilla Firefox",
        windows_paths=(
            r"{PROGRAMFILES}\Mozilla Firefox\firefox.exe",
            r"{PROGRAMFILES(X86)}\Mozilla Firefox\firefox.exe",
            r"{LOCALAPPDATA}\Mozilla Firefox\firefox.exe",
        ),
        mac_app="Firefox",
        linux_commands=("firefox",),
    ),
    BrowserCandidate(
        id="brave",
        name="Brave",
        windows_paths=(
            r"{PROGRAMFILES}\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"{PROGRAMFILES(X86)}\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"{LOCALAPPDATA}\BraveSoftware\Brave-Browser\Application\brave.exe",
        ),
        mac_app="Brave Browser",
        linux_commands=("brave-browser", "brave"),
    ),
    BrowserCandidate(
        id="opera",
        name="Opera",
        windows_paths=(
            r"{LOCALAPPDATA}\Programs\Opera\opera.exe",
            r"{PROGRAMFILES}\Opera\launcher.exe",
            r"{PROGRAMFILES(X86)}\Opera\launcher.exe",
        ),
        mac_app="Opera",
        linux_commands=("opera",),
    ),
    BrowserCandidate(
        id="chromium",
        name="Chromium",
        windows_paths=(
            r"{LOCALAPPDATA}\Chromium\Application\chrome.exe",
            r"{PROGRAMFILES}\Chromium\Application\chrome.exe",
        ),
        mac_app="Chromium",
        linux_commands=("chromium", "chromium-browser"),
    ),
    BrowserCandidate(
        id="safari",
        name="Safari",
        mac_app="Safari",
    ),
)


def browser_ids() -> set[str]:
    return {candidate.id for candidate in BROWSER_CANDIDATES}


def available_browsers() -> list[dict[str, str]]:
    browsers = [{"id": "", "name": "System Default"}]
    for candidate in BROWSER_CANDIDATES:
        if _resolve_candidate(candidate):
            browsers.append({"id": candidate.id, "name": candidate.name})
    return browsers


def open_url(url: str, browser_id: str = "") -> bool:
    browser_id = (browser_id or "").strip().lower()
    if browser_id:
        candidate = _candidate_by_id(browser_id)
        if candidate and _open_with_candidate(candidate, url):
            return True
    return webbrowser.open(url)


def _candidate_by_id(browser_id: str) -> Optional[BrowserCandidate]:
    return next((candidate for candidate in BROWSER_CANDIDATES if candidate.id == browser_id), None)


def _resolve_candidate(candidate: BrowserCandidate) -> Optional[str]:
    system = platform.system().lower()
    if system == "windows":
        return _first_existing_path(_expand_windows_path(path) for path in candidate.windows_paths)
    if system == "darwin":
        return candidate.mac_app if candidate.mac_app and _mac_app_exists(candidate.mac_app) else None
    return _first_command(candidate.linux_commands)


def _open_with_candidate(candidate: BrowserCandidate, url: str) -> bool:
    system = platform.system().lower()
    try:
        if system == "windows":
            path = _resolve_candidate(candidate)
            if path:
                subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        elif system == "darwin":
            if candidate.mac_app and _mac_app_exists(candidate.mac_app):
                subprocess.Popen(["open", "-a", candidate.mac_app, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        else:
            command = _resolve_candidate(candidate)
            if command:
                subprocess.Popen([command, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
    except OSError:
        return False
    return False


def _expand_windows_path(template: str) -> str:
    path = template
    for key, value in os.environ.items():
        path = path.replace(f"{{{key.upper()}}}", value)
    return path


def _first_existing_path(paths: Iterable[str]) -> Optional[str]:
    for path in paths:
        if path and Path(path).is_file():
            return path
    return None


def _first_command(commands: Iterable[str]) -> Optional[str]:
    for command in commands:
        if shutil.which(command):
            return command
    return None


def _mac_app_exists(app_name: str) -> bool:
    return Path(f"/Applications/{app_name}.app").exists() or Path(f"/System/Applications/{app_name}.app").exists()
