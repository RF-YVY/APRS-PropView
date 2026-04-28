"""Data export module — CSV/JSON export and optional MQTT publishing."""

import csv
import io
import json
import logging
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
                 username: str = "", password: str = ""):
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix.rstrip("/")
        self.username = username
        self.password = password
        self._client = None
        self._connected = False

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

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._connected = True
                logger.info(f"MQTT connected to {self.host}:{self.port}")
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
            return self._connected
        except Exception as e:
            logger.error(f"MQTT connect error: {e}")
            return False

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
        except Exception as e:
            logger.error(f"MQTT alert publish error: {e}")

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
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
