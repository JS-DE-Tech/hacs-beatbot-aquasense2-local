"""Charging guard regressions using the real manager and transport with HA/Tuya fakes."""

import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_manager
from test_manager import manager_module
from test_protocol import FakeDevice, protocol


FIRST_PROBE = 135 * 60  # Two hours and fifteen minutes after Shelly-off.


class ChargeGuardTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_manager.ManagerTests.asyncSetUp
    service = test_manager.ManagerTests.service

    def at(self, seconds):
        return datetime(2026, 10, 25, tzinfo=timezone.utc) + timedelta(seconds=seconds)

    async def poll(self, seconds, status=0, battery=80, *, offline=False):
        FakeDevice.dps = {"165": status, "6": battery, "154": 0,
                          "132": protocol.encode_mode("Standard")}
        self.hass.async_add_executor_job.side_effect = lambda fn, *args: fn(*args)
        with patch.object(manager_module, "_now", return_value=self.at(seconds)):
            if offline:
                with patch.object(FakeDevice, "status", side_effect=OSError("offline")):
                    await self.manager.async_poll()
            else:
                await self.manager.async_poll()

    async def charged(self):
        self.plug = "on"
        self.manager.charge_target = 80
        FakeDevice.writes = []
        await self.manager.async_select_mode("Boden")
        await self.poll(0, status=2)
        self.assertEqual(self.plug, "off")
        self.assertEqual(FakeDevice.writes, [])
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")

    async def restore(self):
        saved = self.manager._stored_data()
        self.manager = manager_module.BeatbotManager(self.hass, self.manager.entry)
        self.manager.store.async_load.return_value = saved
        await self.manager.async_initialize()

    async def test_charge_cutoff_silence_power_cycle_then_latest_selection(self):
        await self.charged()
        self.hass.async_add_executor_job.reset_mock()
        await self.manager.async_select_mode("Bereich")
        await self.manager.async_select_program_option("floor", "2")
        await self.manager.async_select_mode("ECO")
        for seconds in (1, 30, 300, 600, 3600, 7200, FIRST_PROBE - 1):
            await self.poll(seconds)
        self.hass.async_add_executor_job.assert_not_awaited()
        self.assertTrue(self.manager.online)  # Silence alone is not an outage.
        await self.poll(FIRST_PROBE, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        await self.poll(FIRST_PROBE + 300, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_return")
        await self.poll(FIRST_PROBE + 600)
        self.assertFalse(self.manager.charge_guard.blocked)
        self.assertTrue(self.manager.mode_pending)
        self.assertEqual(FakeDevice.writes, [])  # Recovery probe is read-only.
        await self.poll(FIRST_PROBE + 630)
        self.assertEqual(FakeDevice.writes, [("132", protocol.encode_mode("ECO"))])
        self.assertFalse(self.manager.mode_pending)

    async def test_charging_still_monitors_battery_but_never_sends_commands(self):
        self.plug = "on"
        FakeDevice.writes = []
        await self.manager.async_select_mode("Boden")
        await self.poll(0, status=2, battery=70)
        self.assertEqual(self.manager.charge_guard.phase, "charging")
        self.assertEqual(self.manager.store.async_save.call_args.args[0]["charge_guard"]["phase"], "charging")
        await self.poll(5, status=0, battery=71)
        self.assertEqual(self.manager.battery, 71)
        self.assertTrue(self.manager.mode_pending)
        self.assertEqual(FakeDevice.writes, [])
        self.manager.robot_status = "cleaning"
        self.manager.last_mode = "Standard"
        self.manager.cleaning_started_at = self.at(-1000)
        self.assertFalse(self.manager.can_park)
        with self.assertRaises(RuntimeError):
            await self.manager.async_request_park()

    async def test_single_failed_probe_and_elapsed_silence_do_not_unlock(self):
        await self.charged()
        await self.poll(FIRST_PROBE)
        self.assertTrue(self.manager.charge_guard.blocked)
        await self.poll(FIRST_PROBE + 300, offline=True)
        await self.poll(FIRST_PROBE + 600)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        await self.poll(FIRST_PROBE + 900, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        self.assertEqual(FakeDevice.writes, [])

    async def test_reload_keeps_pause_and_pending_options(self):
        await self.charged()
        await self.manager.async_select_mode("Bereich")
        await self.manager.async_select_program_option("floor", "2")
        await self.restore()
        self.assertEqual(self.manager.charge_guard.next_poll_at, self.at(FIRST_PROBE))
        self.assertEqual(self.manager.floor_count, 2)
        self.assertTrue(self.manager.mode_pending)
        self.hass.async_add_executor_job.reset_mock()
        await self.poll(FIRST_PROBE - 1)
        self.hass.async_add_executor_job.assert_not_awaited()

    async def test_reload_does_not_count_downtime_as_second_failed_probe(self):
        await self.charged()
        await self.poll(FIRST_PROBE, offline=True)
        await self.restore()
        await self.poll(FIRST_PROBE + 1400, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        await self.poll(FIRST_PROBE + 1700, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_return")
        await self.restore()
        await self.poll(FIRST_PROBE + 2000)
        self.assertFalse(self.manager.charge_guard.blocked)
        self.assertEqual(FakeDevice.writes, [])

    async def test_shelly_on_resumes_battery_queries_without_unlocking(self):
        await self.charged()
        with patch.object(manager_module, "_now", return_value=self.at(100)):
            await self.manager.async_set_charging(True)
        await self.poll(105, status=2, battery=50)
        self.assertEqual(self.manager.battery, 50)
        self.assertTrue(self.manager.charge_guard.blocked)
        with patch.object(manager_module, "_now", return_value=self.at(110)):
            await self.manager.async_set_charging(False)
        self.assertEqual(self.manager.charge_guard.next_poll_at, self.at(FIRST_PROBE + 110))
        self.assertEqual(FakeDevice.writes, [])

    async def test_repeated_off_or_unknown_switch_does_not_extend_pause_or_unlock(self):
        await self.charged()
        for seconds, state in ((100, "off"), (200, "unavailable"), (300, "off")):
            self.plug = state
            event = types.SimpleNamespace(data={"new_state": types.SimpleNamespace(state=state)})
            with patch.object(manager_module, "_now", return_value=self.at(seconds)):
                self.manager._on_switch_changed(event)
            self.assertEqual(self.manager.charge_guard.next_poll_at, self.at(FIRST_PROBE))
        self.plug = "unavailable"
        await self.poll(FIRST_PROBE, offline=True)
        await self.poll(FIRST_PROBE + 300, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")

    async def test_charge_and_switch_off_during_same_executor_call_still_lock(self):
        self.plug = "on"
        FakeDevice.writes = []
        await self.manager.async_select_mode("Boden")

        def response(device):
            self.plug = "off"
            return {"dps": {"165": 2, "6": 79}}

        with patch.object(FakeDevice, "status", response):
            await self.poll(0, status=2)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        self.assertEqual(FakeDevice.writes, [])

    async def test_loading_old_storage_does_not_invent_charge_cycle(self):
        self.manager.store.async_load.return_value = {"robot_status": "charging"}
        await self.manager.async_initialize()
        self.assertFalse(self.manager.charge_guard.blocked)

    async def test_already_selected_program_is_confirmed_without_rewriting(self):
        FakeDevice.writes = []
        await self.manager.async_select_mode("Standard")
        await self.poll(0)
        self.assertFalse(self.manager.mode_pending)
        self.assertEqual(FakeDevice.writes, [])

    async def test_charging_return_does_not_release_lock(self):
        await self.charged()
        await self.poll(FIRST_PROBE, offline=True)
        await self.poll(FIRST_PROBE + 300, offline=True)
        await self.poll(FIRST_PROBE + 600, status=2)
        self.assertTrue(self.manager.charge_guard.blocked)
        self.assertEqual(FakeDevice.writes, [])

    async def test_active_underwater_outage_does_not_count_as_power_off(self):
        await self.charged()
        await self.poll(FIRST_PROBE, status=5)
        await self.poll(FIRST_PROBE + 300, offline=True)
        await self.poll(FIRST_PROBE + 600, offline=True)
        self.assertEqual(self.manager.charge_guard.phase, "waiting_off")
        self.assertEqual(FakeDevice.writes, [])


if __name__ == "__main__":
    unittest.main()
