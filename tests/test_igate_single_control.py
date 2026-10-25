import unittest
from server.config import Config
from server.igate import IGate


class SingleIGateControlTests(unittest.TestCase):
    def test_one_live_controller_obeys_master_and_direction_switches(self):
        config=Config()
        config.station.callsign='W1AW'
        gate=IGate(config)
        raw='K2SRC>APRS::K1DEST   :Test message'
        self.assertFalse(config.igate.is_to_rf)
        config.igate.enabled=True
        gate.note_rf_station('K1DEST')
        self.assertIsNone(gate.should_gate_is_to_rf(raw,'K2SRC'))
        config.igate.is_to_rf=True
        self.assertIsNotNone(gate.should_gate_is_to_rf(raw,'K2SRC'))
        config.igate.is_to_rf=False
        self.assertIsNone(gate.should_gate_is_to_rf(raw+'2','K2SRC'))
        config.igate.is_to_rf=True
        config.igate.enabled=False
        self.assertIsNone(gate.should_gate_is_to_rf(raw+'3','K2SRC'))
        self.assertIsNone(gate.should_gate_rf_to_is('K2SRC>APRS:>Test','K2SRC'))

    def test_disabled_controller_does_not_collect_station_history(self):
        config=Config();config.igate.enabled=False
        gate=IGate(config)
        gate.note_rf_station('K1DEST');gate.note_is_station('K2SRC')
        self.assertEqual(gate._rf_stations,{})
        self.assertEqual(gate._is_stations,{})
