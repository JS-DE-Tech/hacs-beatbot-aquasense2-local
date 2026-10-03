"""Authenticated history route contract with external HTTP interfaces faked."""

import importlib
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_manager


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


aiohttp = types.ModuleType("aiohttp")
aiohttp.web = types.SimpleNamespace(HTTPForbidden=Forbidden, HTTPNotFound=NotFound,
    json_response=lambda data, headers: {"data": data, "headers": headers})
http = types.ModuleType("homeassistant.components.http")
http.HomeAssistantView = object
with patch.dict("sys.modules", {"aiohttp": aiohttp, "homeassistant.components.http": http}):
    view_module = importlib.import_module("custom_components.beatbot_aquasense2_local.history_view")


class HistoryViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_download_is_attachment_without_caching(self):
        manager = types.SimpleNamespace(async_export_runtime=AsyncMock(return_value={"format": "beatbot-history-v2"}))
        hass = types.SimpleNamespace(data={view_module.DOMAIN: {"entry": manager}})
        view = view_module.BeatbotHistoryView(hass)
        self.assertTrue(view.requires_auth)
        response = await view.get({"hass_user": types.SimpleNamespace(is_admin=True)}, "entry")
        self.assertIn("attachment", response["headers"]["Content-Disposition"])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")
        manager.async_export_runtime.assert_awaited_once()

    async def test_non_admin_and_unknown_robot_cannot_export(self):
        view = view_module.BeatbotHistoryView(types.SimpleNamespace(data={}))
        with self.assertRaises(Forbidden):
            await view.get({"hass_user": types.SimpleNamespace(is_admin=False)}, "entry")
        with self.assertRaises(NotFound):
            await view.get({"hass_user": types.SimpleNamespace(is_admin=True)}, "missing")
