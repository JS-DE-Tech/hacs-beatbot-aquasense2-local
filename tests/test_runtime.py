"""Deterministic learning tests: no device, secrets or Home Assistant needed."""

import importlib
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

name = "custom_components.beatbot_aquasense2_local"
if name not in sys.modules:
    package = types.ModuleType(name)
    package.__path__ = [str(pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "beatbot_aquasense2_local")]
    sys.modules[name] = package
runtime = importlib.import_module(f"{name}.runtime")
Program, Learner = runtime.Program, runtime.RuntimeLearner


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.learner = Learner()
        self.program = Program("Standard")

    def run_sample(self, start, duration=3600, program=None):
        program = program or self.program
        self.learner.observe("standby", program, start - 5)
        self.learner.observe("cleaning", program, start)
        self.learner.observe("cleaning", program, start + duration - 5)
        self.learner.observe("clean_done", program, start + duration)

    def test_two_samples_then_three_and_median(self):
        self.run_sample(100)
        self.assertIsNone(self.learner.estimate("Standard")["estimated_seconds"])
        self.run_sample(5000, 4200)
        self.assertEqual(self.learner.estimate("Standard")["estimated_seconds"], 3900)
        self.assertEqual(self.learner.estimate("Standard")["learning_state"], "preliminary")
        self.run_sample(10000, 3660)
        self.assertEqual(self.learner.estimate("Standard")["estimated_seconds"], 3660)
        self.assertEqual(self.learner.estimate("Standard")["learning_state"], "learned")

    def test_all_combinations_have_unique_roundtrip_keys(self):
        programs = [Program("Bereich", f, w) for f in range(3) for w in range(3) if f or w]
        programs += [Program("MultiZone", duration=d) for d in runtime.MULTI_DURATIONS]
        programs += [Program(m) for m in ("Boden", "Standard", "ECO")]
        self.assertEqual(len({p.key for p in programs}), 14)
        for p in programs:
            self.assertEqual(Program.from_dps(p.writes()).key, p.key)
        with self.assertRaises(ValueError):
            Program("Bereich", 0, 0)

    def test_history_isolation_and_persistence(self):
        p = Program("Bereich", 2, 1)
        self.run_sample(100, program=p)
        self.run_sample(5000, program=p)
        restored = Learner()
        restored.restore(json.loads(json.dumps(self.learner.dump())))
        self.assertEqual(restored.estimate(p.key)["sample_count"], 2)
        self.assertIsNone(restored.estimate(Program("Bereich", 1, 2).key)["estimated_seconds"])
        self.assertIsNone(restored.estimate("Standard")["estimated_seconds"])

    def test_offline_countdown_does_not_complete_run(self):
        self.run_sample(100)
        self.run_sample(5000)
        self.learner.observe("standby", self.program, 9995)
        self.learner.observe("cleaning", self.program, 10000)
        self.assertEqual(self.learner.remaining(10600)["remaining_seconds"], 3000)
        self.assertTrue(self.learner.remaining(14000)["overdue"])
        self.assertIsNotNone(self.learner.active)
        self.assertEqual(self.learner.estimate("Standard")["sample_count"], 2)

    def test_late_completion_after_underwater_gap_not_learned(self):
        self.learner.observe("standby", self.program, 0)
        self.learner.observe("cleaning", self.program, 5)
        self.learner.observe("clean_done", self.program, 4000)
        self.assertEqual(self.learner.history, {})

    def test_first_observation_mid_run_not_learned(self):
        self.learner.observe("cleaning", self.program, 5)
        self.learner.observe("cleaning", self.program, 3595)
        self.learner.observe("clean_done", self.program, 3600)
        self.assertEqual(self.learner.history, {})

    def test_parking_pause_and_abort_not_learned(self):
        for state, parking in [("cleaning", True), ("paused", False), ("auto_dock", False), ("charging", False)]:
            with self.subTest(state=state, parking=parking):
                learner = Learner()
                learner.observe("standby", self.program, 0)
                learner.observe("cleaning", self.program, 5)
                learner.observe(state, self.program, 200, parking)
                learner.observe("cleaning", self.program, 3595)
                learner.observe("clean_done", self.program, 3600)
                # Charging followed by cleaning is a new bounded start, but
                # here the gap is too long to accept it.
                self.assertEqual(learner.history, {})

    def test_restart_preserves_history_but_excludes_interrupted_run(self):
        self.run_sample(100)
        self.learner.observe("standby", self.program, 4995)
        self.learner.observe("cleaning", self.program, 5000)
        restored = Learner()
        restored.restore(json.loads(json.dumps(self.learner.dump())))
        restored.observe("cleaning", self.program, 8595)
        restored.observe("clean_done", self.program, 8600)
        self.assertEqual(restored.estimate("Standard")["sample_count"], 1)

    def test_changed_program_and_missing_details_not_misattributed(self):
        self.learner.observe("standby", self.program, 0)
        self.learner.observe("cleaning", self.program, 5)
        self.learner.observe("cleaning", Program("Boden"), 3595)
        self.learner.observe("clean_done", Program("Boden"), 3600)
        self.assertEqual(self.learner.history, {})
        self.assertIsNone(Program.from_dps({"132": runtime.encode_raw(2), "114": 1, "115": 1}))
        self.assertIsNone(Program.from_dps({"132": runtime.encode_raw(6)}))

    def test_completion_not_double_counted_and_history_bounded(self):
        for index in range(12):
            self.run_sample(index * 5000 + 100)
        self.learner.observe("clean_done", self.program, 58701)
        self.assertEqual(self.learner.estimate("Standard")["sample_count"], 10)

    def test_options_write_exact_app_dps_and_require_all_echoes(self):
        protocol = importlib.import_module(f"{name}.protocol")
        from test_protocol import FakeDevice
        FakeDevice.dps = {"165": 6}
        FakeDevice.writes = []
        client = protocol.LocalBeatbot("test", "192.168.1.2", "0123456789abcdef")
        program = Program("Bereich", 2, 0)
        self.assertTrue(client.poll(mode_to_set=program).mode_confirmed)
        self.assertEqual(FakeDevice.writes, list(program.writes().items()))
        with patch.object(FakeDevice, "set_value", return_value={"dps": {"132": runtime.encode_raw(2)}}):
            self.assertFalse(client.poll(mode_to_set=program).mode_confirmed)

    def floor_run(self, learner=None, *, parking=False, pause=False, restart=False,
                  start_battery=100, end_battery=81, transient=True):
        learner = learner or self.learner
        p = Program("Boden")
        learner.observe("standby", p, 0, battery=start_battery, position=0)
        learner.observe("cleaning", p, 5, battery=start_battery, position=1)
        learner.observe("diving", p, 10, position=1)
        if pause:
            learner.observe("paused", p, 100)
        if restart:
            restored = Learner()
            restored.restore(learner.dump())
            learner = restored
        # >1h underwater, then observed return/edge phase (no clean_done).
        learner.observe("emerge", p, 4300, parking=parking, position=2)
        if transient:
            learner.observe("standby", p, 4560, position=1)
        completed = learner.observe("auto_dock", p, 4565, battery=end_battery, position=1)
        return learner, completed

    def test_floor_surface_edge_is_completion_not_pickup(self):
        learner, completed = self.floor_run()
        self.assertTrue(completed)
        self.assertEqual(learner.history, {"Boden": [4560]})
        self.assertEqual(learner.battery_history, {"Boden": [19]})
        self.assertIsNone(learner.active)
        for state, at in [("auto_dock", 4600), ("dock", 5000), ("standby", 5400), ("sleep", 5500)]:
            self.assertFalse(learner.observe(state, Program("Boden"), at, battery=60, position=0))
        self.assertEqual(learner.history["Boden"], [4560])

    def test_floor_interrupted_or_restart_is_not_learned(self):
        for kwargs in ({"parking": True}, {"pause": True}, {"restart": True}):
            with self.subTest(kwargs=kwargs):
                learner, completed = self.floor_run(Learner(), **kwargs)
                self.assertFalse(completed)
                self.assertEqual(learner.history, {})
                self.assertEqual(learner.battery_history, {})

    def test_floor_requires_surface_sequence_and_bounded_return(self):
        for surface, end, position in [(None, 4000, 1), (100, 4000, 1), (3900, 4000, 0)]:
            learner = Learner()
            p = Program("Boden")
            learner.observe("standby", p, 0)
            learner.observe("cleaning", p, 5)
            if surface:
                learner.observe("emerge", p, surface)
            learner.observe("standby", p, end - 1, position=position)
            self.assertFalse(learner.observe("auto_dock", p, end))
            self.assertEqual(learner.history, {})

    def test_other_modes_do_not_inherit_floor_auto_dock_rule(self):
        for p in (Program("Standard"), Program("ECO"), Program("Bereich", 2, 0), Program("MultiZone")):
            learner = Learner()
            learner.observe("standby", p, 0)
            learner.observe("cleaning", p, 5)
            learner.observe("emerge", p, 3000)
            self.assertFalse(learner.observe("auto_dock", p, 3200))
            self.assertEqual(learner.history, {})

    def test_fresh_ready_battery_can_bridge_missing_start_dp(self):
        learner = Learner()
        p = Program("Boden")
        learner.observe("standby", p, 0, battery=80)
        learner.observe("cleaning", p, 5)
        learner.observe("emerge", p, 3000)
        learner.observe("auto_dock", p, 3200, battery=66)
        self.assertEqual(learner.battery_history, {"Boden": [14]})

    def test_missing_or_increasing_battery_never_creates_consumption(self):
        for start, end in [(None, 66), (80, None), (80, 90), (True, 20)]:
            learner, completed = self.floor_run(Learner(), start_battery=start, end_battery=end)
            self.assertTrue(completed)
            self.assertEqual(learner.battery_history, {})

    def test_battery_warning_threshold_is_conservative_isolated_and_fresh(self):
        self.learner.battery_history = {"Boden": [19, 14]}
        estimate = self.learner.battery_estimate("Boden", 23, stale=False)
        self.assertEqual(estimate["estimated_consumption_percent"], 16.5)
        self.assertEqual(estimate["required_battery_percent"], 24)
        self.assertTrue(estimate["insufficient"])
        self.assertFalse(self.learner.battery_estimate("Boden", 24, stale=False)["insufficient"])
        for key, battery, stale in [("Boden", 23, True), ("Boden", None, False), ("Standard", 5, False)]:
            self.assertIsNone(self.learner.battery_estimate(key, battery, stale=stale)["insufficient"])

    def test_battery_history_roundtrip_and_invalid_values(self):
        self.learner.restore({"battery_history": {"Boden": [14, 19, -1, 101, True, float("nan")]}})
        restored = Learner()
        restored.restore(json.loads(json.dumps(self.learner.dump())))
        self.assertEqual(restored.battery_history, {"Boden": [14, 19]})

    def test_floor_end_with_changed_program_is_excluded(self):
        p = Program("Boden")
        self.learner.observe("standby", p, 0)
        self.learner.observe("cleaning", p, 5)
        self.learner.observe("emerge", p, 3000)
        self.learner.observe("auto_dock", Program("Standard"), 3200)
        self.assertEqual(self.learner.history, {})


if __name__ == "__main__":
    unittest.main()
