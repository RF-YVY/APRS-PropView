"""Band Opening Alerts — detects propagation events and sends notifications."""

import asyncio
import logging
import time
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger("propview.alerts")


@dataclass
class AlertConfig:
    """Alert thresholds and notification config."""
    enabled: bool = False
    # Thresholds
    min_stations: int = 5          # Minimum RF stations in 1h to trigger
    min_distance_km: float = 100.0 # Minimum max-distance to trigger
    cooldown_seconds: int = 1800   # 30 min between alerts

    # Discord webhook
    discord_enabled: bool = False
    discord_webhook_url: str = ""

    # Email (SMTP)
    email_enabled: bool = False
    email_smtp_server: str = ""
    email_smtp_port: int = 587
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""

    # SMS via email gateway (e.g. 5551234567@tmomail.net)
    sms_enabled: bool = False
    sms_gateway_address: str = ""


class AlertManager:
    """Monitors propagation and sends band-opening alerts."""

    def __init__(self, config: AlertConfig, station_callsign: str = ""):
        self.config = config
        self.station_callsign = station_callsign
        self._last_alert_time: float = 0
        self._alert_history: List[Dict[str, Any]] = []
        self._band_open: bool = False

    def check_and_alert(self, prop_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check propagation data against thresholds. Returns alert dict if triggered."""
        if not self.config.enabled:
            return None

        now = time.time()
        rf_count = prop_data.get("rf_stations_1h", 0)
        max_dist = prop_data.get("max_distance_km", 0)
        score = prop_data.get("score", 0)
        level = prop_data.get("level", "none")

        meets_threshold = (
            rf_count >= self.config.min_stations
            and max_dist >= self.config.min_distance_km
        )

        # Detect band opening (transition from below to above threshold)
        if meets_threshold and not self._band_open:
            self._band_open = True

            # Check cooldown
            if now - self._last_alert_time < self.config.cooldown_seconds:
                return None

            self._last_alert_time = now

            alert = {
                "type": "band_opening",
                "timestamp": now,
                "rf_stations": rf_count,
                "max_distance_km": round(max_dist, 1),
                "score": round(score, 1),
                "level": level,
                "message": (
                    f"🚨 VHF Band Opening Detected!\n"
                    f"Station: {self.station_callsign}\n"
                    f"RF Stations (1h): {rf_count}\n"
                    f"Max Distance: {max_dist:.1f} km ({max_dist * 0.621371:.1f} mi)\n"
                    f"Propagation: {level.upper()} (Score: {score:.0f})"
                ),
            }

            self._alert_history.append(alert)
            # Keep only last 100 alerts
            if len(self._alert_history) > 100:
                self._alert_history = self._alert_history[-100:]

            return alert

        elif not meets_threshold:
            self._band_open = False

        return None

    async def send_alert(self, alert: Dict[str, Any]):
        """Send alert via all configured channels."""
        tasks = []

        if self.config.discord_enabled and self.config.discord_webhook_url:
            tasks.append(self._send_discord(alert))

        if self.config.email_enabled and self.config.email_smtp_server:
            tasks.append(self._send_email(alert))

        if self.config.sms_enabled and self.config.sms_gateway_address:
            tasks.append(self._send_sms(alert))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Alert send error: {result}")

    async def _send_discord(self, alert: Dict[str, Any]):
        """Send alert to Discord webhook."""
        try:
            import urllib.request
            import ssl

            payload = json.dumps({
                "content": alert["message"],
                "embeds": [{
                    "title": "🚨 VHF Band Opening!",
                    "color": 0xFF6B35,
                    "fields": [
                        {"name": "RF Stations", "value": str(alert["rf_stations"]), "inline": True},
                        {"name": "Max Distance", "value": f"{alert['max_distance_km']} km", "inline": True},
                        {"name": "Propagation", "value": f"{alert['level'].upper()} ({alert['score']})", "inline": True},
                    ],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(alert["timestamp"])),
                }],
            }).encode("utf-8")

            req = urllib.request.Request(
                self.config.discord_webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            ctx = ssl.create_default_context()
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, context=ctx, timeout=10),
            )
            logger.info("Discord alert sent successfully")

        except Exception as e:
            logger.error(f"Discord alert failed: {e}")

    async def _send_email(self, alert: Dict[str, Any]):
        """Send alert via email SMTP."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(alert["message"])
            msg["Subject"] = f"APRS PropView — VHF Band Opening Alert"
            msg["From"] = self.config.email_from
            msg["To"] = self.config.email_to

            loop = asyncio.get_event_loop()

            def _send():
                with smtplib.SMTP(self.config.email_smtp_server, self.config.email_smtp_port, timeout=15) as server:
                    server.starttls()
                    if self.config.email_password:
                        server.login(self.config.email_from, self.config.email_password)
                    server.send_message(msg)

            await loop.run_in_executor(None, _send)
            logger.info(f"Email alert sent to {self.config.email_to}")

        except Exception as e:
            logger.error(f"Email alert failed: {e}")

    async def _send_sms(self, alert: Dict[str, Any]):
        """Send SMS via email-to-SMS gateway."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            # SMS messages should be short
            sms_text = (
                f"VHF BAND OPENING! "
                f"RF:{alert['rf_stations']} "
                f"Max:{alert['max_distance_km']}km "
                f"Prop:{alert['level'].upper()}"
            )

            msg = MIMEText(sms_text)
            msg["Subject"] = ""
            msg["From"] = self.config.email_from
            msg["To"] = self.config.sms_gateway_address

            loop = asyncio.get_event_loop()

            def _send():
                with smtplib.SMTP(self.config.email_smtp_server, self.config.email_smtp_port, timeout=15) as server:
                    server.starttls()
                    if self.config.email_password:
                        server.login(self.config.email_from, self.config.email_password)
                    server.send_message(msg)

            await loop.run_in_executor(None, _send)
            logger.info(f"SMS alert sent to {self.config.sms_gateway_address}")

        except Exception as e:
            logger.error(f"SMS alert failed: {e}")

    def get_alert_history(self) -> List[Dict[str, Any]]:
        """Return recent alert history."""
        return list(reversed(self._alert_history))

    def get_status(self) -> Dict[str, Any]:
        """Return current alert system status."""
        return {
            "enabled": self.config.enabled,
            "band_open": self._band_open,
            "last_alert": self._last_alert_time,
            "alert_count": len(self._alert_history),
            "channels": {
                "discord": self.config.discord_enabled,
                "email": self.config.email_enabled,
                "sms": self.config.sms_enabled,
            },
            "thresholds": {
                "min_stations": self.config.min_stations,
                "min_distance_km": self.config.min_distance_km,
                "cooldown_seconds": self.config.cooldown_seconds,
            },
        }
