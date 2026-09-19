"""Regression tests for SQLite versions shipped by supported Linux systems."""

import unittest

from server.database import Database


class _Pre335SQLiteGuard:
    """Connection proxy that rejects SQL unavailable before SQLite 3.35."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, *args, **kwargs):
        if "RETURNING" in sql.upper():
            raise AssertionError("RETURNING requires SQLite 3.35 or newer")
        return self._connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class SQLiteCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.initialize()
        self.db.db = _Pre335SQLiteGuard(self.db.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_station_upsert_works_without_returning_clause(self):
        inserted = await self.db.upsert_station(
            "W1ABC",
            "aprs_is",
            latitude=35.0,
            longitude=-90.0,
            comment="first",
        )
        updated = await self.db.upsert_station(
            "W1ABC",
            "aprs_is",
            comment="second",
        )

        self.assertEqual(inserted["packet_count"], 1)
        self.assertEqual(updated["packet_count"], 2)
        self.assertEqual(updated["last_comment"], "second")
        self.assertEqual(updated["latitude"], 35.0)
        self.assertEqual(updated["longitude"], -90.0)


if __name__ == "__main__":
    unittest.main()
