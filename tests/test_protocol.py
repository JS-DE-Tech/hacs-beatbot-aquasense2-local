"""Critical local command guards without requiring Home Assistant or a robot."""

from __future__ import annotations

import importlib
import pathlib
import sys
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "beatbot_aquasense2_local"

package = types.ModuleType("custom_components.beatbot_aquasense2_local")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package


class FakeDevice:
    dps: dict = {}
    writes: list = []

    def __init__(self, *_args, **_kwargs):
        self.retry_limit = 5

    def set_socketTimeout(self, _value):
        pass

    def set_socketRetryLimit(self, value):
        self.retry_limit = value

    def set_socketPersistent(self, _value):
        pass

    def status(self):
        if self.retry_limit < 1:
            return {"Err": "905"}
        return {"dps": self.dps}

    def set_value(self, dp, value):
        self.writes.append((str(dp), value))
        return {"dps": {str(dp): value}}

    def close(self):
        pass


tuya = types.ModuleType("tinytuya")
tuya.Device = FakeDevice
tuya.scanner = types.SimpleNamespace(devices=lambda **_kwargs: {})
sys.modules["tinytuya"] = tuya

protocol = importlib.import_module("custom_components.beatbot_aquasense2_local.protocol")
policy = importlib.import_module("custom_components.beatbot_aquasense2_local.policy")


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        FakeDevice.writes = []
        self.client = protocol.LocalBeatbot("test-device", "192.168.1.2", "0123456789abcdef")

    def test_parking_is_not_sent_on_dry_dock(self):
        FakeDevice.dps = {"6": 80, "154": 0, "165": 5}
        result = self.client.poll(park_due=True)
        self.assertFalse(result.park_sent)
        self.assertEqual(FakeDevice.writes, [])

    def test_status_opens_at_least_one_connection(self):
        FakeDevice.dps = {"6": 98, "165": 6}
        self.assertEqual(self.client.poll().dps["6"], 98)

    def test_poll_sets_finite_socket_timeout_and_retry_limit(self):
        FakeDevice.dps = {"6": 98, "165": 6}
        with patch.object(FakeDevice, "set_socketTimeout") as timeout:
            self.client.poll()
        timeout.assert_called_once_with(2)

    def test_stop_after_status_prevents_writes_and_closes_socket(self):
        def status(device):
            self.client.request_stop()
            return {"dps": {"6": 98, "165": 6}}
        with patch.object(FakeDevice, "status", status), patch.object(FakeDevice, "close") as close:
            with self.assertRaises(protocol.BeatbotConnectionError):
                self.client.poll(mode_to_set="Standard")
            close.assert_called_once()
        self.assertEqual(FakeDevice.writes, [])

    def test_discovery_is_passive_and_duration_is_bounded(self):
        for seconds in [0, -1, 13, None, float("inf"), True]:
            with self.assertRaises(ValueError):
                protocol.discover(seconds=seconds)
        with patch.object(tuya.scanner, "devices", return_value={}) as scan:
            protocol.discover("robot", 6)
        self.assertEqual(scan.call_args.kwargs["scantime"], 6)
        self.assertFalse(scan.call_args.kwargs["poll"])
        self.assertFalse(scan.call_args.kwargs["forcescan"])

    def test_parking_is_sent_once_when_cleaning_in_pool(self):
        FakeDevice.dps = {"6": 80, "154": 1, "165": 5}
        result = self.client.poll(park_due=True)
        self.assertTrue(result.park_sent)
        self.assertEqual(FakeDevice.writes, [("152", 1)])

    def test_parking_stops_at_reported_completion(self):
        FakeDevice.dps = {"6": 80, "154": 1, "165": 15}
        result = self.client.poll(park_due=True)
        self.assertFalse(result.park_sent)
        self.assertEqual(FakeDevice.writes, [])

    def test_mode_preselection_never_starts_cleaning(self):
        FakeDevice.dps = {"6": 80, "154": 0, "165": 6}
        result = self.client.poll(mode_to_set="Standard")
        self.assertTrue(result.mode_confirmed)
        self.assertEqual(FakeDevice.writes, [("132", "AAAAAw==")])

    def test_mode_change_waits_during_cleaning(self):
        FakeDevice.dps = {"6": 80, "154": 1, "165": 5}
        result = self.client.poll(mode_to_set="Boden")
        self.assertFalse(result.mode_confirmed)
        self.assertEqual(FakeDevice.writes, [])

    def test_charge_cutoff_rejects_old_sample(self):
        started = datetime.now(timezone.utc)
        old_sample = started - timedelta(seconds=5)
        self.assertFalse(policy.charge_cutoff_due(True, 99, 80, started, old_sample))

    def test_charge_cutoff_requires_plug_on_and_target(self):
        started = datetime.now(timezone.utc)
        self.assertFalse(policy.charge_cutoff_due(False, 100, 80, started, started))
        self.assertFalse(policy.charge_cutoff_due(True, 79, 80, started, started))
        self.assertTrue(policy.charge_cutoff_due(True, 80, 80, started, started))

    def test_discovery_filters_model_and_drops_secrets(self):
        original = tuya.scanner.devices
        tuya.scanner.devices = lambda **_kwargs: {
            "a": {"id": "right", "productKey": "c64wbaic8jnkqgix", "ip": "192.168.1.2",
                  "version": "3.3", "key": "must-not-escape", "token": "must-not-escape"},
            "b": {"id": "other", "productKey": "different", "ip": "192.168.1.3"},
            "c": {"id": "remote", "productKey": "c64wbaic8jnkqgix", "ip": "8.8.8.8"},
        }
        try:
            self.assertEqual(protocol.discover(), [{"device_id": "right", "host": "192.168.1.2", "version": "3.3"}])
        finally:
            tuya.scanner.devices = original

    def test_decodes_verified_mode_payload(self):
        self.assertEqual(protocol.decode_mode("AAAAAw=="), "Standard")

    def test_filter_basket_known_fault_values(self):
        self.assertIs(protocol.decode_filter_basket_missing(2), True)
        self.assertIs(protocol.decode_filter_basket_missing(0), False)

    def test_filter_basket_other_codes_and_types_are_unknown(self):
        for value in (None, True, False, "2", "0", 2.0, -1, 1, 3, 6, {}, []):
            with self.subTest(value=value):
                self.assertIsNone(protocol.decode_filter_basket_missing(value))

    def test_filter_fault_status_is_read_only(self):
        FakeDevice.dps = {"107": 2, "165": 0}
        self.assertEqual(self.client.poll().dps["107"], 2)
        self.assertEqual(FakeDevice.writes, [])


if __name__ == "__main__":
    unittest.main()
