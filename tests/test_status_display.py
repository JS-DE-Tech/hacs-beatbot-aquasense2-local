"""Status presentation must not control completion, charging or runtime learning."""

import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

import test_manager
import test_protocol
import test_runtime_ui

module = test_manager.manager_module
sensor_module = test_runtime_ui.sensor_module

EXPECTED = [
    "Bereit", "Laderückkehr – unbestätigt", "Lädt", "Vollständig geladen",
    "Pausiert", "Reinigt", "Ruhemodus", "Rückkehr läuft", "Reinigung abgeschlossen",
    "Manuelle Steuerung", "Wartet auf Reinigung", "WLAN-Verbindung wird hergestellt",
    "Taucht ab", "Aufgetaucht – fährt zum Rand", "Geparkt am Beckenrand",
    "Dockstatus – unbestätigt",
]


class StatusDisplayTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_manager.ManagerTests.asyncSetUp
    service = test_manager.ManagerTests.service
    poll_at = test_manager.ManagerTests.poll_at

    async def test_all_codes_and_entity_values_without_synthetic_completion(self):
        for code, label in enumerate(EXPECTED):
            with self.subTest(code=code):
                await self.asyncSetUp()
                await self.poll_at(0, code, 61, 0)
                sensor = sensor_module.BeatbotCleaningState(self.manager)
                self.assertEqual(sensor.native_value, label)
                self.assertTrue(sensor.available)
                self.assertEqual(sensor.extra_state_attributes["status_mapping_verified"],
                                 code in {0, 2, 5, 6, 12, 13, 14})
                self.assertFalse(self.manager.filter_cleaning_required)
                self.assertIsNone(self.manager.last_completion_at)
                self.assertEqual(self.manager.cooldown.state, "idle")
                self.assertEqual(self.manager.runtime.history, {})
                self.hass.services.async_call.assert_not_awaited()

    async def test_every_label_survives_restart_as_stale_without_side_effects(self):
        for code, label in enumerate(EXPECTED):
            with self.subTest(code=code):
                await self.asyncSetUp()
                now = await self.poll_at(0, code, 61, 0)
                saved = self.manager._stored_data()
                restored = module.BeatbotManager(self.hass, self.manager.entry)
                restored.store.async_load.return_value = saved
                with patch.object(module, "_now", return_value=now):
                    await restored.async_initialize()
                self.assertEqual(restored.cleaning_state, label)
                self.assertFalse(restored.online)
                self.assertFalse(restored.inferred_off)
                self.assertEqual(restored.cooldown.dump(), saved["cooldown"])
                self.assertEqual(restored.runtime.history, {})
                self.hass.services.async_call.assert_not_awaited()

    async def test_old_saved_labels_upgrade_using_raw_status(self):
        cases = [("sleep", "Bereit", "Ruhemodus"),
                 ("diving", "Reinigt", "Reinigt"),
                 ("dock", "Fertig", EXPECTED[15]),
                 ("auto_dock", "Geparkt", EXPECTED[14]),
                 ("standby", "Schwebend", EXPECTED[13]),
                 ("standby", "Parkt", EXPECTED[14])]
        for status, old, expected in cases:
            with self.subTest(status=status, old=old):
                restored = module.BeatbotManager(self.hass, self.manager.entry)
                restored.store.async_load.return_value = {"robot_status": status, "cleaning_state": old}
                await restored.async_initialize()
                self.assertEqual(restored.cleaning_state, expected)
                self.assertFalse(restored.online)
                self.assertIsNone(restored.last_completion_at)

    async def test_sleep_overrides_park_display_then_offline_inference_and_reconnect(self):
        await self.poll_at(0, 14, 61, 1)
        now = await self.poll_at(10, 6, 61, 0)
        sensor = sensor_module.BeatbotCleaningState(self.manager)
        self.assertEqual(sensor.native_value, "Ruhemodus")
        self.hass.async_add_executor_job.side_effect = OSError("offline")
        for seconds, expected in ((0, "Ruhemodus"), (299, "Ruhemodus"), (300, "Ausgeschaltet")):
            with patch.object(module, "_now", return_value=now + timedelta(seconds=seconds)):
                await self.manager.async_poll()
                self.assertEqual(sensor.native_value, expected)
                self.assertEqual(self.manager.robot_status, "sleep")
        self.hass.async_add_executor_job.side_effect = None
        await self.poll_at(400, 0, 61, 0)
        self.assertEqual(sensor.native_value, "Bereit")
        self.assertFalse(sensor.extra_state_attributes["inferred_off"])

    async def test_active_statuses_remain_visible_underwater(self):
        for code in (4, 5, 7, 10, 12, 13):
            with self.subTest(code=code):
                await self.asyncSetUp()
                now = await self.poll_at(0, code, 61, 1)
                self.manager.online = False
                self.manager._offline_since = now
                with patch.object(module, "_now", return_value=now + timedelta(hours=3)):
                    self.assertEqual(sensor_module.BeatbotCleaningState(self.manager).native_value, EXPECTED[code])

    async def test_surface_standby_preserves_display_even_without_training(self):
        await self.poll_at(0, 13, 61, 2)
        self.assertIsNone(self.manager.runtime.active)
        await self.poll_at(5, 0, 61, 1)
        self.assertEqual(self.manager.cleaning_state, EXPECTED[13])
        await self.poll_at(10, 14, 61, 1)
        self.assertEqual(self.manager.cleaning_state, EXPECTED[14])
        completed = self.manager.last_completion_at
        await self.poll_at(15, 0, 61, 1)
        self.assertEqual(self.manager.cleaning_state, EXPECTED[14])
        await self.poll_at(20, 0, 61, 0)
        self.assertEqual(self.manager.cleaning_state, "Bereit")
        self.assertEqual(self.manager.last_completion_at, completed)

    async def test_partial_or_unknown_status_does_not_fabricate_ready(self):
        await self.poll_at(0, 6, 61, 0)
        for dps in ({"6": 60}, {"165": 99}, {"165": False}):
            self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult(dps)
            await self.manager.async_poll()
            self.assertEqual(self.manager.cleaning_state, "Ruhemodus")
            self.assertEqual(self.manager.robot_status, "sleep")

    async def test_diving_exact_90_second_boundary_and_repeated_reports(self):
        started = await self.poll_at(0, 12, 90, 1)
        for seconds, expected in ((30, "Taucht ab"), (89, "Taucht ab"), (90, "Reinigt"), (180, "Reinigt")):
            await self.poll_at(seconds, 12, 90, 1)
            self.assertEqual(self.manager.cleaning_state, expected)
            self.assertEqual(self.manager.diving_started_at, started)
            self.assertEqual(self.manager.robot_status, "diving")
        self.assertIsNone(self.manager.last_completion_at)
        self.assertFalse(self.manager.filter_cleaning_required)
        self.assertEqual(self.manager.runtime.history, {})
        self.assertIsNone(self.manager.cooldown.deadline)
        self.hass.services.async_call.assert_not_awaited()

    async def test_diving_offline_callback_updates_sensor_without_poll_or_commands(self):
        started = await self.poll_at(0, 12, 90, 1)
        self.manager.online = False
        notified = Mock()
        self.manager.subscribe(notified)
        self.manager.store.async_delay_save = Mock()
        before = self.hass.async_add_executor_job.await_count
        with patch.object(module, "_now", return_value=started + timedelta(seconds=90)):
            self.manager._on_diving_display_due()
            self.assertEqual(sensor_module.BeatbotCleaningState(self.manager).native_value, "Reinigt")
            self.assertFalse(self.manager.inferred_off)
        notified.assert_called_once()
        self.manager.store.async_delay_save.assert_called_once()
        self.assertEqual(self.hass.async_add_executor_job.await_count, before)
        self.assertEqual(self.manager.robot_status, "diving")
        self.hass.services.async_call.assert_not_awaited()

    async def test_diving_restart_preserves_remaining_time_and_expired_window(self):
        started = await self.poll_at(0, 12, 90, 1)
        saved = self.manager._stored_data()
        for seconds, expected in ((40, "Taucht ab"), (90, "Reinigt"), (3600, "Reinigt")):
            restored = module.BeatbotManager(self.hass, self.manager.entry)
            restored.store.async_load.return_value = saved
            with patch.object(module, "_now", return_value=started + timedelta(seconds=seconds)):
                await restored.async_initialize()
            self.assertEqual(restored.cleaning_state, expected)
            self.assertEqual(restored.diving_started_at, started)
            self.assertFalse(restored.online)

    async def test_diving_upgrade_without_valid_timestamp_does_not_invent_window(self):
        for stamp in (None, "invalid", "2999-01-01T00:00:00+00:00"):
            restored = module.BeatbotManager(self.hass, self.manager.entry)
            restored.store.async_load.return_value = {"robot_status": "diving", "cleaning_state": "Reinigt – taucht ab", "diving_started_at": stamp}
            await restored.async_initialize()
            self.assertEqual(restored.cleaning_state, "Reinigt")
            self.assertIsNone(restored.diving_started_at)

    async def test_restore_transient_standby_does_not_restart_expired_diving_window(self):
        started = await self.poll_at(0, 12, 90, 1)
        await self.poll_at(100, 0, 90, 1)
        saved = self.manager._stored_data()
        restored = module.BeatbotManager(self.hass, self.manager.entry)
        restored.store.async_load.return_value = saved
        with patch.object(module, "_now", return_value=started + timedelta(seconds=110)):
            await restored.async_initialize()
        self.manager = restored
        await self.poll_at(120, 12, 90, 1)
        self.assertEqual(self.manager.diving_started_at, started)
        self.assertEqual(self.manager.cleaning_state, "Reinigt")

    async def test_new_state_overrides_diving_immediately_and_new_dive_starts_new_window(self):
        for code in (0, 2, 4, 5, 6, 13, 14):
            await self.asyncSetUp()
            await self.poll_at(0, 12, 90, 1)
            await self.poll_at(10, code, 90, 0)
            self.assertIsNone(self.manager.diving_started_at)
            self.assertEqual(self.manager.cleaning_state, EXPECTED[code])
            now = await self.poll_at(20, 12, 90, 1)
            self.assertEqual(self.manager.diving_started_at, now)
            self.assertEqual(self.manager.cleaning_state, "Taucht ab")

    async def test_transient_standby_and_missing_status_do_not_restart_diving_clock(self):
        started = await self.poll_at(0, 12, 90, 1)
        await self.poll_at(30, 0, 90, 1)
        self.assertEqual(self.manager.cleaning_state, "Taucht ab")
        await self.poll_at(60, None, 90, 1)
        await self.poll_at(90, 12, 90, 1)
        self.assertEqual(self.manager.diving_started_at, started)
        self.assertEqual(self.manager.cleaning_state, "Reinigt")


if __name__ == "__main__":
    unittest.main()
