"""Completion-driven charging, reminders and push with actual manager logic."""

import types
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch
import test_manager
import test_protocol

module = test_manager.manager_module


class CompletionManagerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_manager.ManagerTests.asyncSetUp
    service = test_manager.ManagerTests.service
    poll_at = test_manager.ManagerTests.poll_at

    async def finish(self, battery=61, park=False):
        self.manager.charge_target = 80
        await self.poll_at(0, 0, 90, 0, module.Program("Standard"))
        await self.poll_at(5, 5, 90, 1, module.Program("Standard"))
        if park:
            with patch.object(module, "_now", return_value=self.manager.cleaning_started_at + timedelta(minutes=11)):
                await self.manager.async_request_park()
        await self.poll_at(3000, 13, battery, 2)
        return await self.poll_at(3100, 14, battery, 1)

    async def test_manual_park_sets_reminder_and_timer_without_training(self):
        now = await self.finish(61, park=True)
        self.assertEqual(self.manager.cooldown.deadline, now.timestamp() + 7200)
        self.assertTrue(self.manager.filter_cleaning_required)
        self.assertEqual(self.manager.runtime.history, {})
        await self.poll_at(3200, 14, 60, 1)
        self.assertEqual(self.manager.cooldown.deadline, now.timestamp() + 7200)

    async def test_missing_end_battery_uses_last_known_and_runs_timer_offline(self):
        self.manager.battery = 61
        self.manager.charge_target = 80
        await self.poll_at(0, 13, position=2)
        now = await self.poll_at(100, 14, position=1)
        self.assertEqual(self.manager.cooldown.deadline, now.timestamp() + 7200)
        self.hass.async_add_executor_job.side_effect = OSError("off")
        with patch.object(module, "_now", return_value=now + timedelta(hours=2)):
            await self.manager.async_poll()
            await self.manager._check_cooldown()
        self.assertEqual(self.plug, "on")
        self.assertTrue(self.manager.filter_cleaning_required)  # First failure is not off confirmation.
        self.hass.services.async_call.assert_awaited_once()

    async def test_new_run_cancels_timer_and_next_completion_restarts_full_delay(self):
        await self.finish()
        await self.poll_at(4000, 12, 61, 1)
        self.assertIsNone(self.manager.cooldown.deadline)
        await self.poll_at(6000, 13, 41, 2)
        self.assertIsNone(self.manager.cooldown.deadline)
        now = await self.poll_at(6100, 14, 40, 1)
        self.assertEqual(self.manager.cooldown.deadline, now.timestamp() + 7200)

    async def test_basket_removal_clears_reminder_but_stale_missing_code_does_not(self):
        self.manager.fault_code = 2
        await self.finish()
        self.assertTrue(self.manager.filter_cleaning_required)
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult({"165": 0, "154": 0, "107": 2})
        await self.manager.async_poll()
        self.assertFalse(self.manager.filter_cleaning_required)
        self.assertTrue(self.manager.filter_basket_missing)

    async def test_offline_idle_clears_reminder_after_five_minutes_and_reconnect_clears_inference(self):
        await self.finish()
        now = await self.poll_at(3200, 0, 61, 0)
        self.hass.async_add_executor_job.side_effect = OSError("off")
        self.manager._rediscover = AsyncMock()
        for seconds, expected in ((0, False), (299, False), (300, True)):
            with patch.object(module, "_now", return_value=now + timedelta(seconds=seconds)):
                await self.manager.async_poll()
                self.assertEqual(self.manager.inferred_off, expected)
                self.assertEqual(self.manager.filter_cleaning_required, not expected)
        self.hass.async_add_executor_job.side_effect = None
        await self.poll_at(3600, 0, 61, 0)
        self.assertFalse(self.manager.inferred_off)

    async def test_underwater_or_paused_offline_is_not_inferred_off(self):
        for state in ("cleaning", "diving", "emerge", "paused", "clean_wait", "return_trip"):
            self.manager.robot_status = state
            self.manager.online = False
            self.manager._offline_since = module._now() - timedelta(hours=3)
            self.assertFalse(self.manager.inferred_off)

    async def test_push_toggle_default_off_and_one_notification_per_completion_across_restore(self):
        self.manager.entry.options["notify_service"] = "mobile_app_test_phone"
        self.hass.services.has_service = lambda domain, service: True
        self.hass.services.async_call = AsyncMock()
        await self.finish()
        self.hass.services.async_call.assert_not_awaited()
        await self.manager.async_set_completion_notifications(True)
        await self.poll_at(4000, 5, 61, 1)
        await self.poll_at(6000, 13, 40, 2)
        await self.poll_at(6100, 14, 40, 1)
        self.hass.services.async_call.assert_awaited_once()
        self.assertEqual(self.hass.services.async_call.call_args.args[:2], ("notify", "mobile_app_test_phone"))
        saved = self.manager._stored_data()
        self.manager.store.async_load.return_value = saved
        await self.manager.async_initialize()
        await self.poll_at(6200, 14, 40, 1)
        self.hass.services.async_call.assert_awaited_once()
        self.assertTrue(self.manager.filter_cleaning_required)
        self.assertTrue(self.manager.completion_notifications)

    async def test_push_failure_does_not_prevent_planning_or_repeat(self):
        self.manager.entry.options["notify_service"] = "mobile_app_test_phone"
        self.manager.completion_notifications = True
        self.hass.services.async_call.side_effect = RuntimeError("notification service unavailable")
        with self.assertLogs(module.__name__, level="WARNING"):
            await self.finish()
        self.assertEqual(self.manager.cooldown.state, "cooling")
        self.assertTrue(self.manager.online)
        await self.poll_at(3200, 14, 61, 1)
        self.hass.services.async_call.assert_awaited_once()

    async def test_push_requires_configured_target(self):
        with self.assertRaises(RuntimeError):
            await self.manager.async_set_completion_notifications(True)
        self.assertFalse(self.manager.completion_notifications)

    async def test_notification_switch_save_failure_preserves_previous_setting(self):
        self.manager.entry.options["notify_service"] = "mobile_app_test_phone"
        self.hass.services.has_service = lambda *args: True
        self.manager.store.async_save.side_effect = OSError("disk unavailable")
        with self.assertRaises(OSError):
            await self.manager.async_set_completion_notifications(True)
        self.assertFalse(self.manager.completion_notifications)
