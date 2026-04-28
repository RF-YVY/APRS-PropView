"""Band Opening Alerts — detects propagation events and sends notifications."""

import asyncio
import logging
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger("propview.alerts")


@dataclass
class AlertConfig:
    """Alert thresholds and notification config."""
    enabled: bool = False
    # Per-meter thresholds
    my_min_stations: int = 3           # Direct-heard stations in 1h for My Station alert
    my_min_distance_km: float = 100.0  # Max direct distance for My Station alert
    regional_min_stations: int = 5     # All RF stations in 1h for Regional alert
    regional_min_distance_km: float = 100.0  # Max RF distance for Regional alert
    cooldown_seconds: int = 1800       # 30 min between alerts

    # Quiet hours (local time, HH:MM 24h)
    quiet_start: str = ""          # e.g. "22:00"
    quiet_end: str = ""            # e.g. "08:00"

    # Message notifications
    msg_notify_enabled: bool = False
    msg_discord_enabled: bool = False
    msg_email_enabled: bool = False
    msg_sms_enabled: bool = False

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
        self._last_my_alert_time: float = 0
        self._last_regional_alert_time: float = 0
        self._last_first_heard_alert_time: float = 0
        self._last_es_alert_time: float = 0
        self._last_anomaly_alert_time: float = 0
        self._alert_history: List[Dict[str, Any]] = []
        self._my_band_open: bool = False
        self._regional_band_open: bool = False

    def _is_quiet_time(self) -> bool:
        """Check if current local time falls within the quiet window."""
        qs = self.config.quiet_start.strip()
        qe = self.config.quiet_end.strip()
        if not qs or not qe:
            return False
        try:
            now = datetime.now().strftime("%H:%M")
            if qs <= qe:
                # Same-day window, e.g. 08:00–18:00
                return qs <= now < qe
            else:
                # Overnight window, e.g. 22:00–08:00
                return now >= qs or now < qe
        except Exception:
            return False

    def check_and_alert(self, prop_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check propagation data against thresholds. Returns list of alert dicts."""
        if not self.config.enabled:
            return []

        if self._is_quiet_time():
            return []

        now = time.time()
        alerts: List[Dict[str, Any]] = []

        # --- MY STATION alert (direct-heard only) ---
        my_count = prop_data.get("my_stations_1h", 0)
        my_max_dist = prop_data.get("my_max_distance_km", 0)
        my_score = prop_data.get("my_score", 0)
        my_level = prop_data.get("my_level", "none")

        my_meets = (
            my_count >= self.config.my_min_stations
            and my_max_dist >= self.config.my_min_distance_km
        )

        if not my_meets:
            self._my_band_open = False
        elif now - self._last_my_alert_time >= self.config.cooldown_seconds:
            was_open = self._my_band_open
            self._my_band_open = True
            self._last_my_alert_time = now
            label = "MY STATION Band Opening!" if not was_open else "MY STATION Band Still Open!"
            alerts.append({
                "type": "my_station_opening",
                "timestamp": now,
                "rf_stations": my_count,
                "max_distance_km": round(my_max_dist, 1),
                "score": round(my_score, 1),
                "level": my_level,
                "message": (
                    f"\U0001f6a8 {label}\n"
                    f"Station: {self.station_callsign}\n"
                    f"Direct Stations (1h): {my_count}\n"
                    f"Max Distance (Direct): {my_max_dist:.1f} km ({my_max_dist * 0.621371:.1f} mi)\n"
                    f"My Station Propagation: {my_level.upper()} (Score: {my_score:.0f})"
                ),
            })

        # --- REGIONAL alert (RF heard via another digipeater) ---
        rf_count = prop_data.get("regional_stations_1h", prop_data.get("rf_stations_1h", 0))
        max_dist = prop_data.get("max_distance_km", 0)
        score = prop_data.get("score", 0)
        level = prop_data.get("level", "none")

        reg_meets = (
            rf_count >= self.config.regional_min_stations
            and max_dist >= self.config.regional_min_distance_km
        )

        if not reg_meets:
            self._regional_band_open = False
        elif now - self._last_regional_alert_time >= self.config.cooldown_seconds:
            was_open = self._regional_band_open
            self._regional_band_open = True
            self._last_regional_alert_time = now
            label = "Regional VHF Band Watch" if not was_open else "Regional VHF Band Still Open"
            alerts.append({
                "type": "regional_watch",
                "timestamp": now,
                "rf_stations": rf_count,
                "max_distance_km": round(max_dist, 1),
                "score": round(score, 1),
                "level": level,
                "message": (
                    f"\U0001f50d {label}\n"
                    f"Station: {self.station_callsign}\n"
                    f"Relayed RF Stations (1h): {rf_count}\n"
                    f"Max Relayed Distance: {max_dist:.1f} km ({max_dist * 0.621371:.1f} mi)\n"
                    f"Regional Propagation: {level.upper()} (Score: {score:.0f})"
                ),
            })

        # Store history
        for alert in alerts:
            self._alert_history.append(alert)
        if len(self._alert_history) > 100:
            self._alert_history = self._alert_history[-100:]

        return alerts

    async def check_first_heard(self, callsign: str, distance_km: float, heading: Optional[float]):
        """Alert when a never-before-heard station appears on RF at distance."""
        if not self.config.enabled or self._is_quiet_time():
            return

        now = time.time()

        # Only alert for stations at meaningful distance
        if distance_km < 50:
            return

        # Cooldown: don't spam first-heard alerts
        if now - self._last_first_heard_alert_time < 300:  # 5 min cooldown
            return

        self._last_first_heard_alert_time = now

        bearing_str = f"{heading:.0f}°" if heading else "?"
        alert = {
            "type": "first_heard",
            "timestamp": now,
            "callsign": callsign,
            "distance_km": round(distance_km, 1),
            "heading": heading,
            "message": (
                f"\U0001f195 New Station Heard on RF!\n"
                f"Station: {self.station_callsign}\n"
                f"New Contact: {callsign}\n"
                f"Distance: {distance_km:.1f} km ({distance_km * 0.621371:.1f} mi)\n"
                f"Bearing: {bearing_str}"
            ),
        }

        self._alert_history.append(alert)
        if len(self._alert_history) > 100:
            self._alert_history = self._alert_history[-100:]

        await self.send_alert(alert)

    async def check_anomaly(self, anomaly_data: Dict[str, Any]):
        """Alert when propagation anomaly is detected (conditions significantly above baseline)."""
        if not self.config.enabled or self._is_quiet_time():
            return

        now = time.time()
        anomaly_score = anomaly_data.get("anomaly_score", 0)
        anomaly_level = anomaly_data.get("anomaly_level", "normal")

        # Only alert on significant+ anomalies
        if anomaly_score < 1.5:
            return

        if now - self._last_anomaly_alert_time < self.config.cooldown_seconds:
            return

        self._last_anomaly_alert_time = now

        count_pct = anomaly_data.get("count_pct_above_avg", 0)
        dist_pct = anomaly_data.get("dist_pct_above_avg", 0)

        alert = {
            "type": "anomaly",
            "timestamp": now,
            "anomaly_score": anomaly_score,
            "anomaly_level": anomaly_level,
            "message": (
                f"\U0001f4c8 Propagation Anomaly Detected!\n"
                f"Station: {self.station_callsign}\n"
                f"Level: {anomaly_level.upper()} ({anomaly_score:.1f}\u03c3)\n"
                f"Stations: {count_pct:+.0f}% vs average\n"
                f"Distance: {dist_pct:+.0f}% vs average"
            ),
        }

        self._alert_history.append(alert)
        if len(self._alert_history) > 100:
            self._alert_history = self._alert_history[-100:]

        await self.send_alert(alert)

    async def check_sporadic_e(self, es_data: Dict[str, Any]):
        """Alert when sporadic-E conditions are detected."""
        if not self.config.enabled or self._is_quiet_time():
            return

        now = time.time()
        es_level = es_data.get("es_level", "none")

        if es_level not in ("likely", "possible"):
            return

        if now - self._last_es_alert_time < self.config.cooldown_seconds:
            return

        self._last_es_alert_time = now

        candidates = es_data.get("candidates", [])
        top_calls = ", ".join(c["callsign"] for c in candidates[:3])
        max_dist = max((c["distance_km"] for c in candidates), default=0)

        alert = {
            "type": "sporadic_e",
            "timestamp": now,
            "es_level": es_level,
            "candidate_count": len(candidates),
            "max_distance_km": round(max_dist, 1),
            "message": (
                f"\u26a1 Possible Sporadic-E Event!\n"
                f"Station: {self.station_callsign}\n"
                f"Confidence: {es_level.upper()}\n"
                f"Candidates: {len(candidates)} station(s)\n"
                f"Max Distance: {max_dist:.1f} km ({max_dist * 0.621371:.1f} mi)\n"
                f"Top: {top_calls}"
            ),
        }

        self._alert_history.append(alert)
        if len(self._alert_history) > 100:
            self._alert_history = self._alert_history[-100:]

        await self.send_alert(alert)

    async def send_alert(self, alert: Dict[str, Any]):
        """Send alert via all configured channels."""
        tasks = []

        logger.info(
            f"send_alert called — discord={self.config.discord_enabled}, "
            f"email={self.config.email_enabled}, sms={self.config.sms_enabled}"
        )

        if self.config.discord_enabled and self.config.discord_webhook_url:
            tasks.append(self._send_discord(alert))

        if self.config.email_enabled and self.config.email_smtp_server:
            tasks.append(self._send_email(alert))

        if self.config.sms_enabled and self.config.sms_gateway_address:
            tasks.append(self._send_sms(alert))

        if not tasks:
            logger.warning("Alert triggered but no notification channels are configured/enabled")
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Alert channel {i} failed: {result}", exc_info=result)

    def _alert_embed_title(self, alert: Dict[str, Any]) -> str:
        alert_type = alert.get("type")
        if alert_type == "my_station_opening":
            return "\U0001f6a8 MY STATION Band Opening!"
        if alert_type == "anomaly":
            return "\U0001f4c8 Propagation Anomaly Detected"
        if alert_type == "sporadic_e":
            return "\u26a1 Possible Sporadic-E Event"
        return "\U0001f50d Regional VHF Band Watch"

    def _alert_embed_color(self, alert: Dict[str, Any]) -> int:
        alert_type = alert.get("type")
        if alert_type == "my_station_opening":
            return 0xFF6B35
        if alert_type == "anomaly":
            return 0xE63946
        if alert_type == "sporadic_e":
            return 0xF4A261
        return 0xFFA500

    def _alert_embed_fields(self, alert: Dict[str, Any]) -> list[Dict[str, Any]]:
        alert_type = alert.get("type")
        if alert_type in {"my_station_opening", "regional_watch"}:
            return [
                {"name": "RF Stations", "value": str(alert.get("rf_stations", 0)), "inline": True},
                {"name": "Max Distance", "value": f"{alert.get('max_distance_km', 0)} km", "inline": True},
                {"name": "Propagation", "value": f"{str(alert.get('level', 'none')).upper()} ({alert.get('score', 0)})", "inline": True},
            ]
        if alert_type == "anomaly":
            return [
                {"name": "Level", "value": f"{str(alert.get('anomaly_level', 'normal')).upper()} ({alert.get('anomaly_score', 0):.1f}\u03c3)", "inline": True},
            ]
        if alert_type == "sporadic_e":
            return [
                {"name": "Confidence", "value": str(alert.get("es_level", "none")).upper(), "inline": True},
                {"name": "Candidates", "value": str(alert.get("candidate_count", 0)), "inline": True},
                {"name": "Max Distance", "value": f"{alert.get('max_distance_km', 0)} km", "inline": True},
            ]
        return []

    async def _send_discord(self, alert: Dict[str, Any]):
        """Send alert to Discord webhook."""
        try:
            import urllib.request
            import ssl

            payload = json.dumps({
                "content": alert["message"],
                "embeds": [{
                    "title": self._alert_embed_title(alert),
                    "color": self._alert_embed_color(alert),
                    "fields": self._alert_embed_fields(alert),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(alert["timestamp"])),
                }],
            }).encode("utf-8")

            req = urllib.request.Request(
                self.config.discord_webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "APRSPropView/1.0",
                },
                method="POST",
            )

            loop = asyncio.get_running_loop()
            ctx = ssl.create_default_context()
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, context=ctx, timeout=10),
            )
            logger.info("Discord alert sent successfully")

        except Exception as e:
            logger.error(f"Discord alert failed: {e}", exc_info=True)
            raise

    async def _send_email(self, alert: Dict[str, Any]):
        """Send alert via email SMTP."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            subject = (
                "APRS PropView \u2014 MY STATION Band Opening!" if alert.get("type") == "my_station_opening"
                else "APRS PropView \u2014 Regional VHF Band Watch"
            )
            msg = MIMEText(alert["message"])
            msg["Subject"] = subject
            msg["From"] = self.config.email_from
            msg["To"] = self.config.email_to

            smtp_server = self.config.email_smtp_server
            smtp_port = self.config.email_smtp_port
            email_from = self.config.email_from
            email_pw = self.config.email_password

            loop = asyncio.get_running_loop()

            def _send():
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                        server.starttls()
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)

            await loop.run_in_executor(None, _send)
            logger.info(f"Email alert sent to {self.config.email_to}")

        except Exception as e:
            logger.error(f"Email alert failed: {e}", exc_info=True)
            raise

    async def _send_sms(self, alert: Dict[str, Any]):
        """Send SMS via email-to-SMS gateway."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            sms_label = (
                "MY STATION BAND OPENING!" if alert.get("type") == "my_station_opening"
                else "REGIONAL VHF WATCH"
            )
            if alert.get("type") in {"my_station_opening", "regional_watch"}:
                sms_text = (
                    f"{sms_label} "
                    f"RF:{alert.get('rf_stations', 0)} "
                    f"Max:{alert.get('max_distance_km', 0)}km "
                    f"Prop:{str(alert.get('level', 'none')).upper()}"
                )
            else:
                sms_text = alert["message"]

            msg = MIMEText(sms_text)
            msg["Subject"] = ""
            msg["From"] = self.config.email_from
            msg["To"] = self.config.sms_gateway_address

            smtp_server = self.config.email_smtp_server
            smtp_port = self.config.email_smtp_port
            email_from = self.config.email_from
            email_pw = self.config.email_password

            loop = asyncio.get_running_loop()

            def _send():
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                        server.starttls()
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)

            await loop.run_in_executor(None, _send)
            logger.info(f"SMS alert sent to {self.config.sms_gateway_address}")

        except Exception as e:
            logger.error(f"SMS alert failed: {e}", exc_info=True)
            raise

    async def send_message_notification(self, msg: Dict[str, Any]):
        """Send notification when an APRS message is received for our station."""
        if not self.config.msg_notify_enabled:
            return
        if self._is_quiet_time():
            return

        from_call = msg.get("from", "???")
        text = msg.get("text", "")
        source = msg.get("source", "?")

        alert = {
            "type": "message_received",
            "timestamp": time.time(),
            "message": (
                f"\U0001f4ac APRS Message Received\n"
                f"From: {from_call} ({source.upper()})\n"
                f"To: {self.station_callsign}\n"
                f"Message: {text}"
            ),
            # Fields needed by _send_discord embed
            "rf_stations": 0,
            "max_distance_km": 0,
            "score": 0,
            "level": "message",
        }

        tasks = []
        if self.config.msg_discord_enabled and self.config.discord_webhook_url:
            tasks.append(self._send_discord_message(alert, from_call, text, source))
        if self.config.msg_email_enabled and self.config.email_smtp_server:
            tasks.append(self._send_email(alert))
        if self.config.msg_sms_enabled and self.config.sms_gateway_address:
            tasks.append(self._send_sms_message(from_call, text))

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Message notification channel {i} failed: {result}", exc_info=result)

    async def _send_discord_message(self, alert: Dict[str, Any], from_call: str, text: str, source: str):
        """Send incoming message notification to Discord."""
        try:
            import urllib.request
            import ssl

            payload = json.dumps({
                "content": alert["message"],
                "embeds": [{
                    "title": "\U0001f4ac APRS Message Received",
                    "color": 0x58A6FF,
                    "fields": [
                        {"name": "From", "value": from_call, "inline": True},
                        {"name": "Source", "value": source.upper(), "inline": True},
                        {"name": "Message", "value": text or "(empty)", "inline": False},
                    ],
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(alert["timestamp"])),
                }],
            }).encode("utf-8")

            req = urllib.request.Request(
                self.config.discord_webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "APRSPropView/1.0",
                },
                method="POST",
            )

            loop = asyncio.get_running_loop()
            ctx = ssl.create_default_context()
            await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, context=ctx, timeout=10),
            )
            logger.info("Discord message notification sent")
        except Exception as e:
            logger.error(f"Discord message notification failed: {e}", exc_info=True)
            raise

    async def _send_sms_message(self, from_call: str, text: str):
        """Send incoming message notification via SMS."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            sms_text = f"APRS MSG from {from_call}: {text}"[:160]

            msg = MIMEText(sms_text)
            msg["Subject"] = ""
            msg["From"] = self.config.email_from
            msg["To"] = self.config.sms_gateway_address

            smtp_server = self.config.email_smtp_server
            smtp_port = self.config.email_smtp_port
            email_from = self.config.email_from
            email_pw = self.config.email_password

            loop = asyncio.get_running_loop()

            def _send():
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                        server.starttls()
                        if email_pw:
                            server.login(email_from, email_pw)
                        server.send_message(msg)

            await loop.run_in_executor(None, _send)
            logger.info(f"SMS message notification sent to {self.config.sms_gateway_address}")
        except Exception as e:
            logger.error(f"SMS message notification failed: {e}", exc_info=True)
            raise

    def get_alert_history(self) -> List[Dict[str, Any]]:
        """Return recent alert history."""
        return list(reversed(self._alert_history))

    def get_status(self) -> Dict[str, Any]:
        """Return current alert system status."""
        return {
            "enabled": self.config.enabled,
            "my_band_open": self._my_band_open,
            "regional_band_open": self._regional_band_open,
            "last_my_alert": self._last_my_alert_time,
            "last_regional_alert": self._last_regional_alert_time,
            "last_first_heard_alert": self._last_first_heard_alert_time,
            "last_anomaly_alert": self._last_anomaly_alert_time,
            "last_es_alert": self._last_es_alert_time,
            "alert_count": len(self._alert_history),
            "channels": {
                "discord": self.config.discord_enabled,
                "email": self.config.email_enabled,
                "sms": self.config.sms_enabled,
            },
            "thresholds": {
                "my_min_stations": self.config.my_min_stations,
                "my_min_distance_km": self.config.my_min_distance_km,
                "regional_min_stations": self.config.regional_min_stations,
                "regional_min_distance_km": self.config.regional_min_distance_km,
                "cooldown_seconds": self.config.cooldown_seconds,
            },
        }
