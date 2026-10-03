"""Telegram routing, personal uploads and completion deduplication (no network)."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_completion_manager
import test_manager
import test_runtime_ui
from custom_components.beatbot_aquasense2_local import notification

CAPTION = "✅ Beatbot fertig.\nAquaSense 2 - Gewähltes Programm beendet."
OPTIONS = {"notify_service": "telegram_bot", "telegram_bot_entry_id": "bot-test",
           "telegram_chat_id": "-1001234567890"}
PNG = bytes.fromhex("89504e470d0a1a0a") + b"test-image-payload"


def config_at(directory):
    return types.SimpleNamespace(path=lambda *parts: str(Path(directory).joinpath(*parts)),
                                 allowlist_external_dirs=set())


class NotificationTests(unittest.TestCase):
    def test_positive_negative_and_whitespace_chat_ids(self):
        for raw, expected in ((123, 123), (" 123 ", 123), ("-1001234567890", -1001234567890)):
            self.assertEqual(notification.parse_chat_id(raw), expected)

    def test_reject_ambiguous_or_malformed_recipient(self):
        for raw in (None, "", True, 1.5, "1.5", "1e9", "@person", "123,456", [123], "123:token", 0, "-0", 2**52):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                notification.parse_chat_id(raw)

    def test_exact_text_payload_with_explicit_bot_and_chat(self):
        domain, service, data = notification.completion_call(OPTIONS)
        self.assertEqual((domain, service), ("telegram_bot", "send_message"))
        self.assertEqual(data, {"config_entry_id": "bot-test", "chat_id": [-1001234567890],
                                "message": CAPTION, "parse_mode": "plain_text"})

    def test_photo_is_one_captioned_message_not_two_messages(self):
        domain, service, data = notification.completion_call({**OPTIONS, "telegram_photo": "/private/image.jpg"})
        self.assertEqual(service, "send_photo")
        self.assertEqual(data["caption"], CAPTION)
        self.assertNotIn("message", data)
        self.assertEqual(data["file"], "/private/image.jpg")

    def test_missing_bot_or_chat_never_uses_default_recipient(self):
        for field in ("telegram_chat_id", "telegram_bot_entry_id"):
            with self.assertRaises(ValueError):
                notification.completion_call({key: value for key, value in OPTIONS.items() if key != field})

    def test_mobile_app_keeps_routing_and_uses_requested_text(self):
        domain, service, data = notification.completion_call({"notify_service": "mobile_app_phone"})
        self.assertEqual((domain, service), ("notify", "mobile_app_phone"))
        self.assertEqual(data, {"title": "✅ Beatbot fertig.", "message": "AquaSense 2 - Gewähltes Programm beendet."})

    def test_private_upload_survives_replacement_and_is_not_public(self):
        with tempfile.TemporaryDirectory() as directory:
            hass = types.SimpleNamespace(config=config_at(directory))
            source = Path(directory) / "upload"
            source.write_bytes(PNG)
            first = notification.store_photo(hass, source)
            self.assertEqual(notification.validate_photo(hass, first), first)
            self.assertNotIn("www", Path(first).parts)
            source.write_bytes(b"\xff\xd8\xfftest-jpeg")
            second = notification.store_photo(hass, source)
            self.assertNotEqual(first, second)
            self.assertTrue(Path(first).exists())
            self.assertEqual(notification.validate_photo(hass, second), second)
            self.assertEqual(hass.config.allowlist_external_dirs, set())

    def test_invalid_or_oversized_upload_does_not_overwrite_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            hass = types.SimpleNamespace(config=config_at(directory))
            source = Path(directory) / "upload"
            source.write_bytes(PNG)
            saved = notification.store_photo(hass, source)
            for payload in (b"", b"not-an-image", PNG + bytes(100)):
                source.write_bytes(payload)
                with patch.object(notification, "MAX_PHOTO_BYTES", 64), self.assertRaises(ValueError):
                    notification.store_photo(hass, source)
                self.assertEqual(Path(saved).read_bytes(), PNG)

    def test_arbitrary_file_paths_and_tampered_uploads_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            hass = types.SimpleNamespace(config=config_at(directory))
            source = Path(directory) / "private.jpg"
            source.write_bytes(PNG)
            with self.assertRaises(ValueError):
                notification.validate_photo(hass, str(source))
            saved = notification.store_photo(hass, source)
            Path(saved).write_bytes(PNG + b"changed")
            with self.assertRaises(ValueError):
                notification.validate_photo(hass, saved)


class TelegramFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_runtime_ui.RuntimeUITests.asyncSetUp(self)
        self.bot = types.SimpleNamespace(entry_id="bot-test", title="Test bot")
        self.flow.hass.config_entries.async_entries = lambda domain: [self.bot] if domain == "telegram_bot" else [self.entry]
        self.flow.hass.services.async_services = lambda: {
            "notify": {"mobile_app_test_phone": {}}, "telegram_bot": {"send_message": {}, "send_photo": {}}}

    async def test_single_bot_is_selected_and_id_is_normalized(self):
        result = await self.flow.async_step_settings({"notify_service": "telegram_bot", "telegram_chat_id": " -1001234567890 ",
                                                       "charger_switch": "switch.plug"})
        self.assertEqual(result["data"], {**OPTIONS, "charger_switch": "switch.plug"})

    async def test_multiple_bots_require_explicit_selection(self):
        self.flow.hass.config_entries.async_entries = lambda domain: [self.bot, types.SimpleNamespace(entry_id="second", title="Other bot")] if domain == "telegram_bot" else [self.entry]
        result = await self.flow.async_step_settings({"notify_service": "telegram_bot", "telegram_chat_id": "123"})
        self.assertEqual(result["errors"], {"telegram_bot_entry_id": "telegram_bot_required"})
        result = await self.flow.async_step_settings({**OPTIONS, "telegram_bot_entry_id": "second"})
        self.assertEqual(result["data"]["telegram_bot_entry_id"], "second")

    async def test_invalid_chat_or_missing_service_blocks_saving(self):
        result = await self.flow.async_step_settings({**OPTIONS, "telegram_chat_id": "@username"})
        self.assertEqual(result["errors"], {"telegram_chat_id": "invalid_telegram_chat"})
        self.flow.hass.services.async_services = lambda: {}
        result = await self.flow.async_step_settings(OPTIONS)
        self.assertEqual(result["errors"], {"notify_service": "notify_unavailable"})

    async def test_upload_consumed_saved_privately_and_no_upload_id_in_options(self):
        with tempfile.TemporaryDirectory() as directory:
            self.flow.hass.config = config_at(directory)
            source = Path(directory) / "temporary-upload"
            source.write_bytes(PNG)
            @contextmanager
            def upload(hass, file_id):
                self.assertEqual(file_id, "upload-id")
                try:
                    yield source
                finally:
                    source.unlink()
            with patch.object(test_runtime_ui.flow_module, "process_uploaded_file", upload):
                result = await self.flow.async_step_settings({**OPTIONS, "photo_upload": "upload-id"})
            self.assertFalse(source.exists())
            self.assertNotIn("photo_upload", result["data"])
            saved = result["data"]["telegram_photo"]
            self.assertEqual(Path(saved).read_bytes(), PNG)
            self.assertEqual(result["data"]["telegram_chat_id"], OPTIONS["telegram_chat_id"])

    async def test_keep_replace_remove_and_switch_channel(self):
        self.entry.options.update({**OPTIONS, "telegram_photo": "previous-image"})
        result = await self.flow.async_step_settings(OPTIONS)
        self.assertEqual(result["data"]["telegram_photo"], "previous-image")
        with patch.object(test_runtime_ui.flow_module, "_store_uploaded_photo", return_value="new-image"):
            result = await self.flow.async_step_settings({**OPTIONS, "photo_upload": "upload-id"})
        self.assertEqual(result["data"]["telegram_photo"], "new-image")
        result = await self.flow.async_step_settings({**OPTIONS, "remove_photo": True})
        self.assertNotIn("telegram_photo", result["data"])
        result = await self.flow.async_step_settings({"notify_service": "mobile_app_test_phone"})
        self.assertNotIn("telegram_chat_id", result["data"])
        self.assertEqual(result["data"]["telegram_photo"], "previous-image")

    async def test_upload_errors_and_conflicts_preserve_options(self):
        self.entry.options["telegram_photo"] = "previous-image"
        before = dict(self.entry.options)
        with patch.object(test_runtime_ui.flow_module, "_store_uploaded_photo", side_effect=ValueError("invalid")):
            result = await self.flow.async_step_settings({**OPTIONS, "photo_upload": "upload-id"})
        self.assertEqual(result["errors"], {"photo_upload": "invalid_telegram_photo"})
        self.assertEqual(self.entry.options, before)
        result = await self.flow.async_step_settings({**OPTIONS, "photo_upload": "upload-id", "remove_photo": True})
        self.assertEqual(result["errors"], {"photo_upload": "photo_conflict"})


class TelegramManagerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_manager.ManagerTests.asyncSetUp
    service = test_manager.ManagerTests.service
    poll_at = test_manager.ManagerTests.poll_at
    finish = test_completion_manager.CompletionManagerTests.finish

    async def configure(self):
        self.manager.entry.options.update(OPTIONS)
        self.hass.services.has_service = lambda domain, service: domain == "telegram_bot"
        self.hass.services.async_call = AsyncMock()
        await self.manager.async_set_completion_notifications(True)

    async def test_completion_sends_once_after_persist_and_never_on_offline_or_restore(self):
        await self.configure()
        self.hass.services.async_call.assert_not_awaited()
        async def delivery(*args, **kwargs):
            self.assertTrue(self.manager.store.async_save.call_args.args[0]["completion"]["finished"])
        self.hass.services.async_call.side_effect = delivery
        await self.finish()
        self.assertEqual(self.hass.services.async_call.call_args.args, notification.completion_call(OPTIONS))
        saved = self.manager._stored_data()
        self.manager.store.async_load.return_value = saved
        await self.manager.async_initialize()
        await self.poll_at(3200, 14, 61, 1)
        self.hass.async_add_executor_job.side_effect = OSError("offline")
        await self.manager.async_poll()
        self.hass.services.async_call.assert_awaited_once()

    async def test_failed_send_is_not_retried_or_fallen_back_to_another_chat(self):
        await self.configure()
        self.hass.services.async_call.side_effect = RuntimeError("delivery failed")
        with self.assertLogs(test_manager.manager_module.__name__, level="WARNING"):
            await self.finish()
        await self.poll_at(3200, 14, 61, 1)
        self.hass.services.async_call.assert_awaited_once()
        self.assertEqual(self.manager.cooldown.state, "cooling")

    async def test_photo_send_grants_only_own_folder_and_retains_caption(self):
        await self.configure()
        with tempfile.TemporaryDirectory() as directory:
            self.hass.config = config_at(directory)
            source = Path(directory) / "upload"
            source.write_bytes(PNG)
            photo = notification.store_photo(self.hass, source)
            self.manager.entry.options["telegram_photo"] = photo
            self.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
            await self.manager._notify_completion()
            call = self.hass.services.async_call.call_args
            self.assertEqual(call.args[0:2], ("telegram_bot", "send_photo"))
            self.assertEqual(call.args[2]["caption"], CAPTION)
            self.assertEqual(self.hass.config.allowlist_external_dirs, {str(Path(photo).parent)})
            self.hass.services.async_call.assert_awaited_once()

    async def test_missing_photo_logs_failure_without_text_duplicate_or_wider_file_access(self):
        await self.configure()
        with tempfile.TemporaryDirectory() as directory:
            self.hass.config = config_at(directory)
            self.manager.entry.options["telegram_photo"] = str(Path(directory) / "missing.jpg")
            self.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
            with self.assertLogs(test_manager.manager_module.__name__, level="WARNING"):
                await self.manager._notify_completion()
            self.hass.services.async_call.assert_not_awaited()
            self.assertFalse(self.hass.config.allowlist_external_dirs)

    async def test_disabled_or_invalid_target_never_sends(self):
        self.manager.entry.options.update(OPTIONS)
        self.hass.services.async_call = AsyncMock()
        await self.manager._notify_completion()
        self.hass.services.async_call.assert_not_awaited()
        self.manager.entry.options.pop("telegram_chat_id")
        with self.assertRaises(RuntimeError):
            await self.manager.async_set_completion_notifications(True)

    async def test_caller_cancellation_is_preserved(self):
        await self.configure()
        self.hass.services.async_call.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.manager._notify_completion()
