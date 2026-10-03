"""Runtime import validation, deduplication and rollback without real HA."""

import importlib
import json
import unittest

import test_runtime

runtime_file = importlib.import_module("custom_components.beatbot_aquasense2_local.runtime_file")


class RuntimeImportTests(unittest.TestCase):
    def payload(self):
        return {"format": "beatbot-runtime-v1", "device_id": "test",
                "samples": [{"id": "run-1", "confirmed": True, "program": {"mode": "Boden"},
                             "duration_seconds": 4560},
                            {"id": "run-2", "confirmed": True, "program": {"mode": "Boden"},
                             "duration_seconds": 3193}]}

    def parse(self, payload):
        return runtime_file.parse_runtime_file(json.dumps(payload).encode(), "test")

    def test_two_confirmed_samples_deduplicated_persisted_no_fake_battery(self):
        learner = test_runtime.Learner()
        samples = self.parse(self.payload())
        self.assertEqual(learner.import_samples(samples), 2)
        self.assertEqual(learner.estimate("Boden")["estimated_seconds"], 3876.5)
        self.assertEqual(learner.import_samples(samples), 0)
        restored = test_runtime.Learner()
        restored.restore(learner.dump())
        self.assertEqual(restored.import_samples(samples), 0)
        self.assertEqual(restored.estimate("Boden")["sample_count"], 2)
        self.assertEqual(restored.battery_history, {})

    def test_battery_endpoints_and_combinations(self):
        payload = self.payload()
        payload["samples"][0].update(start_battery=100, end_battery=81, program={"mode": "Bereich", "floor": 2, "wall": 0})
        learner = test_runtime.Learner()
        learner.import_samples(self.parse(payload))
        self.assertEqual(learner.battery_history, {"Bereich:floor=2:wall=0": [19]})

    def test_conflicting_id_rejected_atomically(self):
        learner = test_runtime.Learner()
        learner.import_samples(self.parse(self.payload()))
        before = json.dumps(learner.dump(), sort_keys=True)
        payload = self.payload()
        payload["samples"][0]["id"] = "new-run"
        payload["samples"][1]["duration_seconds"] = 4000
        with self.assertRaises(ValueError):
            learner.import_samples(self.parse(payload))
        self.assertEqual(json.dumps(learner.dump(), sort_keys=True), before)

    def test_invalid_files_and_samples(self):
        for field, value in [("device_id", "other"), ("format", "other"), ("samples", []), ("samples", [False])]:
            payload = self.payload()
            payload[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.parse(payload)
        for fields in [dict(confirmed=False), dict(duration_seconds=True), dict(duration_seconds=0),
                       dict(duration_seconds=float("nan")), dict(duration_seconds=float("inf")),
                       dict(start_battery=80), dict(start_battery=80, end_battery=81),
                       dict(program={"mode": "Bereich"}), dict(program={"mode": "MultiZone"}),
                       dict(program={"mode": "unknown"}), dict(id=""), dict(id="run-2")]:
            payload = self.payload()
            payload["samples"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.parse(payload)
        for data in [b"x" * (runtime_file.MAX_FILE_BYTES + 1), b"\xff", b"[]"]:
            with self.assertRaises(ValueError):
                runtime_file.parse_runtime_file(data, "test")
