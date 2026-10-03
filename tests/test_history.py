"""Round-trip backups and atomic, per-combination manual runtime edits."""

import copy
import json
import unittest
from unittest.mock import AsyncMock
import test_manager
import test_runtime_file

files = test_runtime_file.runtime_file
module = test_manager.manager_module


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_manager.ManagerTests.asyncSetUp
    service = test_manager.ManagerTests.service

    async def test_export_all_combinations_and_roundtrip_including_battery_and_manual_estimates(self):
        self.manager.runtime.history = {"Boden": [4560, 3193]}
        self.manager.runtime.battery_history = {"Boden": [19, 14]}
        self.manager.runtime.manual_seconds = {"Standard": 3600}
        self.manager.runtime.imported_samples = {"sample-1": "a" * 64}
        payload = await self.manager.async_export_runtime()
        self.assertEqual(len(payload["programs"]), 14)
        self.assertNotIn(self.manager.entry.data["local_key"], json.dumps(payload))
        parsed = files.parse_runtime_file(json.dumps(payload).encode(), "test")
        self.manager.runtime.history = {}
        await self.manager.async_restore_runtime_backup(parsed)
        self.assertEqual(self.manager.runtime.history["Boden"], [4560, 3193])
        self.assertEqual(self.manager.runtime.battery_history["Boden"], [19, 14])
        self.assertEqual(self.manager.runtime.estimate("Standard")["estimated_seconds"], 3600)
        self.assertEqual(self.manager.runtime.imported_samples, {"sample-1": "a" * 64})
        self.assertEqual(await self.manager.async_export_runtime(), payload)

    async def test_manual_override_is_immediate_and_can_be_removed_without_faking_samples(self):
        await self.manager.async_edit_runtime("Boden", [], 3600)
        estimate = self.manager.runtime.estimate("Boden")
        self.assertEqual(estimate["estimated_seconds"], 3600)
        self.assertEqual(estimate["sample_count"], 0)
        self.assertEqual(estimate["learning_state"], "manual")
        await self.manager.async_edit_runtime("Boden", [4000, 4200], None)
        self.assertEqual(self.manager.runtime.estimate("Boden")["estimated_seconds"], 4100)
        self.assertIsNone(self.manager.runtime.estimate("Standard")["estimated_seconds"])

    async def test_history_edit_and_backup_restore_roll_back_on_storage_error(self):
        self.manager.runtime.history = {"Boden": [4000, 4200]}
        original = copy.deepcopy(self.manager.runtime.dump())
        payload = await self.manager.async_export_runtime()
        parsed = files.parse_runtime_file(json.dumps(payload).encode(), "test")
        parsed["history"]["Boden"] = [1000]
        self.manager.store.async_save.side_effect = OSError("disk unavailable")
        for action in (lambda: self.manager.async_edit_runtime("Boden", [1000], 2000),
                       lambda: self.manager.async_restore_runtime_backup(parsed)):
            with self.assertRaises(OSError):
                await action()
            self.assertEqual(self.manager.runtime.dump(), original)

    async def test_editing_unknown_program_run_is_blocked_without_runtime_training(self):
        self.manager.completion.active = True
        self.assertIsNone(self.manager.runtime.active)
        with self.assertRaises(RuntimeError):
            await self.manager.async_edit_runtime("Boden", [1000], None)
        self.manager.store.async_save.assert_not_awaited()

    async def test_invalid_history_files_rejected_before_mutation(self):
        payload = await self.manager.async_export_runtime()
        for mutate in (lambda p: p.update(device_id="another-robot"),
                       lambda p: p["programs"].pop(),
                       lambda p: p["programs"][0].update(duration_seconds=[float("nan")]),
                       lambda p: p["programs"][0].update(manual_seconds=True),
                       lambda p: p["programs"][0].update(battery_used=[101]),
                       lambda p: p["programs"][0].update(battery_used=[1.5]),
                       lambda p: p.update(imported_samples={"x": "not-a-fingerprint"}),
                       lambda p: p["programs"].__setitem__(1, p["programs"][0])):
            candidate = copy.deepcopy(payload)
            mutate(candidate)
            with self.assertRaises(ValueError):
                files.parse_runtime_file(json.dumps(candidate).encode(), "test")
        self.manager.store.async_save.assert_not_awaited()

    async def test_importing_legacy_samples_preserves_manual_estimate(self):
        self.manager.runtime.manual_seconds = {"Boden": 3000}
        samples = test_runtime_file.RuntimeImportTests().parse(test_runtime_file.RuntimeImportTests().payload())
        await self.manager.async_import_runtime_samples(samples)
        self.assertEqual(self.manager.runtime.manual_seconds, {"Boden": 3000})
        self.assertEqual(self.manager.runtime.estimate("Boden")["sample_count"], 2)
