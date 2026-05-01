"""GitHub release update checker for APRS PropView."""

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("propview.update")

GITHUB_REPO = "RF-YVY/APRS-PropView"
GITHUB_RELEASES_URL = "https://github.com/RF-YVY/APRS-PropView/releases"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def _normalize_version(value: str) -> str:
    value = (value or "").strip()
    if value.lower().startswith("v"):
        value = value[1:]
    value = value.lstrip(".-_ ")
    return value


def _version_key(value: str) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", _normalize_version(value))
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


class UpdateChecker:
    """Checks GitHub releases and caches the latest known status."""

    def __init__(self, current_version: str, check_interval_seconds: int = 21600):
        self.current_version = _normalize_version(current_version)
        self.check_interval_seconds = max(300, int(check_interval_seconds))
        self.enabled = True
        self._last_checked: float = 0.0
        self._status: Dict[str, Any] = {
            "checked": False,
            "current_version": self.current_version,
            "update_available": False,
            "current_is_newer_than_release": False,
            "latest_version": self.current_version,
            "release_name": "",
            "release_url": GITHUB_RELEASES_URL,
            "published_at": "",
            "prerelease": False,
            "checked_at": None,
            "message": "Update check has not run yet.",
            "error": "",
            "enabled": True,
            "check_interval_seconds": self.check_interval_seconds,
        }
        self._request_task: Optional[asyncio.Task] = None
        self._periodic_task: Optional[asyncio.Task] = None

    async def get_status(self, force: bool = False) -> Dict[str, Any]:
        if not self.enabled:
            status = dict(self._status)
            status.update({
                "enabled": False,
                "check_interval_seconds": self.check_interval_seconds,
                "message": "Update checks are disabled.",
                "error": "",
            })
            return status

        fresh_enough = (time.time() - self._last_checked) < self.check_interval_seconds
        if not force and self._status.get("checked") and fresh_enough:
            status = dict(self._status)
            status.update({
                "enabled": self.enabled,
                "check_interval_seconds": self.check_interval_seconds,
            })
            return status

        if self._request_task:
            await self._request_task
            status = dict(self._status)
            status.update({
                "enabled": self.enabled,
                "check_interval_seconds": self.check_interval_seconds,
            })
            return status

        self._request_task = asyncio.create_task(self._refresh())
        try:
            await self._request_task
        finally:
            self._request_task = None
        status = dict(self._status)
        status.update({
            "enabled": self.enabled,
            "check_interval_seconds": self.check_interval_seconds,
        })
        return status

    def configure(self, enabled: bool, interval_seconds: int) -> None:
        self.enabled = bool(enabled)
        self.check_interval_seconds = max(300, int(interval_seconds))
        self._status["enabled"] = self.enabled
        self._status["check_interval_seconds"] = self.check_interval_seconds
        if not self.enabled:
            self._status["message"] = "Update checks are disabled."

    def start_periodic_task(self) -> None:
        if self._periodic_task and not self._periodic_task.done():
            return
        self._periodic_task = asyncio.create_task(self._periodic_loop())

    async def stop_periodic_task(self) -> None:
        if not self._periodic_task:
            return
        self._periodic_task.cancel()
        try:
            await self._periodic_task
        except asyncio.CancelledError:
            pass
        self._periodic_task = None

    async def _periodic_loop(self) -> None:
        while True:
            try:
                if self.enabled:
                    await self.get_status(force=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Periodic update check failed: %s", exc)
            await asyncio.sleep(self.check_interval_seconds)

    async def _refresh(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            release = await loop.run_in_executor(None, self._fetch_latest_release_sync)
            latest_version = _normalize_version(release.get("tag_name") or release.get("name") or "")
            current_key = _version_key(self.current_version)
            latest_key = _version_key(latest_version)
            update_available = latest_key > current_key
            current_is_newer = current_key > latest_key
            checked_at = int(time.time())
            self._status = {
                "checked": True,
                "current_version": self.current_version,
                "update_available": update_available,
                "current_is_newer_than_release": current_is_newer,
                "latest_version": latest_version or self.current_version,
                "release_name": release.get("name") or release.get("tag_name") or "",
                "release_url": release.get("html_url") or GITHUB_RELEASES_URL,
                "published_at": release.get("published_at") or "",
                "prerelease": bool(release.get("prerelease")),
                "checked_at": checked_at,
                "enabled": self.enabled,
                "check_interval_seconds": self.check_interval_seconds,
                "message": (
                    f"Update available: v{latest_version}"
                    if update_available and latest_version
                    else (
                        "You are on the newest version."
                        if current_is_newer
                        else "You are on the newest version."
                    )
                ),
                "error": "",
            }
            self._last_checked = time.time()
            if update_available:
                logger.info(
                    "Update available: current=%s latest=%s url=%s",
                    self.current_version,
                    latest_version,
                    self._status["release_url"],
                )
            elif current_is_newer:
                logger.info(
                    "Update check complete: current version %s is newer than GitHub release %s",
                    self.current_version,
                    latest_version or "<unknown>",
                )
            else:
                logger.info("Update check complete: current version %s is up to date", self.current_version)
        except Exception as exc:
            self._last_checked = time.time()
            self._status.update({
                "checked": True,
                "current_version": self.current_version,
                "checked_at": int(time.time()),
                "enabled": self.enabled,
                "check_interval_seconds": self.check_interval_seconds,
                "message": "Could not check for updates right now.",
                "error": str(exc),
            })
            logger.warning("Update check failed: %s", exc)

    def _fetch_latest_release_sync(self) -> Dict[str, Any]:
        try:
            return self._fetch_latest_release_api_sync()
        except Exception as first_error:
            logger.info("GitHub latest-release API failed, trying releases page fallback: %s", first_error)
            try:
                fallback = self._fetch_latest_release_page_sync()
                fallback["api_error"] = str(first_error)
                return fallback
            except Exception as fallback_error:
                raise RuntimeError(
                    f"{first_error}; releases page fallback failed: {fallback_error}"
                ) from fallback_error

    def _fetch_latest_release_api_sync(self) -> Dict[str, Any]:
        req = urllib.request.Request(
            GITHUB_LATEST_API,
            headers={
                "User-Agent": f"APRSPropView/{self.current_version}",
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub returned HTTP {exc.code}: {body[:160]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub request failed: {exc.reason}") from exc

    def _fetch_latest_release_page_sync(self) -> Dict[str, Any]:
        req = urllib.request.Request(
            GITHUB_RELEASES_URL,
            headers={
                "User-Agent": f"APRSPropView/{self.current_version}",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub releases page returned HTTP {exc.code}: {body[:160]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub releases page request failed: {exc.reason}") from exc

        tags = re.findall(rf"/{re.escape(GITHUB_REPO)}/releases/tag/([^\"?#]+)", html)
        tags = sorted(set(tags), key=_version_key, reverse=True)
        if not tags:
            raise RuntimeError("Could not find a release tag on the GitHub releases page")

        tag = tags[0]
        return {
            "tag_name": tag,
            "name": tag,
            "html_url": f"{GITHUB_RELEASES_URL}/tag/{tag}",
            "published_at": "",
            "prerelease": False,
        }
