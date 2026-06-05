"""Data export module — CSV/JSON export and optional MQTT publishing."""

import csv
import io
import json
import logging
import re
import time
import asyncio
from typing import Dict, Any, List, Optional

logger = logging.getLogger("propview.export")


# ── CSV/JSON Export Helpers ─────────────────────────────────────────

def stations_to_csv(stations: List[Dict[str, Any]]) -> str:
    """Convert station list to CSV string."""
    if not stations:
        return ""
    output = io.StringIO()
    fields = [
        "callsign", "source", "first_heard", "last_heard", "packet_count",
        "latitude", "longitude", "distance_km", "heading",
        "symbol_table", "symbol_code", "last_comment", "last_path",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for s in stations:
        writer.writerow(s)
    return output.getvalue()


def packets_to_csv(packets: List[Dict[str, Any]]) -> str:
    """Convert packet list to CSV string."""
    if not packets:
        return ""
    output = io.StringIO()
    fields = [
        "timestamp", "source", "from_call", "to_call", "path",
        "packet_type", "latitude", "longitude", "raw",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for p in packets:
        writer.writerow(p)
    return output.getvalue()


def propagation_to_csv(records: List[Dict[str, Any]]) -> str:
    """Convert propagation log to CSV string."""
    if not records:
        return ""
    output = io.StringIO()
    fields = [
        "timestamp", "rf_station_count", "max_distance_km", "avg_distance_km",
        "unique_stations_1h", "unique_stations_6h", "unique_stations_24h",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(r)
    return output.getvalue()


# ── MQTT Publisher ──────────────────────────────────────────────────

class MQTTPublisher:
    """Publishes propagation data to an MQTT broker."""

    def __init__(self, host: str, port: int = 1883, topic_prefix: str = "aprs/propview",
                 username: str = "", password: str = "", discovery_enabled: bool = False,
                 discovery_prefix: str = "homeassistant", device_name: str = "APRS PropView",
                 device_id: str = "aprs_propview", station_callsign: str = "",
                 app_version: str = "", watched_callsigns: Optional[List[str]] = None):
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix.rstrip("/")
        self.username = username
        self.password = password
        self.discovery_enabled = discovery_enabled
        self.discovery_prefix = (discovery_prefix or "homeassistant").strip().strip("/")
        self.device_name = (device_name or "APRS PropView").strip()
        self.device_id = self._slugify(device_id or self.device_name)
        self.station_callsign = (station_callsign or "").strip().upper()
        self.app_version = (app_version or "").strip()
        self.watched_callsigns = self._normalize_watched_callsigns(watched_callsigns or [])
        self.availability_topic = f"{self.topic_prefix}/status"
        self._client = None
        self._connected = False
        self._last_status: Dict[str, Any] = {}

    async def connect(self):
        """Connect to MQTT broker."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.warning("paho-mqtt not installed — MQTT publishing disabled. "
                           "Install with: pip install paho-mqtt")
            return False

        self._client = mqtt.Client(client_id="aprs-propview", protocol=mqtt.MQTTv311)
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.will_set(self.availability_topic, "offline", qos=0, retain=True)

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._connected = True
                logger.info(f"MQTT connected to {self.host}:{self.port}")
                client.publish(self.availability_topic, "online", qos=0, retain=True)
            else:
                logger.error(f"MQTT connection failed: rc={rc}")

        def on_disconnect(client, userdata, rc):
            self._connected = False
            logger.warning(f"MQTT disconnected: rc={rc}")

        self._client.on_connect = on_connect
        self._client.on_disconnect = on_disconnect

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._client.connect(self.host, self.port, keepalive=60)
            )
            self._client.loop_start()
            # Wait briefly for connection
            await asyncio.sleep(1)
            if self._connected and self.discovery_enabled:
                await self.publish_home_assistant_discovery()
            return self._connected
        except Exception as e:
            logger.error(f"MQTT connect error: {e}")
            return False

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower().replace("-", "_"))
        return slug.strip("_") or "aprs_propview"

    @staticmethod
    def _normalize_watched_callsigns(callsigns: List[str]) -> List[str]:
        out = []
        seen = set()
        for value in callsigns or []:
            call = str(value or "").strip().upper()
            if not call or call in seen:
                continue
            if not re.fullmatch(r"[A-Z0-9]{1,9}(?:-[0-9]{1,2})?", call):
                continue
            seen.add(call)
            out.append(call)
        return out[:40]

    def _device_payload(self) -> Dict[str, Any]:
        payload = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "APRS PropView",
            "model": "APRS propagation monitor",
        }
        if self.app_version:
            payload["sw_version"] = self.app_version
        if self.station_callsign:
            payload["configuration_url"] = "http://localhost:14501/"
            payload["suggested_area"] = self.station_callsign
        return payload

    def _common_discovery(self, state_topic: str) -> Dict[str, Any]:
        return {
            "device": self._device_payload(),
            "state_topic": state_topic,
            "json_attributes_topic": state_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
        }

    def _discovery_payloads(self) -> Dict[str, Dict[str, Any]]:
        state_topic = f"{self.topic_prefix}/propagation"
        common = self._common_discovery(state_topic)
        status_common = self._common_discovery(f"{self.topic_prefix}/ha/status")

        payloads = {
            "my_score": {
                **common,
                "_component": "sensor",
                "name": "My Station Propagation Score",
                "unique_id": f"{self.device_id}_my_score",
                "value_template": "{{ value_json.my_score }}",
                "icon": "mdi:radio-tower",
                "unit_of_measurement": "%",
                "state_class": "measurement",
            },
            "my_level": {
                **common,
                "_component": "sensor",
                "name": "My Station Propagation Level",
                "unique_id": f"{self.device_id}_my_level",
                "value_template": "{{ value_json.my_level }}",
                "icon": "mdi:signal",
            },
            "regional_score": {
                **common,
                "_component": "sensor",
                "name": "Regional Propagation Score",
                "unique_id": f"{self.device_id}_regional_score",
                "value_template": "{{ value_json.regional_score }}",
                "icon": "mdi:radio-tower",
                "unit_of_measurement": "%",
                "state_class": "measurement",
            },
            "regional_level": {
                **common,
                "_component": "sensor",
                "name": "Regional Propagation Level",
                "unique_id": f"{self.device_id}_regional_level",
                "value_template": "{{ value_json.regional_level }}",
                "icon": "mdi:signal",
            },
            "rf_stations_1h": {
                **common,
                "_component": "sensor",
                "name": "RF Stations 1h",
                "unique_id": f"{self.device_id}_rf_stations_1h",
                "value_template": "{{ value_json.rf_stations_1h }}",
                "icon": "mdi:access-point-network",
                "unit_of_measurement": "stations",
                "state_class": "measurement",
            },
            "max_distance_km": {
                **common,
                "_component": "sensor",
                "name": "Max RF Distance",
                "unique_id": f"{self.device_id}_max_distance_km",
                "value_template": "{{ value_json.max_distance_km }}",
                "icon": "mdi:map-marker-distance",
                "unit_of_measurement": "km",
                "state_class": "measurement",
            },
            "rf_station_count": {
                **status_common,
                "_component": "sensor",
                "name": "RF Stations Heard",
                "unique_id": f"{self.device_id}_rf_station_count",
                "value_template": "{{ value_json.rf_station_count }}",
                "icon": "mdi:radio-handheld",
                "unit_of_measurement": "stations",
                "state_class": "measurement",
            },
            "aprs_is_station_count": {
                **status_common,
                "_component": "sensor",
                "name": "APRS-IS Stations Heard",
                "unique_id": f"{self.device_id}_aprs_is_station_count",
                "value_template": "{{ value_json.aprs_is_station_count }}",
                "icon": "mdi:cloud-sync",
                "unit_of_measurement": "stations",
                "state_class": "measurement",
            },
            "last_rf_packet_age": {
                **status_common,
                "_component": "sensor",
                "name": "Last RF Packet Age",
                "unique_id": f"{self.device_id}_last_rf_packet_age",
                "value_template": "{{ value_json.last_rf_packet_age_seconds }}",
                "icon": "mdi:timer-outline",
                "unit_of_measurement": "s",
                "state_class": "measurement",
            },
            "weather_alert_count": {
                **status_common,
                "_component": "sensor",
                "name": "Weather Alert Count",
                "unique_id": f"{self.device_id}_weather_alert_count",
                "value_template": "{{ value_json.weather_alert_count }}",
                "icon": "mdi:weather-lightning-rainy",
                "unit_of_measurement": "alerts",
                "state_class": "measurement",
            },
            "aprs_is_connected": self._binary_payload(
                "APRS-IS Connected", "aprs_is_connected", "mdi:cloud-check", status_common,
            ),
            "rf_interface_connected": self._binary_payload(
                "RF Interface Connected", "rf_interface_connected", "mdi:access-point-check", status_common,
            ),
            "band_opening_active": self._binary_payload(
                "Band Opening Active", "band_opening_active", "mdi:radio-tower", status_common,
            ),
            "sporadic_e_possible": self._binary_payload(
                "Sporadic-E Possible", "sporadic_e_possible", "mdi:flash-triangle", status_common,
            ),
            "new_station_heard": self._binary_payload(
                "New Station Heard", "new_station_heard", "mdi:account-plus", status_common,
            ),
            "weather_warning_active": self._binary_payload(
                "Weather Warning Active", "weather_warning_active", "mdi:alert", status_common,
            ),
            "aprs_message_waiting": self._binary_payload(
                "APRS Message Waiting", "aprs_message_waiting", "mdi:message-badge", status_common,
            ),
            "rf_interface_down": self._binary_payload(
                "RF Interface Down", "rf_interface_down", "mdi:access-point-off", status_common,
            ),
            "aprs_is_down": self._binary_payload(
                "APRS-IS Down", "aprs_is_down", "mdi:cloud-off-outline", status_common,
            ),
        }
        for callsign in self.watched_callsigns:
            slug = self._slugify(callsign)
            watched_common = self._common_discovery(f"{self.topic_prefix}/watched/{slug}")
            payloads[f"watched_{slug}"] = {
                **watched_common,
                "_component": "binary_sensor",
                "name": f"{callsign} Heard Recently",
                "unique_id": f"{self.device_id}_watched_{slug}",
                "value_template": "{{ value_json.present }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:radio-handheld",
            }
            payloads[f"watched_{slug}_last_heard"] = {
                **watched_common,
                "_component": "sensor",
                "name": f"{callsign} Last Heard",
                "unique_id": f"{self.device_id}_watched_{slug}_last_heard",
                "value_template": "{{ value_json.last_heard_iso }}",
                "icon": "mdi:clock-outline",
            }
            payloads[f"watched_{slug}_distance"] = {
                **watched_common,
                "_component": "sensor",
                "name": f"{callsign} Distance",
                "unique_id": f"{self.device_id}_watched_{slug}_distance",
                "value_template": "{{ value_json.distance_km }}",
                "icon": "mdi:map-marker-distance",
                "unit_of_measurement": "km",
                "state_class": "measurement",
            }
        return payloads

    def _binary_payload(self, name: str, field: str, icon: str, common: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **common,
            "_component": "binary_sensor",
            "name": name,
            "unique_id": f"{self.device_id}_{field}",
            "value_template": f"{{{{ value_json.{field} }}}}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": icon,
        }

    async def publish_home_assistant_discovery(self):
        """Publish Home Assistant MQTT Discovery configs for propagation sensors."""
        if not self._client or not self._connected:
            return
        try:
            for key, payload in self._discovery_payloads().items():
                payload = dict(payload)
                component = payload.pop("_component", "sensor")
                topic = f"{self.discovery_prefix}/{component}/{self.device_id}/{key}/config"
                self._client.publish(topic, json.dumps(payload), qos=0, retain=True)
            logger.info("MQTT Home Assistant discovery published for device %s", self.device_id)
        except Exception as e:
            logger.error(f"MQTT discovery publish error: {e}")

    async def publish_propagation(self, prop_data: Dict[str, Any]):
        """Publish current propagation score and metrics."""
        if not self._client or not self._connected:
            return
        try:
            payload = json.dumps({
                "my_score": prop_data.get("my_score", 0),
                "my_level": prop_data.get("my_level", "none"),
                "regional_score": prop_data.get("score", 0),
                "regional_level": prop_data.get("level", "none"),
                "rf_stations_1h": prop_data.get("rf_stations_1h", 0),
                "max_distance_km": prop_data.get("max_distance_km", 0),
                "timestamp": time.time(),
            })
            self._client.publish(
                f"{self.topic_prefix}/propagation", payload, qos=0, retain=True
            )
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")

    async def publish_alert(self, alert: Dict[str, Any]):
        """Publish alert event."""
        if not self._client or not self._connected:
            return
        try:
            payload = json.dumps(alert, default=str)
            self._client.publish(
                f"{self.topic_prefix}/alert", payload, qos=1
            )
            event_type = self._slugify(alert.get("type") or alert.get("event") or "alert")
            self._client.publish(
                f"{self.topic_prefix}/event/{event_type}", payload, qos=1
            )
        except Exception as e:
            logger.error(f"MQTT alert publish error: {e}")

    async def publish_event(self, event: Dict[str, Any]):
        """Publish an automation-friendly event payload."""
        if not self._client or not self._connected:
            return
        try:
            payload = json.dumps(event, default=str)
            self._client.publish(
                f"{self.topic_prefix}/event", payload, qos=1
            )
            event_type = self._slugify(event.get("event") or event.get("type") or "event")
            self._client.publish(
                f"{self.topic_prefix}/event/{event_type}", payload, qos=1
            )
        except Exception as e:
            logger.error(f"MQTT event publish error: {e}")

    async def publish_status_snapshot(self, status: Dict[str, Any]):
        """Publish retained Home Assistant status and binary-sensor state."""
        if not self._client or not self._connected:
            return
        try:
            self._last_status.update(status or {})
            payload = json.dumps(self._last_status, default=str)
            self._client.publish(f"{self.topic_prefix}/ha/status", payload, qos=0, retain=True)
        except Exception as e:
            logger.error(f"MQTT status snapshot publish error: {e}")

    async def publish_watched_station(self, callsign: str, station: Dict[str, Any], present: bool):
        """Publish retained state for one watched callsign."""
        if not self._client or not self._connected:
            return
        callsign = (callsign or "").strip().upper()
        if callsign not in self.watched_callsigns:
            return
        try:
            topic = f"{self.topic_prefix}/watched/{self._slugify(callsign)}"
            payload = json.dumps({
                "callsign": callsign,
                "present": "ON" if present else "OFF",
                "source": station.get("source", ""),
                "last_heard": station.get("last_heard"),
                "last_heard_iso": self._timestamp_iso(station.get("last_heard")),
                "distance_km": station.get("distance_km"),
                "heading": station.get("heading"),
                "path": station.get("last_path") or station.get("path", ""),
                "comment": station.get("last_comment") or station.get("comment", ""),
                "timestamp": time.time(),
            }, default=str)
            self._client.publish(topic, payload, qos=0, retain=True)
        except Exception as e:
            logger.error(f"MQTT watched station publish error: {e}")

    @staticmethod
    def _timestamp_iso(value) -> str:
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(value)))
        except (TypeError, ValueError, OverflowError):
            return ""

    async def publish_prop_score(self, score: float, level: str):
        """Publish just the propagation score (lightweight endpoint for integrations)."""
        if not self._client or not self._connected:
            return
        try:
            self._client.publish(
                f"{self.topic_prefix}/score", str(round(score, 1)), qos=0, retain=True
            )
            self._client.publish(
                f"{self.topic_prefix}/level", level, qos=0, retain=True
            )
        except Exception as e:
            logger.error(f"MQTT score publish error: {e}")

    async def close(self):
        """Disconnect from MQTT broker."""
        if self._client:
            if self._connected:
                self._client.publish(self.availability_topic, "offline", qos=0, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
