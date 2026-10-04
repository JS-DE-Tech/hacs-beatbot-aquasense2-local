"""Real observed surface sequence, restart deduplication and unknown states."""

import importlib
import unittest
import test_protocol

Tracker = importlib.import_module("custom_components.beatbot_aquasense2_local.completion").CompletionTracker


class CompletionTests(unittest.TestCase):
    def test_program_is_frozen_across_partial_reports_pause_and_restore(self):
        tracker = Tracker()
        tracker.observe("cleaning", 1, 0, "Bereich:floor=2:wall=2")
        for state in (None, "paused", "diving", "emerge", "standby"):
            tracker.observe(state, 1, 100, "ECO")
            self.assertEqual(tracker.program_key, "Bereich:floor=2:wall=2")
        restored = Tracker()
        restored.restore(tracker.dump())
        self.assertTrue(restored.observe("auto_dock", 1, 200, "ECO"))
        self.assertEqual(restored.program_key, "Bereich:floor=2:wall=2")

    def test_new_run_and_idle_clear_previous_program(self):
        tracker = Tracker()
        tracker.observe("cleaning", 1, 0, "Boden")
        self.assertTrue(tracker.observe("clean_done", 1, 100))
        tracker.observe("diving", 1, 200, "Standard")
        self.assertEqual(tracker.program_key, "Standard")
        tracker.observe("standby", 0, 300)
        self.assertIsNone(tracker.program_key)
        tracker.observe("emerge", 2, 400)
        self.assertTrue(tracker.observe("auto_dock", 1, 500))
        self.assertIsNone(tracker.program_key)

    def test_legacy_or_invalid_saved_program_stays_unknown(self):
        for key in (None, "invalid", [], 123):
            with self.subTest(key=key):
                tracker = Tracker()
                tracker.restore({"active": True, "emerged_at": 100, "program_key": key})
                self.assertTrue(tracker.observe("auto_dock", 1, 200, "Boden"))
                self.assertIsNone(tracker.program_key)

    def test_surface_standby_park_finishes_once_until_new_run(self):
        tracker = Tracker()
        for state, pos, now in (("cleaning", 1, 0), ("diving", 1, 5), ("emerge", 2, 3000), ("standby", 1, 3050)):
            self.assertFalse(tracker.observe(state, pos, now))
        self.assertTrue(tracker.observe("auto_dock", 1, 3100))
        for state in ("auto_dock", "emerge", "auto_dock", "clean_done", None):
            self.assertFalse(tracker.observe(state, 1, 3150))
        tracker.observe("diving", 1, 4000)
        tracker.observe("emerge", 2, 7000)
        self.assertTrue(tracker.observe("auto_dock", 1, 7100))

    def test_restart_between_surface_and_park_or_after_completion(self):
        tracker = Tracker()
        tracker.observe("emerge", 2, 100)
        restored = Tracker()
        restored.restore(tracker.dump())
        self.assertTrue(restored.observe("auto_dock", 1, 200))
        again = Tracker()
        again.restore(restored.dump())
        self.assertFalse(again.observe("auto_dock", 1, 210))

    def test_park_alone_stale_surface_and_dry_readiness_are_not_completion(self):
        for sequence in ((('auto_dock', 1, 100),),
                         (("emerge", 2, 100), ("auto_dock", 1, 701)),
                         (("emerge", 2, 100), ("standby", 0, 120), ("auto_dock", 1, 130))):
            tracker = Tracker()
            for state, pos, now in sequence:
                self.assertFalse(tracker.observe(state, pos, now))

    def test_explicit_clean_done_needs_a_run_and_is_once_only(self):
        tracker = Tracker()
        self.assertFalse(tracker.observe("clean_done", 1, 0))
        tracker.observe("cleaning", 1, 1)
        self.assertTrue(tracker.observe("clean_done", 1, 100))
        self.assertFalse(tracker.observe("clean_done", 1, 105))
