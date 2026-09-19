import unittest
from urllib.parse import parse_qs, urlparse

from server.config import Config
from server.external_propagation import PskReporterManager


XML = b'''<?xml version="1.0"?>
<receptionReports>
  <receptionReport receiverCallsign="W1AAA" receiverLocator="FN42" senderCallsign="K5YVY" senderLocator="EM54" frequency="50313000" flowStartSeconds="1790000000" mode="FT8" />
  <receptionReport receiverCallsign="K5YVY-1" receiverLocator="EM54" senderCallsign="W4BBB" senderLocator="EM85" frequency="144174000" flowStartSeconds="1790000010" mode="FT8" />
  <receptionReport receiverCallsign="W9ZZZ" receiverLocator="EN50" senderCallsign="W8CCC" senderLocator="EN80" frequency="144174000" flowStartSeconds="1790000020" mode="FT8" />
</receptionReports>'''


class PskReporterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config()
        self.config.station.callsign = "K5YVY-1"
        self.config.propagation.psk_reporter_enabled = True
        self.config.propagation.psk_reporter_window_minutes = 45

    async def test_station_specific_vhf_reports_are_summarized(self):
        urls = []

        def fetch(url):
            urls.append(url)
            return XML

        manager = PskReporterManager(self.config, fetch_xml=fetch)
        await manager.poll_once()
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["report_count"], 2)
        self.assertEqual(snapshot["unique_peers"], 2)
        self.assertEqual(snapshot["bands"], {"2 m": 1, "6 m": 1})
        self.assertGreater(snapshot["max_distance_km"], 0)
        self.assertFalse(snapshot["stale"])
        query = parse_qs(urlparse(urls[0]).query)
        self.assertEqual(query["callsign"], ["K5YVY"])
        self.assertEqual(query["flowStartSeconds"], ["-2700"])
        self.assertEqual(query["frange"], ["50000000-1500000000"])

    async def test_placeholder_callsign_disables_queries(self):
        self.config.station.callsign = "N0CALL"
        manager = PskReporterManager(self.config, fetch_xml=lambda _: (_ for _ in ()).throw(AssertionError()))
        await manager.poll_once()
        self.assertFalse(manager.snapshot()["enabled"])


if __name__ == "__main__":
    unittest.main()
