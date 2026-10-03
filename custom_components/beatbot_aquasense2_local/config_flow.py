"""UI setup and per-robot charger switch assignment."""

from __future__ import annotations

import ipaddress
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CHARGER_SWITCH,
    CONF_NOTIFY_SERVICE,
    CONF_TELEGRAM_BOT,
    CONF_TELEGRAM_CHAT,
    CONF_TELEGRAM_PHOTO,
    TELEGRAM_NOTIFY,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_VERSION,
    DOMAIN,
)
from .protocol import LocalBeatbot, discover
from .key_file import InvalidKeyFile, RobotCredentials, read_key_file
from .runtime_file import read_runtime_file
from .runtime import PROGRAMS, program_label
from .notification import parse_chat_id, store_photo


def _read_uploaded_key(hass, file_id: str) -> RobotCredentials:
    """Read and remove the temporary upload entirely in the executor."""
    with process_uploaded_file(hass, file_id) as path:
        return read_key_file(path)


def _read_uploaded_runtime(hass, file_id: str, device_id: str) -> list[dict] | dict:
    with process_uploaded_file(hass, file_id) as path:
        return read_runtime_file(path, device_id)


def _store_uploaded_photo(hass, file_id: str) -> str:
    with process_uploaded_file(hass, file_id) as path:
        return store_photo(hass, path)


def _user_schema(found: list[dict[str, Any]]) -> vol.Schema:
    ids = {item[CONF_DEVICE_ID]: item[CONF_DEVICE_ID] for item in found}
    id_field = vol.In(ids) if len(ids) > 1 else selector.TextSelector()
    default_id = found[0][CONF_DEVICE_ID] if len(found) == 1 else None
    fields: dict[Any, Any] = {
        vol.Optional(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_LOCAL_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_HOST): selector.TextSelector(),
    }
    fields[
        vol.Optional(CONF_DEVICE_ID, default=default_id)
        if default_id else vol.Required(CONF_DEVICE_ID)
    ] = id_field
    return vol.Schema(fields)


class BeatbotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Discover a matching device and verify the entered local key."""

    VERSION = 1

    def __init__(self) -> None:
        self._found: list[dict[str, Any]] | None = None
        self._imported: RobotCredentials | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="user", menu_options=["key_file", "manual"])

    async def _async_discover(self) -> None:
        if self._found is None:
            try:
                self._found = await self.hass.async_add_executor_job(discover, None, 12)
            except Exception:
                self._found = []

    async def _async_validate(self, user_input: dict[str, Any]) -> tuple[dict, dict]:
        await self._async_discover()
        errors: dict[str, str] = {}
        device_id = (user_input.get(CONF_DEVICE_ID) or "").strip()
        host = (user_input.get(CONF_HOST) or "").strip()
        local_key = user_input[CONF_LOCAL_KEY]
        matching = next((item for item in self._found if item[CONF_DEVICE_ID] == device_id), None)
        if device_id and not matching:
            try:
                targeted = await self.hass.async_add_executor_job(discover, device_id, 12)
            except Exception:
                targeted = []
            matching = next((item for item in targeted if item[CONF_DEVICE_ID] == device_id), None)
        if not matching:
            errors["base"] = "not_found"
        elif not host:
            host = matching[CONF_HOST]
        try:
            if not ipaddress.ip_address(host).is_private:
                raise ValueError("Not a private address")
        except ValueError:
            errors[CONF_HOST] = "host_required"
        if not device_id:
            errors[CONF_DEVICE_ID] = "device_required"
        if len(local_key) != 16:
            errors[CONF_LOCAL_KEY] = "invalid_local_key"
        version = float(matching[CONF_VERSION]) if matching else 3.3
        data = {CONF_DEVICE_ID: device_id, CONF_HOST: host,
                CONF_LOCAL_KEY: local_key, CONF_VERSION: version,
                CONF_NAME: (user_input.get(CONF_NAME) or "").strip()}
        if not errors:
            client = LocalBeatbot(device_id, host, local_key, version)
            try:
                result = await self.hass.async_add_executor_job(client.poll)
                if not result.dps or "6" not in result.dps:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
        return errors, data

    async def _async_create_robot(self, data: dict) -> FlowResult:
        device_id = data[CONF_DEVICE_ID]
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()
        self._imported = None
        name = data.get(CONF_NAME, "").strip()
        title = f"Beatbot AquaSense 2 - {name}" if name else "Beatbot AquaSense 2"
        return self.async_create_entry(title=title, data=data)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self._async_discover()
        errors = {}
        if user_input is not None:
            errors, data = await self._async_validate(user_input)
            if not errors:
                return await self._async_create_robot(data)
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(_user_schema(self._found), user_input or {}),
            errors=errors,
            description_placeholders={"count": str(len(self._found))},
        )

    async def async_step_key_file(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                self._imported = await self.hass.async_add_executor_job(
                    _read_uploaded_key, self.hass, user_input["key_file"]
                )
            except (InvalidKeyFile, OSError, ValueError):
                errors["base"] = "invalid_key_file"
            else:
                return await self.async_step_key_connect()
        return self.async_show_form(step_id="key_file", errors=errors, data_schema=vol.Schema({
            vol.Required("key_file"): selector.FileSelector(selector.FileSelectorConfig(accept=".json"))
        }))

    async def async_step_key_connect(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._imported is None:
            return await self.async_step_key_file()
        errors = {}
        if user_input is not None:
            values = self._imported.as_config()
            # Empty host means rediscover; exported addresses may be outdated.
            values[CONF_HOST] = user_input.get(CONF_HOST, "")
            values[CONF_NAME] = user_input.get(CONF_NAME, "")
            errors, data = await self._async_validate(values)
            if not errors:
                return await self._async_create_robot(data)
        return self.async_show_form(
            step_id="key_connect", errors=errors,
            description_placeholders={"device_id": self._imported.device_id},
            data_schema=self.add_suggested_values_to_schema(vol.Schema({
                vol.Optional(CONF_NAME): selector.TextSelector(),
                vol.Optional(CONF_HOST): selector.TextSelector(),
            }), user_input or {}),
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> BeatbotOptionsFlow:
        return BeatbotOptionsFlow()


class BeatbotOptionsFlow(config_entries.OptionsFlowWithReload):
    """Assign an existing HA switch, such as a Shelly Plug, to this robot."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:  # Compatibility with an already open older form.
            return await self.async_step_settings(user_input)
        return self.async_show_menu(step_id="init", menu_options=[
            "settings", "history", "history_export", "history_import"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            switch_id = user_input.get(CONF_CHARGER_SWITCH)
            if switch_id:
                registered = er.async_get(self.hass).async_get(switch_id)
                if registered and registered.platform == DOMAIN:
                    errors[CONF_CHARGER_SWITCH] = "proxy_not_allowed"
                for other in self.hass.config_entries.async_entries(DOMAIN):
                    if other.entry_id != self.config_entry.entry_id and other.options.get(CONF_CHARGER_SWITCH) == switch_id:
                        errors[CONF_CHARGER_SWITCH] = "already_assigned"
                        break
            if not errors:
                if user_input.get("runtime_file"):
                    manager = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
                    if manager is None:
                        errors["base"] = "runtime_unavailable"
                    else:
                        try:
                            samples = await self.hass.async_add_executor_job(
                                _read_uploaded_runtime, self.hass, user_input["runtime_file"],
                                self.config_entry.data[CONF_DEVICE_ID],
                            )
                            if isinstance(samples, list):
                                await manager.async_import_runtime_samples(samples)
                            else:
                                errors["base"] = "use_history_import"
                        except (OSError, ValueError):
                            errors["base"] = "invalid_runtime_file"
                        except HomeAssistantError:
                            errors["base"] = "runtime_unavailable"
                if errors:
                    return self.async_show_form(step_id="settings", data_schema=self.add_suggested_values_to_schema(
                        self._schema(), {CONF_CHARGER_SWITCH: switch_id} if switch_id else {}), errors=errors,
                        description_placeholders=self._photo_description())
                service = user_input.get(CONF_NOTIFY_SERVICE)
                telegram = {}
                if service == TELEGRAM_NOTIFY:
                    bots = self._telegram_bots()
                    bot = user_input.get(CONF_TELEGRAM_BOT)
                    if not bot and len(bots) == 1:
                        bot = next(iter(bots))
                    if bot not in bots:
                        errors[CONF_TELEGRAM_BOT] = "telegram_bot_required"
                    else:
                        telegram[CONF_TELEGRAM_BOT] = bot
                    try:
                        telegram[CONF_TELEGRAM_CHAT] = str(parse_chat_id(user_input.get(CONF_TELEGRAM_CHAT)))
                    except ValueError:
                        errors[CONF_TELEGRAM_CHAT] = "invalid_telegram_chat"
                    photo = user_input.get("photo_upload") or (
                        self.config_entry.options.get(CONF_TELEGRAM_PHOTO) if not user_input.get("remove_photo") else None)
                    action = "send_photo" if photo else "send_message"
                    if action not in self.hass.services.async_services().get(TELEGRAM_NOTIFY, {}):
                        errors[CONF_NOTIFY_SERVICE] = "notify_unavailable"
                elif service and service not in self._notify_services():
                    errors[CONF_NOTIFY_SERVICE] = "notify_unavailable"
                if user_input.get("photo_upload") and user_input.get("remove_photo"):
                    errors["photo_upload"] = "photo_conflict"
                photo = self.config_entry.options.get(CONF_TELEGRAM_PHOTO)
                if not errors and user_input.get("photo_upload"):
                    try:
                        photo = await self.hass.async_add_executor_job(
                            _store_uploaded_photo, self.hass, user_input["photo_upload"])
                    except (OSError, ValueError, RuntimeError):
                        errors["photo_upload"] = "invalid_telegram_photo"
                elif user_input.get("remove_photo"):
                    photo = None
                if not errors:
                    data = dict(self.config_entry.options)
                    for field in (CONF_TELEGRAM_BOT, CONF_TELEGRAM_CHAT, CONF_TELEGRAM_PHOTO):
                        data.pop(field, None)
                    for field in (CONF_CHARGER_SWITCH, CONF_NOTIFY_SERVICE):
                        data.pop(field, None)
                        if user_input.get(field):
                            data[field] = user_input[field]
                    data.update(telegram)
                    if photo:
                        data[CONF_TELEGRAM_PHOTO] = photo
                    return self.async_create_entry(data=data)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                self._schema(), user_input if user_input is not None else self.config_entry.options),
            errors=errors,
            description_placeholders=self._photo_description(),
        )

    def _photo_description(self) -> dict[str, str]:
        return {"photo_status": "✓" if self.config_entry.options.get(CONF_TELEGRAM_PHOTO) else "–"}

    def _notify_services(self) -> list[str]:
        return sorted(name for name in self.hass.services.async_services().get("notify", {})
                      if name.startswith("mobile_app_"))

    def _telegram_bots(self) -> dict[str, str]:
        return {entry.entry_id: entry.title for entry in self.hass.config_entries.async_entries(TELEGRAM_NOTIFY)}

    def _schema(self) -> vol.Schema:
        return vol.Schema({
            vol.Optional(CONF_CHARGER_SWITCH): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_NOTIFY_SERVICE): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": "", "label": "Keine Fertigmeldung"}]
                + [{"value": TELEGRAM_NOTIFY, "label": "Telegram"}]
                + [{"value": name, "label": name.removeprefix("mobile_app_")} for name in self._notify_services()],
                mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_TELEGRAM_BOT): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": "", "label": "Automatisch bei genau einem Bot"}]
                + [{"value": key, "label": title} for key, title in self._telegram_bots().items()],
                mode=selector.SelectSelectorMode.DROPDOWN)),
            vol.Optional(CONF_TELEGRAM_CHAT): selector.TextSelector(),
            vol.Optional("photo_upload"): selector.FileSelector(selector.FileSelectorConfig(accept=".jpg,.jpeg,.png")),
            vol.Optional("remove_photo", default=False): selector.BooleanSelector(),
        })

    def _manager(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_history(self, user_input=None):
        manager = self._manager()
        if manager is None:
            return self.async_abort(reason="runtime_unavailable")
        if user_input is not None and user_input.get("program") in PROGRAMS:
            self._history_key = user_input["program"]
            return await self.async_step_history_edit()
        rows = ["| Programm | Läufe | Schätzung |", "|---|---:|---:|"]
        for key in PROGRAMS:
            estimate = manager.runtime.estimate(key)
            seconds = estimate["estimated_seconds"]
            value = f"{seconds / 60:.1f} min" if seconds is not None else "–"
            if estimate["manual_seconds"] is not None:
                value += " (manuell)"
            rows.append(f"| {program_label(key)} | {estimate['sample_count']} | {value} |")
        return self.async_show_form(step_id="history", description_placeholders={"overview": "\n".join(rows)},
            data_schema=vol.Schema({vol.Required("program"): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[{"value": key, "label": program_label(key)} for key in PROGRAMS],
                mode=selector.SelectSelectorMode.DROPDOWN))}))

    async def async_step_history_edit(self, user_input=None):
        manager = self._manager()
        if manager is None:
            return self.async_abort(reason="runtime_unavailable")
        key = getattr(self, "_history_key", None)
        if key not in PROGRAMS:
            return await self.async_step_history()
        errors = {}
        if user_input is not None:
            try:
                samples = [float(line.strip().replace(",", ".")) * 60
                           for line in user_input.get("samples_minutes", "").splitlines() if line.strip()]
                value = user_input.get("manual_minutes", "").strip()
                manual = float(value.replace(",", ".")) * 60 if value else None
                await manager.async_edit_runtime(key, samples, manual)
            except (ValueError, TypeError):
                errors["base"] = "invalid_times"
            except HomeAssistantError:
                errors["base"] = "runtime_busy"
            except OSError:
                errors["base"] = "save_failed"
            else:
                return await self.async_step_history()
        defaults = {"samples_minutes": "\n".join(format(value / 60, ".12g") for value in manager.runtime.history.get(key, [])),
                    "manual_minutes": format(manager.runtime.manual_seconds[key] / 60, ".12g") if key in manager.runtime.manual_seconds else ""}
        return self.async_show_form(step_id="history_edit", errors=errors,
            description_placeholders={"program": program_label(key)},
            data_schema=self.add_suggested_values_to_schema(vol.Schema({
                vol.Optional("samples_minutes"): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional("manual_minutes"): selector.TextSelector(),
            }), user_input if user_input is not None else defaults))

    async def async_step_history_export(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        if self._manager() is None:
            return self.async_abort(reason="runtime_unavailable")
        from homeassistant.components.http.auth import async_sign_path
        url = async_sign_path(self.hass, f"/api/{DOMAIN}/history/{self.config_entry.entry_id}", timedelta(minutes=5))
        return self.async_show_form(step_id="history_export", data_schema=vol.Schema({}),
                                   description_placeholders={"download_url": url})

    async def async_step_history_import(self, user_input=None):
        errors = {}
        if user_input is not None:
            manager = self._manager()
            if manager is None:
                errors["base"] = "runtime_unavailable"
            else:
                try:
                    data = await self.hass.async_add_executor_job(_read_uploaded_runtime, self.hass,
                        user_input["runtime_file"], self.config_entry.data[CONF_DEVICE_ID])
                    if isinstance(data, list):
                        await manager.async_import_runtime_samples(data)
                    elif not user_input.get("replace_history"):
                        errors["base"] = "confirm_replace"
                    else:
                        await manager.async_restore_runtime_backup(data)
                except ValueError:
                    errors["base"] = "invalid_runtime_file"
                except HomeAssistantError:
                    errors["base"] = "runtime_busy"
                except OSError:
                    errors["base"] = "save_failed"
                if not errors:
                    return await self.async_step_history()
        return self.async_show_form(step_id="history_import", errors=errors, data_schema=vol.Schema({
            vol.Required("runtime_file"): selector.FileSelector(selector.FileSelectorConfig(accept=".json")),
            vol.Optional("replace_history", default=False): selector.BooleanSelector(),
        }))
