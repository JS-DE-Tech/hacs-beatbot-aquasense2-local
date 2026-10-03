"""Manager service wiring with small HA fakes; not a HA runtime integration test."""

import importlib
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import test_protocol  # Transport and integration package bootstrap.


class Store:
    def __init__(self, *args):
        self.async_save = AsyncMock()
        self.async_load = AsyncMock(return_value={})

    def async_delay_save(self, *args):
        pass


stubs = {}
for name, fields in {
    "homeassistant": {},
    "homeassistant.config_entries": {"ConfigEntry": object},
    "homeassistant.const": {"EVENT_HOMEASSISTANT_STOP": "homeassistant_stop"},
    "homeassistant.core": {"HomeAssistant": object, "callback": lambda f: f},
    "homeassistant.exceptions": {"HomeAssistantError": RuntimeError},
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {"async_track_state_change_event": lambda *args: lambda: None},
    "homeassistant.helpers.storage": {"Store": Store},
}.items():
    module = types.ModuleType(name)
    module.__dict__.update(fields)
    stubs[name] = module
with patch.dict("sys.modules", stubs):
    manager_module = importlib.import_module("custom_components.beatbot_aquasense2_local.manager")


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plug = "off"
        self.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(
                get=lambda entity_id: types.SimpleNamespace(state=self.plug),
                is_state=lambda entity_id, state: self.plug == state),
            services=types.SimpleNamespace(async_call=AsyncMock(side_effect=self.service)),
            async_add_executor_job=AsyncMock(),
        )
        entry = types.SimpleNamespace(entry_id="test", title="Robot", data={
            "device_id": "test", "host": "192.168.1.2", "local_key": "0123456789abcdef"},
            options={"charger_switch": "switch.test_plug"})
        self.manager = manager_module.BeatbotManager(self.hass, entry)

    async def service(self, domain, service, data, blocking):
        self.assertEqual(domain, "switch")
        self.assertEqual(data, {"entity_id": "switch.test_plug"})
        old = self.plug
        self.plug = "on" if service == "turn_on" else "off"
        event = types.SimpleNamespace(data={"old_state": types.SimpleNamespace(state=old),
                                           "new_state": types.SimpleNamespace(state=self.plug)})
        self.manager._on_switch_changed(event)

    def arm(self):
        self.manager.cooldown.state = "cooling"
        self.manager.cooldown.deadline = datetime.now(timezone.utc).timestamp() - 1

    async def test_automatic_start_once_then_target_off(self):
        self.arm()
        await self.manager._check_cooldown()
        self.assertEqual(self.plug, "on")
        await self.manager._check_cooldown()
        self.assertEqual(self.hass.services.async_call.await_count, 1)
        self.manager.charge_target = 80
        await self.manager._check_charger(datetime.now(timezone.utc) + timedelta(seconds=1), 80)
        self.assertEqual(self.plug, "off")
        self.assertEqual(self.manager.cooldown.state, "complete")

    async def test_manual_off_cancels_pending_timer_even_if_already_off(self):
        self.arm()
        await self.manager.async_set_charging(False)
        await self.manager._check_cooldown()
        self.assertEqual(self.plug, "off")
        self.assertEqual(self.hass.services.async_call.await_count, 1)
        self.assertEqual(self.manager.cooldown.state, "manual")

    async def test_manual_on_uses_assigned_entity_and_target_still_applies(self):
        await self.manager.async_set_charging(True)
        self.assertEqual(self.plug, "on")
        await self.manager._check_charger(datetime.now(timezone.utc) + timedelta(seconds=1), 100)
        self.assertEqual(self.plug, "off")

    async def test_unavailable_switch_never_gets_auto_on(self):
        self.arm()
        self.plug = "unavailable"
        await self.manager._check_cooldown()
        self.hass.services.async_call.assert_not_awaited()

    async def test_start_exception_is_rate_limited(self):
        self.arm()
        self.hass.services.async_call.side_effect = RuntimeError("offline")
        await self.manager._check_cooldown()
        await self.manager._check_cooldown()
        self.assertEqual(self.hass.services.async_call.await_count, 1)
        self.assertEqual(self.manager.cooldown.state, "cooling")

    async def test_poll_feeds_completion_sleep_and_fresh_battery(self):
        for status, battery in [(5, 80), (8, 60), (6, 60)]:
            self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult({"165": status, "6": battery})
            await self.manager.async_poll()
        self.assertEqual(self.manager.cooldown.state, "cooling")
        self.assertGreater(self.manager.cooldown.deadline, datetime.now(timezone.utc).timestamp() + 7190)
        self.hass.services.async_call.assert_not_awaited()

    async def test_floor_only_area_disables_parking(self):
        self.manager.selected_mode = "Bereich"
        self.manager.last_program_key = "Bereich:floor=2:wall=0"
        self.manager.robot_status = "cleaning"
        self.assertFalse(self.manager.can_park)

    async def test_live_charging_dp_updates_display_without_cleaning_completion(self):
        for previous in ("Bereit", "Geparkt", "Fertig"):
            self.manager.cleaning_state = previous
            await self.poll_at(0, 2, 97, 0)
            self.assertEqual(self.manager.robot_status, "charging")
            self.assertEqual(self.manager.cleaning_state, "Lädt")
            self.assertFalse(self.manager.inferred_off)
            self.assertFalse(self.manager.filter_cleaning_required)
            self.assertIsNone(self.manager.last_completion_at)
            self.assertEqual(self.manager.runtime.history, {})
            self.assertEqual(self.manager.cooldown.state, "idle")
        self.hass.services.async_call.assert_not_awaited()

    async def test_charging_display_survives_restore_until_new_status(self):
        await self.poll_at(0, 2, 97, 0)
        saved = self.manager._stored_data()
        restored = manager_module.BeatbotManager(self.hass, self.manager.entry)
        restored.store.async_load.return_value = saved
        await restored.async_initialize()
        self.assertEqual(restored.cleaning_state, "Lädt")
        self.assertFalse(restored.online)
        self.manager = restored
        await self.poll_at(10, 0, 97, 0)
        self.assertEqual(self.manager.cleaning_state, "Bereit")

    def queue_park(self, state="queued"):
        self.manager.selected_mode = self.manager.last_mode = "Standard"
        self.manager.park_pending = True
        self.manager.park_state = state
        self.manager.park_requested_at = datetime(2026, 10, 2, tzinfo=timezone.utc)
        self.manager.last_park_send_at = self.manager.park_requested_at

    async def test_fresh_dry_ready_finishes_every_pending_park_state(self):
        for state in ("queued", "sent", "waiting_for_feedback", "waiting_for_surface", "accepted"):
            with self.subTest(state=state):
                self.queue_park(state)
                await self.poll_at(10, 0, 61, 0)
                self.assertFalse(self.manager.park_pending)
                self.assertEqual(self.manager.park_state, "completed")
                self.assertIsNone(self.manager.park_requested_at)
                self.assertIsNone(self.manager.last_park_send_at)
                self.assertEqual(self.manager.cleaning_state, "Bereit")
                self.assertFalse(self.manager.can_park)
        self.assertEqual(self.manager.runtime.history, {})
        self.hass.services.async_call.assert_not_awaited()

    async def test_ready_unlocks_mode_and_program_options_for_next_poll(self):
        self.queue_park()
        await self.poll_at(10, 0, 61, 0)
        await self.manager.async_select_mode("Standard")  # Same mode is a normal selection.
        await self.manager.async_select_program_option("floor", "2")
        await self.poll_at(15, 0, 61, 0)
        self.hass.async_add_executor_job.assert_awaited_with(
            self.manager.client.poll, False, manager_module.Program("Standard", 2, 1, "Max"))

    async def test_missing_or_invalid_position_cannot_finish_park(self):
        for position in (None, False, True, "0", 0.0, -1, 1, 2):
            with self.subTest(position=position):
                self.queue_park()
                self.manager.position = 0  # A previous dry position is not enough.
                await self.poll_at(10, 0, 61, position)
                self.assertTrue(self.manager.park_pending)

    async def test_missing_status_cannot_finish_park_using_saved_readiness(self):
        self.queue_park()
        self.manager.robot_status = "standby"
        self.manager.cleaning_state = "Bereit"
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult({"154": 0})
        with patch.object(manager_module, "_now", return_value=self.manager.park_requested_at + timedelta(seconds=10)):
            await self.manager.async_poll()
        self.assertTrue(self.manager.park_pending)

    async def test_active_or_sleep_status_does_not_finish_park_even_with_dry_position(self):
        for status in (4, 5, 6, 12, 13, 14):
            with self.subTest(status=status):
                self.queue_park()
                await self.poll_at(10, status, 61, 0)
                self.assertTrue(self.manager.park_pending)

    async def test_restored_ready_and_offline_do_not_clear_pending_park(self):
        self.queue_park()
        self.manager.robot_status = "standby"
        self.manager.cleaning_state = "Bereit"
        self.manager.store.async_load.return_value = self.manager._stored_data()
        now = self.manager.park_requested_at + timedelta(seconds=10)
        with patch.object(manager_module, "_now", return_value=now):
            await self.manager.async_initialize()
            self.assertTrue(self.manager.park_pending)
            self.hass.async_add_executor_job.side_effect = OSError("offline")
            await self.manager.async_poll()
        self.assertTrue(self.manager.park_pending)
        self.assertFalse(self.manager.online)

    async def test_partial_dry_and_ready_reports_must_not_be_combined(self):
        self.queue_park()
        await self.poll_at(10, 0, 61, None)
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult({"154": 0})
        with patch.object(manager_module, "_now", return_value=self.manager.park_requested_at + timedelta(seconds=15)):
            await self.manager.async_poll()
        self.assertTrue(self.manager.park_pending)
        await self.poll_at(20, 0, 61, 0)
        self.assertFalse(self.manager.park_pending)
        saved = self.manager._stored_data()
        await self.poll_at(25, 0, 61, 0)
        self.assertEqual(self.manager.park_state, "completed")
        self.assertFalse(saved["park_pending"])
        self.assertIsNone(saved["park_requested_at"])

    async def test_explicit_done_still_finishes_park_without_position(self):
        for status in (8, 15):
            with self.subTest(status=status):
                self.queue_park()
                await self.poll_at(10, status, 61)
                self.assertFalse(self.manager.park_pending)
                self.assertEqual(self.manager.park_state, "completed")

    async def test_park_delay_boundary_and_offline_surface_queue(self):
        self.manager.selected_mode = self.manager.last_mode = "Standard"
        started = await self.poll_at(0, 5, 90, 1)
        self.assertIsNone(self.manager.runtime.active)  # Timing does not require training.
        self.manager.online = False  # Underwater WLAN loss does not restart timing.
        with patch.object(manager_module, "_now", return_value=started + timedelta(seconds=599)):
            self.assertFalse(self.manager.can_park)
            with self.assertRaises(RuntimeError):
                await self.manager.async_request_park()
        with patch.object(manager_module, "_now", return_value=started + timedelta(seconds=600)):
            self.assertTrue(self.manager.can_park)
            await self.manager.async_request_park()
        self.assertTrue(self.manager.park_pending)
        self.assertEqual(self.manager.cleaning_started_at, started)
        self.assertEqual(self.manager.park_state, "queued")

    async def test_all_floor_only_variants_remain_blocked_after_delay(self):
        for program in (manager_module.Program("Boden"), manager_module.Program("ECO"),
                        manager_module.Program("Bereich", 1, 0), manager_module.Program("Bereich", 2, 0)):
            with self.subTest(program=program.key):
                self.manager.cleaning_started_at = None
                self.manager.selected_mode = self.manager.last_mode = program.mode
                started = await self.poll_at(0, 5, 90, 1, program)
                with patch.object(manager_module, "_now", return_value=started + timedelta(minutes=20)):
                    self.assertFalse(self.manager.can_park)
                    with self.assertRaises(RuntimeError):
                        await self.manager.async_request_park()

    async def test_wall_variants_can_park_after_delay(self):
        for program in (manager_module.Program("Standard"), manager_module.Program("MultiZone"),
                        manager_module.Program("Bereich", 0, 1), manager_module.Program("Bereich", 2, 2)):
            with self.subTest(program=program.key):
                self.manager.cleaning_started_at = None
                started = await self.poll_at(0, 5, 90, 1, program)
                with patch.object(manager_module, "_now", return_value=started + timedelta(minutes=10)):
                    self.assertTrue(self.manager.can_park)

    async def test_park_send_is_delayed_even_for_legacy_pending_request(self):
        self.queue_park()
        self.manager.cleaning_started_at = self.manager.park_requested_at
        await self.poll_at(599, 5, 90, 1)
        self.assertFalse(self.hass.async_add_executor_job.call_args.args[1])
        await self.poll_at(600, 5, 90, 1)
        self.assertTrue(self.hass.async_add_executor_job.call_args.args[1])
        self.manager.last_program_key = "Bereich:floor=1:wall=0"
        await self.poll_at(605, 5, 90, 1)
        self.assertFalse(self.hass.async_add_executor_job.call_args.args[1])

    async def test_polling_pause_and_surface_do_not_restart_parking_clock(self):
        self.manager.selected_mode = "Standard"
        started = await self.poll_at(0, 5, 90, 1)
        for seconds, status in ((5, 12), (100, 4), (200, 5), (400, 13), (450, 0)):
            await self.poll_at(seconds, status, 80, 1)
            self.assertEqual(self.manager.cleaning_started_at, started)

    async def test_dry_ready_clears_old_clock_and_new_run_waits_again(self):
        self.manager.selected_mode = "Standard"
        await self.poll_at(0, 5, 90, 1)
        await self.poll_at(700, 0, 80, 0)
        self.assertIsNone(self.manager.cleaning_started_at)
        restarted = await self.poll_at(800, 12, 80, 1)
        self.assertEqual(self.manager.cleaning_started_at, restarted)
        with patch.object(manager_module, "_now", return_value=restarted + timedelta(seconds=599)):
            self.assertFalse(self.manager.can_park)

    async def test_pending_restore_without_clock_waits_from_first_active_report(self):
        self.queue_park()
        self.manager.robot_status = "diving"
        saved = self.manager._stored_data()
        saved.pop("cleaning_started_at", None)  # Old integration storage.
        self.manager.store.async_load.return_value = saved
        with patch.object(manager_module, "_now", return_value=self.manager.park_requested_at + timedelta(seconds=100)):
            await self.manager.async_initialize()
        first = await self.poll_at(100, 12, 80, 1)
        self.assertEqual(self.manager.cleaning_started_at, first)
        self.assertFalse(self.hass.async_add_executor_job.call_args.args[1])
        await self.poll_at(700, 12, 80, 1)
        self.assertTrue(self.hass.async_add_executor_job.call_args.args[1])

    async def test_future_invalid_or_idle_restored_clock_is_rejected(self):
        for status, value in (("diving", "invalid"), ("diving", "2026-10-03T00:00:00+00:00"),
                              ("diving", "2026-10-02T00:00:00"),
                              ("standby", "2026-10-02T00:00:00+00:00")):
            with self.subTest(status=status, value=value):
                self.manager.store.async_load.return_value = {
                    "robot_status": status, "cleaning_started_at": value}
                with patch.object(manager_module, "_now", return_value=datetime(2026, 10, 2, 1, tzinfo=timezone.utc)):
                    await self.manager.async_initialize()
                self.assertIsNone(self.manager.cleaning_started_at)

    async def test_selection_does_not_relabel_active_run(self):
        program = manager_module.Program("Standard")
        self.manager.runtime.observe("standby", program, 0)
        self.manager.runtime.observe("cleaning", program, 5)
        await self.manager.async_select_mode("Boden")
        self.assertEqual(self.manager.runtime.active["key"], "Standard")

    async def poll_at(self, seconds, status, battery=None, position=None, program=None):
        now = datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(seconds=seconds)
        dps = {"165": status}
        if battery is not None:
            dps["6"] = battery
        if position is not None:
            dps["154"] = position
        if program is not None:
            dps.update(program.writes())
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult(dps)
        with patch.object(manager_module, "_now", return_value=now):
            await self.manager.async_poll()
        return now

    async def test_two_floor_runs_surface_edge_pickup_and_cooldown(self):
        p = manager_module.Program("Boden")
        # Full idle confirmation bridges a missing DP132 in the start poll.
        await self.poll_at(0, 0, 100, 0, p)
        await self.poll_at(5, 5, 100, 1)
        await self.poll_at(10, 12, position=1)
        await self.poll_at(4300, 13, 82, 2)
        self.assertEqual(self.manager.cleaning_state, "Aufgetaucht – fährt zum Rand")
        await self.poll_at(4560, 0, 81, 1)
        self.assertEqual(self.manager.cleaning_state, "Aufgetaucht – fährt zum Rand")
        await self.poll_at(4565, 14, 81, 1)
        self.assertEqual(self.manager.cleaning_state, "Geparkt am Beckenrand")
        self.assertEqual(self.manager.runtime.history, {"Boden": [4560]})
        await self.poll_at(5000, 0, 81, 0)
        self.assertEqual(self.manager.cleaning_state, "Bereit")
        await self.poll_at(9995, 0, 80, 0, p)
        await self.poll_at(10000, 5, 80, 1)
        await self.poll_at(12800, 13, 68, 2)
        await self.poll_at(13193, 14, 66, 1)
        self.assertEqual(self.manager.cooldown.state, "cooling")
        deadline = self.manager.cooldown.deadline
        await self.poll_at(13200, 14, 66, 1)
        self.assertEqual(self.manager.runtime.history["Boden"], [4560, 3193])
        self.assertEqual(self.manager.runtime.battery_history["Boden"], [19, 14])
        self.assertEqual(self.manager.runtime.estimate("Boden")["estimated_seconds"], 3876.5)
        await self.poll_at(14000, 0, 66, 0)
        self.assertEqual(self.manager.cleaning_state, "Bereit")
        self.assertEqual(self.manager.cooldown.deadline, deadline)
        now = await self.poll_at(14500, 6, 66, 0)
        self.assertEqual(self.manager.cooldown.deadline, deadline)
        self.hass.services.async_call.assert_not_awaited()
        saved = self.manager._stored_data()
        self.manager.store.async_load.return_value = saved
        await self.manager.async_initialize()
        self.assertEqual(self.manager.runtime.estimate("Boden")["sample_count"], 2)
        self.assertEqual(self.manager.runtime.battery_history["Boden"], [19, 14])
        self.assertEqual(self.manager.cooldown.deadline, deadline)

    async def test_missing_start_program_not_taken_from_saved_selection(self):
        self.manager.selected_mode = self.manager.last_mode = "Boden"
        self.manager.last_program_key = "Boden"
        await self.poll_at(0, 0, 100, 0)
        await self.poll_at(5, 5, 100, 1)
        await self.poll_at(3000, 13, 82, 2)
        await self.poll_at(3200, 14, 81, 1)
        self.assertEqual(self.manager.runtime.history, {})

    async def test_stale_confirmed_program_not_used_for_start(self):
        await self.poll_at(0, 0, 100, 0, manager_module.Program("Boden"))
        await self.poll_at(100, 0, 100, 0)
        await self.poll_at(105, 5, 100, 1)
        self.assertIsNone(self.manager.runtime.active)

    async def test_unknown_or_incomplete_start_program_not_fallback(self):
        p = manager_module.Program("Boden")
        await self.poll_at(0, 0, 100, 0, p)
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult({"165": 5, "132": "invalid"})
        with patch.object(manager_module, "_now", return_value=datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(seconds=5)):
            await self.manager.async_poll()
        self.assertIsNone(self.manager.runtime.active)

    async def test_battery_freshness_does_not_use_online_flag_alone(self):
        now = await self.poll_at(0, 0, 80)
        with patch.object(manager_module, "_now", return_value=now):
            self.assertFalse(self.manager.battery_stale)
        later = await self.poll_at(100, 0)
        self.assertTrue(self.manager.online)
        with patch.object(manager_module, "_now", return_value=later):
            self.assertTrue(self.manager.battery_stale)
        later = await self.poll_at(105, 0, 79)
        with patch.object(manager_module, "_now", return_value=later):
            self.assertFalse(self.manager.battery_stale)
            self.manager.online = False
            self.assertTrue(self.manager.battery_stale)

    async def test_manual_park_arms_cooldown_but_does_not_train(self):
        p = manager_module.Program("Boden")
        await self.poll_at(0, 0, 90, 0, p)
        await self.poll_at(5, 5, 90, 1, p)
        self.manager.runtime.cancel_training("parking_excluded")
        await self.poll_at(3000, 13, 50, 2)
        await self.poll_at(3200, 14, 49, 1)
        await self.poll_at(3300, 6, 49, 0)
        self.assertEqual(self.manager.runtime.history, {})
        self.assertEqual(self.manager.cooldown.state, "cooling")

    async def test_import_is_persisted_and_storage_error_rolls_back(self):
        import test_runtime_file
        samples = test_runtime_file.RuntimeImportTests().parse(test_runtime_file.RuntimeImportTests().payload())
        self.manager.store.async_save.side_effect = OSError("disk error")
        with self.assertRaises(OSError):
            await self.manager.async_import_runtime_samples(samples)
        self.assertEqual(self.manager.runtime.history, {})
        self.manager.store.async_save.side_effect = None
        self.assertEqual(await self.manager.async_import_runtime_samples(samples), 2)
        self.assertEqual(await self.manager.async_import_runtime_samples(samples), 0)
        self.assertEqual(self.manager.store.async_save.call_args.args[0]["runtime"]["history"], {"Boden": [4560.0, 3193.0]})

    async def test_import_rejects_active_or_stopping_robot(self):
        self.manager._stopping = True
        with self.assertRaises(RuntimeError):
            await self.manager.async_import_runtime_samples([])
        self.manager._stopping = False
        self.manager.runtime.observe("cleaning", manager_module.Program("Boden"), 5)
        with self.assertRaises(RuntimeError):
            await self.manager.async_import_runtime_samples([])

    async def fault_poll(self, seconds, value, *, include=True):
        dps = {"165": 0}
        if include:
            dps["107"] = value
        now = datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(seconds=seconds)
        self.hass.async_add_executor_job.return_value = test_protocol.protocol.PollResult(dps)
        with patch.object(manager_module, "_now", return_value=now):
            await self.manager.async_poll()
        return now

    async def test_filter_missing_to_clear_without_control_or_training(self):
        now = await self.fault_poll(0, 2)
        self.assertTrue(self.manager.filter_basket_missing)
        with patch.object(manager_module, "_now", return_value=now):
            self.assertFalse(self.manager.fault_stale)
        await self.fault_poll(5, 0)
        self.assertFalse(self.manager.filter_basket_missing)
        self.assertEqual(self.manager.cooldown.state, "idle")
        self.assertEqual(self.manager.runtime.history, {})
        self.hass.services.async_call.assert_not_awaited()

    async def test_filter_missing_dp_does_not_clear_or_refresh(self):
        first = await self.fault_poll(0, 2)
        later = await self.fault_poll(100, None, include=False)
        self.assertEqual(self.manager.fault_seen, first)
        self.assertTrue(self.manager.filter_basket_missing)
        with patch.object(manager_module, "_now", return_value=later):
            self.assertTrue(self.manager.fault_stale)

    async def test_filter_invalid_and_unknown_codes_not_clear(self):
        for value in (None, True, "0", -1, 3):
            with self.subTest(value=value):
                await self.fault_poll(0, 2)
                await self.fault_poll(5, value)
                self.assertIsNone(self.manager.filter_basket_missing)

    async def test_filter_state_persists_but_restore_alone_is_not_fresh(self):
        first = await self.fault_poll(0, 2)
        saved = self.manager._stored_data()
        self.manager.store.async_load.return_value = saved
        self.manager.online = False
        await self.manager.async_initialize()
        self.assertEqual(self.manager.fault_code, 2)
        self.assertEqual(self.manager.fault_seen, first)
        self.assertTrue(self.manager.filter_basket_missing)
        self.assertTrue(self.manager.fault_stale)

    async def test_filter_network_failure_retains_last_code_not_health(self):
        await self.fault_poll(0, 0)
        self.hass.async_add_executor_job.side_effect = OSError("offline")
        await self.manager.async_poll()
        self.assertFalse(self.manager.filter_basket_missing)
        self.assertTrue(self.manager.fault_stale)
