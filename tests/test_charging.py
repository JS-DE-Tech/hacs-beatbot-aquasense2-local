"""Cooldown boundaries, restoration and manual override."""

import importlib
import unittest
import test_runtime  # Bootstrap the integration package without Home Assistant.

Charging = importlib.import_module("custom_components.beatbot_aquasense2_local.charging").CooldownCharging


class ChargingTests(unittest.TestCase):
    def completed(self, battery, target=100):
        plan = Charging()
        plan.observe("cleaning", 90, 0)
        plan.observe("auto_dock", battery, 3600, True, target)
        return plan

    def test_below_target_starts_two_hours_without_sleep(self):
        plan = self.completed(69)
        self.assertEqual(plan.state, "cooling")
        plan.observe(None, None, 4000)
        self.assertEqual(plan.deadline, 10800)
        plan.observe("sleep", 69, 5000)
        self.assertEqual(plan.deadline, 10800)
        self.assertFalse(plan.due(10799))
        self.assertTrue(plan.due(10800))
        plan.observe("sleep", 68, 6000)
        self.assertEqual(plan.deadline, 10800)

    def test_at_or_above_selected_target_does_not_schedule(self):
        for target, battery in ((80, 80), (80, 100), (100, 100)):
            plan = self.completed(battery, target)
            plan.observe("sleep", battery, 5000)
            self.assertFalse(plan.due(100000))

    def test_missing_battery_waits_for_any_known_value(self):
        plan = self.completed(None)
        plan.observe("sleep", None, 5000)
        self.assertEqual(plan.state, "waiting_for_battery")
        plan.observe("sleep", 60, 6000)
        self.assertEqual(plan.deadline, 13200)

    def test_sleep_without_completed_run_never_arms(self):
        plan = Charging()
        plan.observe("sleep", 20, 5000)
        self.assertEqual(plan.state, "idle")
        plan.observe("cleaning", 30, 6000)
        plan.observe("sleep", 20, 7000)
        self.assertIsNone(plan.deadline)

    def test_restart_retains_deadline(self):
        plan = self.completed(60)
        plan.observe("sleep", 60, 5000)
        restored = Charging()
        restored.restore(plan.dump())
        self.assertTrue(restored.due(10800))

    def test_79_and_99_follow_the_selected_target(self):
        self.assertEqual(self.completed(79, 80).state, "cooling")
        self.assertEqual(self.completed(99, 100).state, "cooling")

    def test_second_run_cancels_old_deadline_until_new_completion(self):
        plan = self.completed(60)
        plan.observe("diving", 60, 4000)
        self.assertIsNone(plan.deadline)
        self.assertFalse(plan.due(20000))
        plan.observe(None, 60, 6000)
        self.assertIsNone(plan.deadline)
        plan.observe("auto_dock", 40, 8000, True, 80)
        self.assertEqual(plan.deadline, 15200)

    def test_legacy_four_hour_plan_is_not_reinterpreted(self):
        plan = Charging()
        plan.restore({"state": "cooling", "deadline": 10000})
        self.assertEqual(plan.state, "idle")
        self.assertFalse(plan.due(20000))

    def test_manual_and_new_run_cancel_timer(self):
        for action in ("manual", "new_run"):
            plan = self.completed(60)
            plan.observe("sleep", 60, 5000)
            if action == "manual":
                plan.manual()
                plan.observe("clean_done", 60, 6000)
                plan.observe("sleep", 60, 6100)
            else:
                plan.observe("cleaning", 60, 6000)
            self.assertFalse(plan.due(30000))

    def test_ambiguous_start_is_not_replayed_after_restart(self):
        plan = Charging()
        plan.restore({"policy_version": 2, "state": "starting", "deadline": 1})
        self.assertEqual(plan.state, "start_uncertain")
        self.assertFalse(plan.due(30000))
