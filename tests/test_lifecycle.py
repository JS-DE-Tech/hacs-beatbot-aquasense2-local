"""Lifecycle contract tests with HA fakes and real asyncio/executor tasks."""

import asyncio
import importlib.util
import importlib.machinery
import threading
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_manager
import test_history_view  # Load the actual route with explicit external HTTP fakes.
from test_protocol import protocol
from test_protocol import PACKAGE

manager_module = test_manager.manager_module


def load_setup_module():
    """Load the actual entry hooks with only the external HA imports stubbed."""
    stubs = dict(test_manager.stubs)
    const = types.ModuleType("homeassistant.const")
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    const.Platform = types.SimpleNamespace(**{n: n.lower() for n in (
        "SENSOR", "BINARY_SENSOR", "SELECT", "BUTTON", "SWITCH"
    )})
    stubs[const.__name__] = const
    http = types.ModuleType("homeassistant.components.http")
    http.StaticPathConfig = Mock()
    stubs[http.__name__] = http
    stubs["custom_components.beatbot_aquasense2_local.history_view"] = test_history_view.view_module
    name = "custom_components.beatbot_aquasense2_local.entry_hooks_test"
    spec = importlib.util.spec_from_loader(
        name, importlib.machinery.SourceFileLoader(name, str(PACKAGE / "__init__.py")), is_package=False
    )
    module = importlib.util.module_from_spec(spec)
    stubs["custom_components.beatbot_aquasense2_local.manager"] = manager_module
    with patch.dict("sys.modules", stubs):
        spec.loader.exec_module(module)
    return module


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        self.background = []
        self.tracked = []
        self.handlers = {}
        self.unsub_switch = Mock()
        self.unsub_stop = Mock()

        def listen(event, handler):
            async def fire_once(data):
                # HA removes its one-shot listener before invoking the callback.
                del self.handlers[event]
                await handler(data)

            def unsubscribe():
                if self.handlers.get(event) is not fire_once:
                    raise AssertionError("Unable to remove unknown job listener")
                del self.handlers[event]

            self.unsub_stop.side_effect = unsubscribe
            self.handlers[event] = fire_once
            return self.unsub_stop

        def background(hass, coro, name):
            task = asyncio.create_task(coro, name=name)
            self.background.append(task)
            return task

        def tracked(coro, name, **kwargs):
            task = asyncio.create_task(coro, name=name)
            self.tracked.append(task)
            return task

        self.hass.bus = types.SimpleNamespace(async_listen_once=listen)
        self.hass.async_create_task = Mock(side_effect=tracked)
        self.manager.entry.async_create_background_task = Mock(side_effect=background)
        self.switch_patch = patch.object(manager_module, "async_track_state_change_event", return_value=self.unsub_switch)
        self.switch_patch.start()
        self.addCleanup(self.switch_patch.stop)

    service = test_manager.ManagerTests.service

    async def test_completed_park_is_saved_on_stop_and_not_restored_as_pending(self):
        test_manager.ManagerTests.queue_park(self)
        await test_manager.ManagerTests.poll_at(self, 10, 0, 61, 0)
        await self.manager.async_stop()
        saved = self.manager.store.async_save.call_args.args[0]
        self.assertFalse(saved["park_pending"])
        self.assertIsNone(saved["park_requested_at"])
        self.assertIsNone(saved["cleaning_started_at"])
        restored = manager_module.BeatbotManager(self.hass, self.manager.entry)
        restored.store.async_load.return_value = saved
        await restored.async_initialize()
        self.assertFalse(restored.park_pending)
        self.assertFalse(restored.can_park)
        await restored.async_select_mode("Standard")

    async def test_stop_waits_for_photo_validation_worker_without_sending(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        loop = asyncio.get_running_loop()

        def validate(*args):
            started.set()
            try:
                release.wait(2)
                return "/private/image.jpg"
            finally:
                finished.set()

        self.manager.entry.options.update({"notify_service": "telegram_bot",
            "telegram_bot_entry_id": "bot-test", "telegram_chat_id": "123", "telegram_photo": "/private/image.jpg"})
        self.manager.completion_notifications = True
        self.hass.async_add_executor_job = lambda function, *args: loop.run_in_executor(None, function, *args)
        with patch.object(manager_module, "validate_photo", side_effect=validate):
            self.manager._task = asyncio.create_task(self.manager._notify_completion())
            try:
                self.assertTrue(await loop.run_in_executor(None, started.wait, 1))
                stop = asyncio.create_task(self.manager.async_stop())
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertFalse(stop.done())
                self.assertFalse(finished.is_set())
                self.manager.store.async_save.assert_not_awaited()
            finally:
                release.set()
                await self.manager.async_stop()
            await stop
        self.assertTrue(finished.is_set())
        self.hass.services.async_call.assert_not_awaited()
        self.manager.store.async_save.assert_awaited_once()

    async def test_active_parking_clock_survives_shutdown_and_reload(self):
        self.manager.selected_mode = self.manager.last_mode = "Standard"
        started = await test_manager.ManagerTests.poll_at(self, 0, 12, 90, 1)
        await self.manager.async_stop()
        saved = self.manager.store.async_save.call_args.args[0]
        self.assertEqual(saved["cleaning_started_at"], started.isoformat())
        restored = manager_module.BeatbotManager(self.hass, self.manager.entry)
        restored.store.async_load.return_value = saved
        with patch.object(manager_module, "_now", return_value=started + manager_module.PARK_AVAILABLE_DELAY):
            await restored.async_initialize()
            self.assertEqual(restored.cleaning_started_at, started)
            self.assertTrue(restored.can_park)

    async def asyncTearDown(self):
        await self.manager.async_stop()
        self.assertTrue(all(t.done() for t in self.background + self.tracked))

    async def test_offline_start_is_not_a_startup_task_and_stop_during_interval(self):
        self.hass.async_add_executor_job.side_effect = OSError("offline")
        self.manager.start()
        self.manager.start()
        for _ in range(20):
            if self.manager._failures:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(self.background), 1)
        self.hass.async_create_task.assert_not_called()
        self.assertEqual(self.manager._failures, 1)
        self.assertFalse(self.manager.online)
        await asyncio.wait_for(self.manager.async_stop(), 1)
        self.unsub_switch.assert_called_once()
        self.unsub_stop.assert_called_once()
        self.manager.store.async_save.assert_awaited_once()

    async def test_ha_stop_event_and_concurrent_unload_share_cleanup(self):
        self.manager.async_poll = AsyncMock()
        self.manager.start()
        handler = self.handlers["homeassistant_stop"]
        await asyncio.gather(handler(None), self.manager.async_stop(), self.manager.async_stop())
        await self.manager.async_stop()
        self.assertIsNone(self.manager._task)
        self.assertFalse(self.handlers)
        self.unsub_switch.assert_called_once()
        self.unsub_stop.assert_not_called()
        self.assertIsNone(self.manager._unsubscribe_stop)
        self.manager.store.async_save.assert_awaited_once()

    async def test_ha_stop_clears_reference_before_awaiting_cleanup(self):
        self.manager.async_poll = AsyncMock()
        self.manager.start()
        real_stop = self.manager.async_stop

        async def checked_stop():
            self.assertIsNone(self.manager._unsubscribe_stop)
            self.assertFalse(self.handlers)
            await real_stop()

        with patch.object(self.manager, "async_stop", side_effect=checked_stop):
            await self.handlers["homeassistant_stop"](None)
        self.unsub_stop.assert_not_called()
        self.unsub_switch.assert_called_once()
        self.manager.store.async_save.assert_awaited_once()

    async def test_unload_before_ha_stop_unregisters_once(self):
        self.manager.async_poll = AsyncMock()
        self.manager.start()
        self.hass.data = {manager_module.DOMAIN: {self.manager.entry.entry_id: self.manager}}
        self.hass.config_entries = types.SimpleNamespace(
            async_unload_platforms=AsyncMock(return_value=True),
        )
        hooks = load_setup_module()
        self.assertTrue(await hooks.async_unload_entry(self.hass, self.manager.entry))
        # A later HA-stop event has no remaining listener to dispatch.
        await asyncio.gather(*(handler(None) for handler in list(self.handlers.values())))
        await asyncio.gather(self.manager.async_stop(), self.manager.async_stop())
        self.assertFalse(self.handlers)
        self.assertIsNone(self.manager._unsubscribe_stop)
        self.unsub_stop.assert_called_once()
        self.unsub_switch.assert_called_once()
        self.manager.store.async_save.assert_awaited_once()

    async def test_cancelled_stop_caller_does_not_cancel_save_or_lose_cancellation(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def save(data):
            entered.set()
            await release.wait()

        self.manager.store.async_save.side_effect = save
        self.manager.async_poll = AsyncMock()
        self.manager.start()
        caller = asyncio.create_task(self.manager.async_stop())
        await entered.wait()
        self.manager.start()  # no new poller while cleanup is running
        self.assertEqual(len(self.background), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertFalse(self.manager._stop_task.done())
        release.set()
        await self.manager.async_stop()
        self.manager.store.async_save.assert_awaited_once()

    async def _stop_during_worker(self, discovery=False):
        entered, release, exited = threading.Event(), threading.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def worker(*args):
            entered.set()
            try:
                release.wait(2)
                if discovery:
                    return []
                return protocol.PollResult({"6": 12})
            finally:
                exited.set()

        def executor(fn, *args):
            return loop.run_in_executor(None, fn, *args)

        self.hass.async_add_executor_job = executor
        self.manager.battery = 77
        self.manager.client.poll = worker
        if discovery:
            self.manager._failures = 2
            self.manager.client.poll = Mock(side_effect=OSError("offline"))
        with patch.object(manager_module, "discover", worker):
            self.manager.start()
            try:
                async with asyncio.timeout(1):
                    while not entered.is_set():
                        await asyncio.sleep(0.001)
                stop = asyncio.create_task(self.manager.async_stop())
                await asyncio.sleep(0.01)
                self.assertFalse(stop.done())
                self.manager.store.async_save.assert_not_awaited()
                release.set()
                await asyncio.wait_for(stop, 1)
                self.assertTrue(exited.is_set())
                self.assertIsNone(self.manager._executor_future)
                self.assertEqual(self.manager.battery, 77)  # discard late observation
            finally:
                release.set()

    async def test_stop_during_real_executor_poll_waits_for_thread(self):
        await self._stop_during_worker()

    async def test_stop_during_real_executor_discovery_waits_for_thread(self):
        await self._stop_during_worker(discovery=True)

    async def test_restart_after_stop_and_persistent_state_restore(self):
        self.manager.async_poll = AsyncMock()
        self.manager.battery = 61
        self.manager.selected_mode = "Standard"
        self.manager.mode_pending = True
        self.manager.charge_target = 80
        self.manager.start()
        await self.manager.async_stop()
        saved = self.manager.store.async_save.call_args.args[0]
        replacement = manager_module.BeatbotManager(self.hass, self.manager.entry)
        replacement.store.async_load.return_value = saved
        await replacement.async_initialize()
        self.assertEqual(replacement.battery, 61)
        self.assertEqual(replacement.selected_mode, "Standard")
        self.assertTrue(replacement.mode_pending)
        self.assertEqual(replacement.charge_target, 80)
        self.manager.start()
        self.assertEqual(len(self.background), 2)
        await self.manager.async_stop()
        self.assertEqual(self.manager.store.async_save.await_count, 2)

    async def test_stop_before_start_is_idempotent(self):
        await asyncio.gather(self.manager.async_stop(), self.manager.async_stop())
        self.manager.store.async_save.assert_awaited_once()

    async def test_stop_waits_for_in_progress_history_save_and_preserves_final_edit(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def save(data):
            entered.set()
            await release.wait()

        self.manager.store.async_save.side_effect = save
        edit = asyncio.create_task(self.manager.async_edit_runtime("Boden", [3600, 4000], None))
        await entered.wait()
        stop = asyncio.create_task(self.manager.async_stop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertFalse(stop.done())
        release.set()
        await asyncio.gather(edit, stop)
        self.assertEqual(self.manager.store.async_save.await_count, 2)
        self.assertEqual(self.manager.store.async_save.call_args.args[0]["runtime"]["history"], {"Boden": [3600, 4000]})

    async def test_actual_entry_setup_unload_reload_hooks(self):
        hooks = load_setup_module()
        self.hass.data = {}
        self.hass.config_entries = types.SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        )
        entry = self.manager.entry
        with patch.object(manager_module.BeatbotManager, "async_poll", new_callable=AsyncMock):
            self.assertTrue(await hooks.async_setup_entry(self.hass, entry))
            first = self.hass.data[manager_module.DOMAIN][entry.entry_id]
            self.manager = first
            self.assertTrue(await hooks.async_unload_entry(self.hass, entry))
            first.store.async_save.assert_awaited_once()
            self.assertIsNone(first._task)
            self.assertNotIn(entry.entry_id, self.hass.data[manager_module.DOMAIN])
            self.assertTrue(await hooks.async_unload_entry(self.hass, entry))
            self.assertTrue(await hooks.async_setup_entry(self.hass, entry))
            self.manager = self.hass.data[manager_module.DOMAIN][entry.entry_id]
            self.assertIsNot(first, self.manager)
            self.assertEqual(len(self.background), 2)
            self.assertTrue(await hooks.async_unload_entry(self.hass, entry))

    async def test_http_setup_registers_authenticated_history_and_static_image(self):
        hooks = load_setup_module()
        self.hass.http = types.SimpleNamespace(register_view=Mock(), async_register_static_paths=AsyncMock())
        self.assertTrue(await hooks.async_setup(self.hass, {}))
        self.hass.http.register_view.assert_called_once()
        self.assertTrue(self.hass.http.register_view.call_args.args[0].requires_auth)
        self.hass.http.async_register_static_paths.assert_awaited_once()

    async def test_already_cancelled_background_task_still_saves(self):
        self.manager.async_poll = AsyncMock()
        self.manager.start()
        self.manager._task.cancel()  # HA/config entry can cancel it independently.
        await self.manager.async_stop()
        self.manager.store.async_save.assert_awaited_once()
        self.assertIsNone(self.manager._task)
