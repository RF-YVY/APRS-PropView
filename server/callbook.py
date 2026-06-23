"""Online amateur-radio callbook lookup helpers."""

import asyncio
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


FetchFn = Callable[[str, int], bytes]


@dataclass
class CallbookCredentials:
    provider: str = "auto"
    hamqth_username: str = ""
    hamqth_password: str = ""
    qrz_username: str = ""
    qrz_password: str = ""


def _fetch_url(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "APRS-PropView/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(512 * 1024)


def _xml_text(root: ET.Element, tag: str) -> str:
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1].lower() == tag.lower():
            return (elem.text or "").strip()
    return ""


def _parse_float(value: str) -> Optional[float]:
    try:
        if value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _lookup_result(
    *,
    source: str,
    searched_callsign: str,
    root: ET.Element,
    lat_tag: str = "latitude",
    lon_tag: str = "longitude",
) -> Dict[str, Any]:
    latitude = _parse_float(_xml_text(root, lat_tag))
    longitude = _parse_float(_xml_text(root, lon_tag))
    return {
        "success": bool(latitude is not None and longitude is not None) or bool(_xml_text(root, "grid")),
        "source": source,
        "callsign": (_xml_text(root, "callsign") or _xml_text(root, "call") or searched_callsign).upper(),
        "grid": _xml_text(root, "grid").upper(),
        "latitude": latitude,
        "longitude": longitude,
        "name": _xml_text(root, "adr_name") or _xml_text(root, "name") or _xml_text(root, "fname"),
        "qth": _xml_text(root, "qth") or _xml_text(root, "addr2"),
        "state": _xml_text(root, "us_state") or _xml_text(root, "state"),
        "country": _xml_text(root, "adr_country") or _xml_text(root, "country"),
    }


def _parse_xml(data: bytes) -> ET.Element:
    return ET.fromstring(data.decode("utf-8", errors="replace"))


def lookup_callook_sync(
    _credentials: CallbookCredentials,
    callsign: str,
    fetcher: FetchFn = _fetch_url,
) -> Dict[str, Any]:
    url = f"https://callook.info/{urllib.parse.quote(callsign.upper())}/json"
    data = json.loads(fetcher(url, 12).decode("utf-8", errors="replace"))
    if str(data.get("status", "")).upper() != "VALID":
        return {"success": False, "source": "callook", "message": "Callook did not find a valid U.S. amateur callsign."}

    location = data.get("location") or {}
    address = data.get("address") or {}
    latitude = _parse_float(str(location.get("latitude", "")))
    longitude = _parse_float(str(location.get("longitude", "")))
    grid = str(location.get("gridsquare", "") or "").strip().upper()
    return {
        "success": bool(latitude is not None and longitude is not None) or bool(grid),
        "source": "callook",
        "callsign": str((data.get("current") or {}).get("callsign") or callsign).upper(),
        "grid": grid,
        "latitude": latitude,
        "longitude": longitude,
        "name": str(data.get("name") or "").strip(),
        "qth": str(address.get("line2") or "").strip(),
        "state": "",
        "country": "United States",
        "license_status": str(data.get("status") or "").strip(),
        "license_class": str((data.get("current") or {}).get("operClass") or "").strip(),
        "source_note": "U.S. FCC data with geocoded mailing address; operating location may differ.",
    }


def lookup_hamdb_sync(
    _credentials: CallbookCredentials,
    callsign: str,
    fetcher: FetchFn = _fetch_url,
) -> Dict[str, Any]:
    url = f"https://api.hamdb.org/{urllib.parse.quote(callsign.upper())}/json/APRSPropView"
    data = json.loads(fetcher(url, 12).decode("utf-8", errors="replace"))
    root = data.get("hamdb") or {}
    status = str((root.get("messages") or {}).get("status") or "").upper()
    if status and status != "OK":
        return {"success": False, "source": "hamdb", "message": f"HamDB lookup returned {status}."}
    call = root.get("callsign") or {}
    latitude = _parse_float(str(call.get("lat", "")))
    longitude = _parse_float(str(call.get("lon", "")))
    grid = str(call.get("grid") or "").strip().upper()
    return {
        "success": bool(latitude is not None and longitude is not None) or bool(grid),
        "source": "hamdb",
        "callsign": str(call.get("call") or callsign).upper(),
        "grid": grid,
        "latitude": latitude,
        "longitude": longitude,
        "name": " ".join(part for part in [str(call.get("fname") or "").strip(), str(call.get("name") or "").strip()] if part),
        "qth": " ".join(part for part in [str(call.get("addr2") or "").strip(), str(call.get("state") or "").strip(), str(call.get("zip") or "").strip()] if part),
        "state": str(call.get("state") or "").strip(),
        "country": str(call.get("country") or "").strip(),
        "license_status": str(call.get("status") or "").strip(),
        "license_class": str(call.get("class") or "").strip(),
        "source_note": "Free callbook data; coordinates are based on published license/address data when available.",
    }


def lookup_hamqth_sync(
    credentials: CallbookCredentials,
    callsign: str,
    fetcher: FetchFn = _fetch_url,
) -> Dict[str, Any]:
    if not credentials.hamqth_username or not credentials.hamqth_password:
        return {"success": False, "source": "hamqth", "message": "HamQTH username and password are required."}

    login_url = "https://www.hamqth.com/xml.php?" + urllib.parse.urlencode({
        "u": credentials.hamqth_username,
        "p": credentials.hamqth_password,
    })
    login_root = _parse_xml(fetcher(login_url, 12))
    login_error = _xml_text(login_root, "error")
    if login_error:
        return {"success": False, "source": "hamqth", "message": login_error}
    session_id = _xml_text(login_root, "session_id")
    if not session_id:
        return {"success": False, "source": "hamqth", "message": "HamQTH did not return a session ID."}

    lookup_url = "https://www.hamqth.com/xml.php?" + urllib.parse.urlencode({
        "id": session_id,
        "callsign": callsign,
        "prg": "APRSPropView",
    })
    lookup_root = _parse_xml(fetcher(lookup_url, 12))
    lookup_error = _xml_text(lookup_root, "error")
    if lookup_error:
        return {"success": False, "source": "hamqth", "message": lookup_error}
    result = _lookup_result(source="hamqth", searched_callsign=callsign, root=lookup_root)
    if not result["success"]:
        result["message"] = "HamQTH found the callsign, but no usable grid or coordinates were returned."
    return result


def lookup_qrz_sync(
    credentials: CallbookCredentials,
    callsign: str,
    fetcher: FetchFn = _fetch_url,
) -> Dict[str, Any]:
    if not credentials.qrz_username or not credentials.qrz_password:
        return {"success": False, "source": "qrz", "message": "QRZ username and password are required."}

    login_url = "https://xmldata.qrz.com/xml/current/?" + urllib.parse.urlencode({
        "username": credentials.qrz_username,
        "password": credentials.qrz_password,
        "agent": "APRSPropView",
    })
    login_root = _parse_xml(fetcher(login_url, 12))
    login_error = _xml_text(login_root, "Error")
    if login_error:
        return {"success": False, "source": "qrz", "message": login_error}
    session_key = _xml_text(login_root, "Key")
    if not session_key:
        return {"success": False, "source": "qrz", "message": "QRZ did not return a session key."}

    lookup_url = "https://xmldata.qrz.com/xml/current/?" + urllib.parse.urlencode({
        "s": session_key,
        "callsign": callsign,
    })
    lookup_root = _parse_xml(fetcher(lookup_url, 12))
    lookup_error = _xml_text(lookup_root, "Error")
    if lookup_error:
        return {"success": False, "source": "qrz", "message": lookup_error}
    result = _lookup_result(source="qrz", searched_callsign=callsign, root=lookup_root, lat_tag="lat", lon_tag="lon")
    if not result["success"]:
        result["message"] = "QRZ found the callsign, but no usable grid or coordinates were returned."
    return result


async def lookup_callsign(credentials: CallbookCredentials, callsign: str) -> Dict[str, Any]:
    """Lookup a station in the configured callbook provider."""
    call = (callsign or "").strip().upper().split("-", 1)[0]
    if not call:
        return {"success": False, "source": "", "message": "Enter a callsign to look up."}

    provider = (credentials.provider or "auto").strip().lower()
    loop = asyncio.get_running_loop()

    def run_callook():
        return lookup_callook_sync(credentials, call)

    def run_hamdb():
        return lookup_hamdb_sync(credentials, call)

    def run_hamqth():
        return lookup_hamqth_sync(credentials, call)

    def run_qrz():
        return lookup_qrz_sync(credentials, call)

    runners = {
        "callook": run_callook,
        "hamdb": run_hamdb,
        "hamqth": run_hamqth,
        "qrz": run_qrz,
    }
    if provider in runners:
        return await loop.run_in_executor(None, runners[provider])

    if provider == "auto":
        attempts = [run_callook, run_hamdb]
        if credentials.qrz_username and credentials.qrz_password:
            attempts.append(run_qrz)
        if credentials.hamqth_username and credentials.hamqth_password:
            attempts.append(run_hamqth)
        failures = []
        for runner in attempts:
            result = await loop.run_in_executor(None, runner)
            if result.get("success"):
                return result
            failures.append(f"{result.get('source')}: {result.get('message', 'no usable location')}")
        return {
            "success": False,
            "source": "auto",
            "message": "No lookup provider returned a usable location. " + "; ".join(failures),
        }
    return await loop.run_in_executor(None, run_hamdb)
