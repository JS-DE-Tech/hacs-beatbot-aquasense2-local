"""Authenticated download of non-secret, per-robot learning history."""

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN


class BeatbotHistoryView(HomeAssistantView):
    url = f"/api/{DOMAIN}/history/{{entry_id}}"
    name = f"api:{DOMAIN}:history"
    requires_auth = True

    def __init__(self, hass) -> None:
        self.hass = hass

    async def get(self, request, entry_id):
        if not request["hass_user"].is_admin:
            raise web.HTTPForbidden()
        manager = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if manager is None:
            raise web.HTTPNotFound()
        return web.json_response(await manager.async_export_runtime(), headers={
            "Content-Disposition": 'attachment; filename="beatbot-laufzeiten.json"',
            "Cache-Control": "no-store",
        })
