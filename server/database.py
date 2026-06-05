"""SQLite database for persistent station tracking and packet logging."""

import aiosqlite
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("propview.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    callsign TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('rf', 'aprs_is')),
    first_heard REAL NOT NULL,
    last_heard REAL NOT NULL,
    packet_count INTEGER DEFAULT 1,
    latitude REAL,
    longitude REAL,
    symbol_table TEXT DEFAULT '/',
    symbol_code TEXT DEFAULT '-',
    last_comment TEXT DEFAULT '',
    last_path TEXT DEFAULT '',
    last_port_name TEXT DEFAULT '',
    last_raw TEXT DEFAULT '',
    distance_km REAL,
    heading REAL,
    PRIMARY KEY (callsign, source)
);

CREATE TABLE IF NOT EXISTS packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    source TEXT NOT NULL,
    from_call TEXT NOT NULL,
    to_call TEXT DEFAULT '',
    path TEXT DEFAULT '',
    raw TEXT NOT NULL,
    packet_type TEXT DEFAULT '',
    latitude REAL,
    longitude REAL,
    port_name TEXT DEFAULT '',
    digipeated_by_me INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('rx', 'tx')),
    from_call TEXT NOT NULL,
    to_call TEXT NOT NULL,
    text TEXT DEFAULT '',
    message_id TEXT DEFAULT '',
    source TEXT DEFAULT '',
    acked INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    dedupe_key TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS message_contacts (
    callsign TEXT PRIMARY KEY,
    display_name TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_used REAL
);

CREATE TABLE IF NOT EXISTS propagation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    rf_station_count INTEGER NOT NULL,
    max_distance_km REAL,
    avg_distance_km REAL,
    unique_stations_1h INTEGER,
    unique_stations_6h INTEGER,
    unique_stations_24h INTEGER
);

CREATE TABLE IF NOT EXISTS ducting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    ducting_index REAL,
    pressure_mb REAL,
    pressure_trend REAL,
    temp_f REAL,
    humidity REAL,
    inversion_detected INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS path_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    callsign TEXT NOT NULL,
    distance_km REAL,
    heading REAL,
    path TEXT DEFAULT '',
    port_name TEXT DEFAULT '',
    hop_count INTEGER DEFAULT 0,
    is_direct INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS first_heard_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    callsign TEXT NOT NULL,
    source TEXT NOT NULL,
    distance_km REAL,
    heading REAL,
    latitude REAL,
    longitude REAL,
    path TEXT DEFAULT '',
    port_name TEXT DEFAULT '',
    hop_count INTEGER DEFAULT 0,
    is_direct INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_stations_source ON stations(source);
CREATE INDEX IF NOT EXISTS idx_stations_last_heard ON stations(last_heard);
CREATE INDEX IF NOT EXISTS idx_packets_timestamp ON packets(timestamp);
CREATE INDEX IF NOT EXISTS idx_packets_source ON packets(source);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedupe ON messages(dedupe_key) WHERE dedupe_key != '';
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_contact ON messages(from_call, to_call);
CREATE INDEX IF NOT EXISTS idx_message_contacts_last_used ON message_contacts(last_used);
CREATE INDEX IF NOT EXISTS idx_propagation_timestamp ON propagation_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_ducting_timestamp ON ducting_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_path_history_callsign ON path_history(callsign);
CREATE INDEX IF NOT EXISTS idx_path_history_timestamp ON path_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_first_heard_timestamp ON first_heard_log(timestamp);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create database and tables."""
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self._migrate_schema()
        await self.db.commit()
        logger.info(f"Database initialized at {self.db_path}")

    async def _migrate_schema(self):
        """Add columns introduced after earlier database versions."""
        cursor = await self.db.execute("PRAGMA table_info(first_heard_log)")
        columns = {row["name"] for row in await cursor.fetchall()}
        additions = {
            "path": "ALTER TABLE first_heard_log ADD COLUMN path TEXT DEFAULT ''",
            "port_name": "ALTER TABLE first_heard_log ADD COLUMN port_name TEXT DEFAULT ''",
            "hop_count": "ALTER TABLE first_heard_log ADD COLUMN hop_count INTEGER DEFAULT 0",
            "is_direct": "ALTER TABLE first_heard_log ADD COLUMN is_direct INTEGER DEFAULT 0",
        }
        for name, statement in additions.items():
            if name not in columns:
                await self.db.execute(statement)
        for table, table_additions in {
            "stations": {
                "last_port_name": "ALTER TABLE stations ADD COLUMN last_port_name TEXT DEFAULT ''",
            },
            "packets": {
                "port_name": "ALTER TABLE packets ADD COLUMN port_name TEXT DEFAULT ''",
                "digipeated_by_me": "ALTER TABLE packets ADD COLUMN digipeated_by_me INTEGER DEFAULT 0",
            },
            "path_history": {
                "port_name": "ALTER TABLE path_history ADD COLUMN port_name TEXT DEFAULT ''",
            },
        }.items():
            cursor = await self.db.execute(f"PRAGMA table_info({table})")
            table_columns = {row["name"] for row in await cursor.fetchall()}
            for name, statement in table_additions.items():
                if name not in table_columns:
                    await self.db.execute(statement)
        await self.db.execute(
            """DELETE FROM first_heard_log
               WHERE id NOT IN (
                   SELECT MIN(id)
                   FROM first_heard_log
                   GROUP BY UPPER(callsign), source
               )"""
        )
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_first_heard_unique_station ON first_heard_log(UPPER(callsign), source)"
        )

    async def close(self):
        if self.db:
            await self.db.close()

    async def commit(self):
        if self.db:
            await self.db.commit()

    # ── Station operations ──────────────────────────────────────────

    async def upsert_station(
        self,
        callsign: str,
        source: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        symbol_table: str = "/",
        symbol_code: str = "-",
        comment: str = "",
        path: str = "",
        port_name: str = "",
        raw: str = "",
        distance_km: Optional[float] = None,
        heading: Optional[float] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Insert or update a station record. Returns the station dict."""
        now = time.time()
        existing = await self.db.execute(
            "SELECT * FROM stations WHERE callsign = ? AND source = ?",
            (callsign, source),
        )
        row = await existing.fetchone()

        if row:
            update_fields = {
                "last_heard": now,
                "packet_count": row["packet_count"] + 1,
                "last_path": path,
                "last_port_name": port_name,
                "last_raw": raw,
                "last_comment": comment or row["last_comment"],
            }
            if latitude is not None:
                update_fields["latitude"] = latitude
                update_fields["longitude"] = longitude
                # Always update symbol when position is present (parser extracted it)
                update_fields["symbol_table"] = symbol_table
                update_fields["symbol_code"] = symbol_code
            if distance_km is not None:
                update_fields["distance_km"] = distance_km
                update_fields["heading"] = heading

            set_clause = ", ".join(f"{k} = ?" for k in update_fields)
            values = list(update_fields.values()) + [callsign, source]
            await self.db.execute(
                f"UPDATE stations SET {set_clause} WHERE callsign = ? AND source = ?",
                values,
            )
        else:
            await self.db.execute(
                """INSERT INTO stations
                   (callsign, source, first_heard, last_heard, packet_count,
                    latitude, longitude, symbol_table, symbol_code,
                    last_comment, last_path, last_port_name, last_raw, distance_km, heading)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    callsign, source, now, now,
                    latitude, longitude,
                    symbol_table, symbol_code,
                    comment, path, port_name, raw,
                    distance_km, heading,
                ),
            )
        if commit:
            await self.db.commit()

        # Return current station data
        result = await self.db.execute(
            "SELECT * FROM stations WHERE callsign = ? AND source = ?",
            (callsign, source),
        )
        row = await result.fetchone()
        return dict(row) if row else {}

    async def get_stations(
        self,
        source: Optional[str] = None,
        since: Optional[float] = None,
        max_distance: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Get stations with optional filters."""
        query = "SELECT * FROM stations WHERE 1=1"
        params = []

        if source:
            query += " AND source = ?"
            params.append(source)
        if since:
            query += " AND last_heard >= ?"
            params.append(since)
        if max_distance is not None:
            query += " AND (distance_km IS NULL OR distance_km <= ?)"
            params.append(max_distance)

        query += " ORDER BY last_heard DESC"

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_station(self, callsign: str, source: str) -> Optional[Dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM stations WHERE callsign = ? AND source = ?",
            (callsign, source),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_old_stations(self, max_age: float):
        """Remove stations not heard within max_age seconds."""
        cutoff = time.time() - max_age
        await self.db.execute("DELETE FROM stations WHERE last_heard < ?", (cutoff,))
        await self.db.commit()

    async def delete_station(self, callsign: str, source: str) -> bool:
        """Remove one station record. Returns True when a row was deleted."""
        cursor = await self.db.execute(
            "DELETE FROM stations WHERE callsign = ? AND source = ?",
            (callsign, source),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_max_rf_distance(self) -> float:
        cursor = await self.db.execute(
            "SELECT MAX(distance_km) FROM stations WHERE source = 'rf' AND distance_km IS NOT NULL"
        )
        row = await cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    async def get_rf_station_count(self, since: Optional[float] = None) -> int:
        query = "SELECT COUNT(*) FROM stations WHERE source = 'rf'"
        params = []
        if since:
            query += " AND last_heard >= ?"
            params.append(since)
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Packet operations ───────────────────────────────────────────

    async def log_packet(
        self,
        source: str,
        from_call: str,
        to_call: str = "",
        path: str = "",
        raw: str = "",
        packet_type: str = "",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        port_name: str = "",
        digipeated_by_me: bool = False,
        commit: bool = True,
    ):
        now = time.time()
        await self.db.execute(
            """INSERT INTO packets
               (timestamp, source, from_call, to_call, path, raw, packet_type, latitude, longitude, port_name, digipeated_by_me)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, source, from_call, to_call, path, raw, packet_type, latitude,
                longitude, port_name, 1 if digipeated_by_me else 0,
            ),
        )
        if commit:
            await self.db.commit()

    async def get_recent_packets(
        self, limit: int = 100, source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM packets"
        params = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_old_packets(self, max_age: float):
        cutoff = time.time() - max_age
        await self.db.execute("DELETE FROM packets WHERE timestamp < ?", (cutoff,))
        await self.db.commit()

    # ── Propagation log ─────────────────────────────────────────────

    async def add_message(
        self,
        direction: str,
        from_call: str,
        to_call: str,
        text: str = "",
        message_id: str = "",
        source: str = "",
        acked: bool = False,
        rejected: bool = False,
        dedupe_key: str = "",
        timestamp: Optional[float] = None,
        commit: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Persist a message. Returns None if a dedupe key already exists."""
        now = timestamp or time.time()
        cursor = await self.db.execute(
            """INSERT OR IGNORE INTO messages
               (timestamp, direction, from_call, to_call, text, message_id, source, acked, rejected, dedupe_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                direction,
                from_call,
                to_call,
                text,
                message_id,
                source,
                1 if acked else 0,
                1 if rejected else 0,
                dedupe_key,
            ),
        )
        if commit:
            await self.db.commit()
        if cursor.rowcount == 0:
            return None

        row = await self.db.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,))
        result = await row.fetchone()
        return self._message_row_to_dict(result) if result else None

    async def get_recent_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM messages ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._message_row_to_dict(r) for r in rows]

    async def update_message_status(
        self,
        to_call: str,
        message_id: str,
        acked: bool = False,
        rejected: bool = False,
    ):
        field = "acked" if acked else "rejected"
        await self.db.execute(
            f"""UPDATE messages SET {field} = 1
                WHERE direction = 'tx'
                  AND UPPER(to_call) = ?
                  AND message_id = ?""",
            ((to_call or "").upper(), message_id),
        )
        await self.db.commit()

    async def clear_messages(self):
        await self.db.execute("DELETE FROM messages")
        await self.db.commit()

    async def delete_old_messages(self, max_age: float):
        cutoff = time.time() - max_age
        await self.db.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
        await self.db.commit()

    @staticmethod
    def _message_row_to_dict(row: aiosqlite.Row) -> Dict[str, Any]:
        data = dict(row)
        data["from"] = data.pop("from_call")
        data["to"] = data.pop("to_call")
        data["acked"] = bool(data.get("acked"))
        data["rejected"] = bool(data.get("rejected"))
        return data

    async def upsert_message_contact(
        self,
        callsign: str,
        display_name: str = "",
        last_used: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        call = (callsign or "").strip().upper()
        if not call:
            return None
        now = time.time()
        await self.db.execute(
            """INSERT INTO message_contacts (callsign, display_name, created_at, updated_at, last_used)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(callsign) DO UPDATE SET
                   display_name = COALESCE(NULLIF(excluded.display_name, ''), message_contacts.display_name),
                   updated_at = excluded.updated_at,
                   last_used = COALESCE(excluded.last_used, message_contacts.last_used)""",
            (call, display_name, now, now, last_used),
        )
        await self.db.commit()
        return await self.get_message_contact(call)

    async def get_message_contacts(self) -> List[Dict[str, Any]]:
        cursor = await self.db.execute(
            """SELECT * FROM message_contacts
               ORDER BY COALESCE(last_used, updated_at, created_at) DESC, callsign ASC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_message_contact(self, callsign: str) -> Optional[Dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM message_contacts WHERE callsign = ?",
            ((callsign or "").strip().upper(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_message_contact(self, callsign: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM message_contacts WHERE callsign = ?",
            ((callsign or "").strip().upper(),),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def log_propagation(
        self,
        rf_count: int,
        max_dist: Optional[float],
        avg_dist: Optional[float],
        unique_1h: int,
        unique_6h: int,
        unique_24h: int,
        commit: bool = True,
    ):
        now = time.time()
        await self.db.execute(
            """INSERT INTO propagation_log
               (timestamp, rf_station_count, max_distance_km, avg_distance_km,
                unique_stations_1h, unique_stations_6h, unique_stations_24h)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, rf_count, max_dist, avg_dist, unique_1h, unique_6h, unique_24h),
        )
        if commit:
            await self.db.commit()

    async def get_propagation_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        cursor = await self.db.execute(
            "SELECT * FROM propagation_log WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Statistics ──────────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        now = time.time()
        stats = {}

        for label, seconds in [("1h", 3600), ("6h", 21600), ("24h", 86400)]:
            cutoff = now - seconds
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM stations WHERE source = 'rf' AND last_heard >= ?",
                (cutoff,),
            )
            row = await cursor.fetchone()
            stats[f"rf_stations_{label}"] = row[0] if row else 0

            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM stations WHERE source = 'aprs_is' AND last_heard >= ?",
                (cutoff,),
            )
            row = await cursor.fetchone()
            stats[f"is_stations_{label}"] = row[0] if row else 0

        # Max and avg distance for RF stations
        cursor = await self.db.execute(
            """SELECT MAX(distance_km), AVG(distance_km) FROM stations
               WHERE source = 'rf' AND distance_km IS NOT NULL AND last_heard >= ?""",
            (now - 3600,),
        )
        row = await cursor.fetchone()
        stats["max_distance_km"] = round(row[0], 1) if row and row[0] else 0
        stats["avg_distance_km"] = round(row[1], 1) if row and row[1] else 0

        # Total packets
        cursor = await self.db.execute("SELECT COUNT(*) FROM packets")
        row = await cursor.fetchone()
        stats["total_packets"] = row[0] if row else 0

        return stats

    # ── Ducting log ─────────────────────────────────────────────────

    async def log_ducting(
        self,
        ducting_index: float,
        pressure_mb: Optional[float],
        pressure_trend: Optional[float],
        temp_f: Optional[float],
        humidity: Optional[float],
        inversion_detected: bool = False,
    ):
        now = time.time()
        await self.db.execute(
            """INSERT INTO ducting_log
               (timestamp, ducting_index, pressure_mb, pressure_trend, temp_f, humidity, inversion_detected)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, ducting_index, pressure_mb, pressure_trend, temp_f, humidity, 1 if inversion_detected else 0),
        )
        await self.db.commit()

    async def get_ducting_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        cursor = await self.db.execute(
            "SELECT * FROM ducting_log WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── Path history ────────────────────────────────────────────────

    async def log_path_event(
        self,
        callsign: str,
        distance_km: Optional[float],
        heading: Optional[float],
        path: str = "",
        port_name: str = "",
        hop_count: int = 0,
        is_direct: bool = False,
        commit: bool = True,
    ):
        now = time.time()
        await self.db.execute(
            """INSERT INTO path_history
               (timestamp, callsign, distance_km, heading, path, port_name, hop_count, is_direct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, callsign, distance_km, heading, path, port_name, hop_count, 1 if is_direct else 0),
        )
        if commit:
            await self.db.commit()

    async def get_path_history(self, callsign: str, hours: int = 24) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        cursor = await self.db.execute(
            """SELECT * FROM path_history
               WHERE callsign = ? AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (callsign, cutoff),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_path_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        cursor = await self.db.execute(
            "SELECT * FROM path_history WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── First heard log ─────────────────────────────────────────────

    async def log_first_heard(
        self,
        callsign: str,
        source: str,
        distance_km: Optional[float],
        heading: Optional[float],
        latitude: Optional[float],
        longitude: Optional[float],
        path: str = "",
        port_name: str = "",
        hop_count: int = 0,
        is_direct: bool = False,
        commit: bool = True,
    ) -> bool:
        callsign = (callsign or "").strip().upper()
        source = (source or "").strip().lower()
        if not callsign or source not in {"rf", "aprs_is"}:
            return False
        now = time.time()
        cursor = await self.db.execute(
            """INSERT OR IGNORE INTO first_heard_log
               (timestamp, callsign, source, distance_km, heading, latitude, longitude, path, port_name, hop_count, is_direct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, callsign, source, distance_km, heading, latitude, longitude, path, port_name, hop_count, 1 if is_direct else 0),
        )
        if commit:
            await self.db.commit()
        return cursor.rowcount > 0

    async def get_first_heard_log(self, hours: int = 24, direct_only: bool = False) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        query = "SELECT * FROM first_heard_log WHERE timestamp >= ?"
        params = [cutoff]
        if direct_only:
            query += " AND source = 'rf' AND is_direct = 1"
        query += " ORDER BY timestamp DESC"
        cursor = await self.db.execute(
            query,
            params,
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["is_direct"] = bool(item.get("is_direct"))
            result.append(item)
        return result

    async def is_station_known(self, callsign: str, source: str) -> bool:
        """Check if a station has ever been seen before."""
        callsign = (callsign or "").strip().upper()
        source = (source or "").strip().lower()
        cursor = await self.db.execute(
            "SELECT 1 FROM stations WHERE callsign = ? AND source = ?",
            (callsign, source),
        )
        row = await cursor.fetchone()
        if row is not None:
            return True
        cursor = await self.db.execute(
            "SELECT 1 FROM first_heard_log WHERE UPPER(callsign) = ? AND source = ?",
            (callsign, source),
        )
        row = await cursor.fetchone()
        return row is not None

    # ── Export helpers ──────────────────────────────────────────────

    async def export_stations(self, source: Optional[str] = None, hours: Optional[int] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM stations WHERE 1=1"
        params = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if hours:
            cutoff = time.time() - (hours * 3600)
            query += " AND last_heard >= ?"
            params.append(cutoff)
        query += " ORDER BY last_heard DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def export_packets(self, hours: int = 24, source: Optional[str] = None) -> List[Dict[str, Any]]:
        cutoff = time.time() - (hours * 3600)
        query = "SELECT * FROM packets WHERE timestamp >= ?"
        params = [cutoff]
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY timestamp DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def export_propagation(self, hours: int = 24) -> List[Dict[str, Any]]:
        return await self.get_propagation_history(hours)
