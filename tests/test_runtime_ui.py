"""Exercise real flow/entity wiring with explicit external HA/selector fakes."""

import importlib
import io
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import test_manager
import test_runtime_file

PREFIX = "custom_components.beatbot_aquasense2_local"


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def add_suggested_values_to_schema(self, schema, values):
        return schema


def load_modules():
    stubs = dict(test_manager.stubs)
    modules = {
        "voluptuous": {"Schema": lambda data: data, "Optional": lambda key, **kw: key,
                       "Required": lambda key, **kw: key, "In": lambda value: value},
        "homeassistant.config_entries": {"ConfigEntry": object, "ConfigFlow": Flow, "OptionsFlowWithReload": Flow},
        "homeassistant.const": {"CONF_NAME": "name", "EVENT_HOMEASSISTANT_STOP": "homeassistant_stop"},
        "homeassistant.components.file_upload": {"process_uploaded_file": Mock()},
        "homeassistant.data_entry_flow": {"FlowResult": dict},
        "homeassistant.helpers.entity_registry": {"async_get": lambda hass: types.SimpleNamespace(async_get=lambda entity: None)},
        "homeassistant.helpers.selector": {name: Mock() for name in (
            "FileSelector", "FileSelectorConfig", "EntitySelector", "EntitySelectorConfig",
            "TextSelector", "TextSelectorConfig", "TextSelectorType", "SelectSelector",
            "SelectSelectorConfig", "SelectSelectorMode", "BooleanSelector")},
        "homeassistant.components.sensor": {"SensorEntity": type("Sensor", (), {}),
            "SensorDeviceClass": types.SimpleNamespace(BATTERY="battery", DURATION="duration"),
            "SensorStateClass": types.SimpleNamespace(MEASUREMENT="measurement")},
        "homeassistant.components.switch": {"SwitchEntity": type("Switch", (), {})},
        "homeassistant.components.binary_sensor": {"BinarySensorEntity": type("BinarySensor", (), {}),
            "BinarySensorDeviceClass": types.SimpleNamespace(CONNECTIVITY="connectivity", PROBLEM="problem")},
        "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": object},
        "homeassistant.helpers.entity": {"DeviceInfo": dict, "Entity": type("Entity", (), {})},
    }
    for name, fields in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(fields)
        stubs[name] = module
    stubs["homeassistant"].config_entries = stubs["homeassistant.config_entries"]
    stubs["homeassistant.helpers"].selector = stubs["homeassistant.helpers.selector"]
    stubs["homeassistant.helpers"].entity_registry = stubs["homeassistant.helpers.entity_registry"]
    stubs[f"{PREFIX}.manager"] = test_manager.manager_module
    with patch.dict("sys.modules", stubs):
        return tuple(importlib.import_module(f"{PREFIX}.{name}") for name in ("config_flow", "sensor", "binary_sensor", "switch"))


flow_module, sensor_module, binary_module, switch_module = load_modules()


class RuntimeUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.samples = test_runtime_file.RuntimeImportTests().parse(test_runtime_file.RuntimeImportTests().payload())
        self.manager = types.SimpleNamespace(async_import_runtime_samples=AsyncMock(return_value=2))
        self.flow = flow_module.BeatbotOptionsFlow()
        self.entry = types.SimpleNamespace(entry_id="test", data={"device_id": "test"},
                                           options={"charger_switch": "switch.plug"})
        self.flow.config_entry = self.entry
        self.flow.hass = types.SimpleNamespace(data={"beatbot_aquasense2_local": {"test": self.manager}},
            services=types.SimpleNamespace(async_services=lambda: {"notify": {"mobile_app_test_phone": {}}}),
            async_add_executor_job=AsyncMock(side_effect=lambda function, *args: function(*args)),
            config_entries=types.SimpleNamespace(async_entries=lambda domain: [self.entry] if domain == "beatbot_aquasense2_local" else []))

    async def test_option_upload_imports_without_persisting_upload_id(self):
        with patch.object(flow_module, "_read_uploaded_runtime", return_value=self.samples) as reader:
            result = await self.flow.async_step_init({"charger_switch": "switch.plug", "runtime_file": "upload-id"})
        self.assertEqual(result["data"], {"charger_switch": "switch.plug"})
        reader.assert_called_once_with(self.flow.hass, "upload-id", "test")
        self.manager.async_import_runtime_samples.assert_awaited_once_with(self.samples)

    async def test_invalid_file_keeps_form_no_manager_mutation(self):
        with patch.object(flow_module, "_read_uploaded_runtime", side_effect=ValueError("wrong robot")):
            result = await self.flow.async_step_init({"charger_switch": "switch.plug", "runtime_file": "upload-id"})
        self.assertEqual(result["errors"], {"base": "invalid_runtime_file"})
        self.manager.async_import_runtime_samples.assert_not_awaited()

    async def test_busy_or_unloaded_integration_gives_actionable_error(self):
        self.manager.async_import_runtime_samples.side_effect = RuntimeError("busy")
        with patch.object(flow_module, "_read_uploaded_runtime", return_value=self.samples):
            result = await self.flow.async_step_init({"runtime_file": "upload-id"})
        self.assertEqual(result["errors"], {"base": "runtime_unavailable"})
        self.flow.hass.data = {}
        result = await self.flow.async_step_init({"runtime_file": "upload-id"})
        self.assertEqual(result["errors"], {"base": "runtime_unavailable"})

    async def test_charger_options_work_without_import(self):
        result = await self.flow.async_step_init({"charger_switch": "switch.plug"})
        self.assertEqual(result["data"], {"charger_switch": "switch.plug"})
        self.manager.async_import_runtime_samples.assert_not_awaited()

    async def test_options_menu_contains_settings_history_import_and_export(self):
        result = await self.flow.async_step_init()
        self.assertEqual(result["menu_options"], ["settings", "history", "history_export", "history_import"])

    async def test_mobile_app_target_is_validated_and_saved(self):
        result = await self.flow.async_step_settings({"charger_switch": "switch.plug", "notify_service": "mobile_app_test_phone"})
        self.assertEqual(result["data"]["notify_service"], "mobile_app_test_phone")
        result = await self.flow.async_step_settings({"charger_switch": "switch.plug", "notify_service": "mobile_app_missing"})
        self.assertEqual(result["errors"], {"notify_service": "notify_unavailable"})

    async def test_history_overview_and_edit_use_all_variants_and_minutes(self):
        self.manager.runtime = test_manager.manager_module.RuntimeLearner()
        self.manager.runtime.history = {"Boden": [3600, 4200]}
        self.manager.async_edit_runtime = AsyncMock()
        result = await self.flow.async_step_history()
        overview = result["description_placeholders"]["overview"]
        self.assertIn("65.0 min", overview)
        self.assertIn("Boden ×2, Wand ×2", overview)
        self.assertEqual(len(overview.splitlines()), 16)
        result = await self.flow.async_step_history({"program": "Boden"})
        self.assertEqual(result["step_id"], "history_edit")
        await self.flow.async_step_history_edit({"samples_minutes": "60\n65,5", "manual_minutes": "70"})
        self.manager.async_edit_runtime.assert_awaited_once_with("Boden", [3600, 3930], 4200)

    async def test_full_restore_requires_explicit_confirmation(self):
        self.manager.async_restore_runtime_backup = AsyncMock()
        self.manager.runtime = test_manager.manager_module.RuntimeLearner()
        with patch.object(flow_module, "_read_uploaded_runtime", return_value={"history": {}}):
            result = await self.flow.async_step_history_import({"runtime_file": "upload"})
            self.assertEqual(result["errors"], {"base": "confirm_replace"})
            self.manager.async_restore_runtime_backup.assert_not_awaited()
            await self.flow.async_step_history_import({"runtime_file": "upload", "replace_history": True})
        self.manager.async_restore_runtime_backup.assert_awaited_once_with({"history": {}})

    async def test_export_link_uses_expiring_authenticated_route(self):
        auth = types.ModuleType("homeassistant.components.http.auth")
        auth.async_sign_path = Mock(return_value="/api/signed-test-link")
        with patch.dict("sys.modules", {auth.__name__: auth}):
            result = await self.flow.async_step_history_export()
        self.assertEqual(result["description_placeholders"], {"download_url": "/api/signed-test-link"})
        self.assertEqual(auth.async_sign_path.call_args.args[2].total_seconds(), 300)
        self.assertTrue(auth.async_sign_path.call_args.args[1].endswith("/history/test"))

    async def test_inferred_off_display_keeps_reported_status_for_diagnostics(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        from datetime import timedelta
        self.manager.robot_status = "standby"
        self.manager.cleaning_state = "Bereit"
        self.manager._offline_since = datetime.now(timezone.utc) - timedelta(minutes=6)
        sensor = sensor_module.BeatbotCleaningState(self.manager)
        self.assertEqual(sensor.native_value, "Ausgeschaltet")
        self.assertTrue(sensor.extra_state_attributes["inferred_off"])
        self.assertEqual(sensor.extra_state_attributes["last_reported_status"], "standby")
        self.manager.online = True
        self.assertEqual(sensor.native_value, "Bereit")

    async def test_countdown_and_filter_reminder_entities(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        now = datetime.now(timezone.utc)
        self.manager.cooldown.state = "cooling"
        self.manager.cooldown.deadline = now.timestamp() + 7200
        clock = Mock()
        clock.now.return_value = now
        with patch.object(sensor_module, "datetime", clock):
            self.assertEqual(sensor_module.BeatbotChargeCountdown(self.manager).native_value, "02:00:00")
        reminder = binary_module.BeatbotFilterCleaningRequired(self.manager)
        self.manager.filter_cleaning_required = True
        self.assertTrue(reminder.is_on)
        self.manager.filter_cleaning_required = False
        self.assertFalse(reminder.is_on)

    async def test_notification_switch_registered_and_toggles_without_sending(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        self.hass.data = {"beatbot_aquasense2_local": {"test": self.manager}}
        self.manager.entry.options["notify_service"] = "mobile_app_test_phone"
        self.hass.services.has_service = lambda *args: True
        added = Mock()
        await switch_module.async_setup_entry(self.hass, self.manager.entry, added)
        entities = added.call_args.args[0]
        switch = next(entity for entity in entities if isinstance(entity, switch_module.BeatbotCompletionSwitch))
        self.assertFalse(switch.is_on)
        await switch.async_turn_on()
        self.assertTrue(switch.is_on)
        await switch.async_turn_off()
        self.assertFalse(switch.is_on)
        self.hass.services.async_call.assert_not_awaited()

    async def test_upload_context_is_cleaned_on_validation_failure(self):
        context = Mock()
        context.__enter__ = Mock(return_value=types.SimpleNamespace(open=lambda mode: io.BytesIO(b"{}")))
        context.__exit__ = Mock(return_value=False)
        with patch.object(flow_module, "process_uploaded_file", return_value=context):
            with self.assertRaises(ValueError):
                flow_module._read_uploaded_runtime(self.flow.hass, "upload-id", "test")
        context.__exit__.assert_called_once()

    async def test_new_entity_values_warning_and_selection(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        self.manager.selected_mode = "Boden"
        self.manager.runtime.battery_history = {"Boden": [19, 14], "Standard": [40, 45]}
        self.manager.online = True
        self.manager.battery = 23
        self.manager.battery_seen = datetime.now(timezone.utc)
        sensor = sensor_module.BeatbotBatteryConsumption(self.manager)
        warning = binary_module.BeatbotBatteryInsufficient(self.manager)
        self.assertEqual(sensor.native_value, 16.5)
        self.assertTrue(warning.is_on)
        self.assertTrue(warning.available)
        self.manager.selected_mode = "Standard"
        self.assertEqual(sensor.native_value, 42.5)
        self.manager.selected_mode = "ECO"
        self.assertIsNone(sensor.native_value)
        self.assertFalse(warning.available)
        self.manager.selected_mode = "Boden"
        self.manager.online = False
        self.assertEqual(sensor.native_value, 16.5)
        self.assertIsNone(warning.is_on)
        self.assertFalse(warning.available)

    async def test_filter_entity_fresh_missing_clear_and_unknown(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        warning = binary_module.BeatbotFilterBasketMissing(self.manager)
        self.assertFalse(warning.available)
        self.manager.online = True
        self.manager.fault_seen = datetime.now(timezone.utc)
        self.manager.fault_code = 2
        self.assertTrue(warning.is_on)
        self.assertTrue(warning.available)
        self.assertEqual(warning.extra_state_attributes["raw_fault_code"], 2)
        self.manager.fault_code = 0
        self.assertFalse(warning.is_on)
        self.assertTrue(warning.available)
        self.manager.fault_code = 3
        self.assertIsNone(warning.is_on)
        self.assertFalse(warning.available)

    async def test_filter_entity_offline_retains_diagnostics_not_clear_state(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        self.manager.fault_code = 2
        self.manager.fault_seen = datetime.now(timezone.utc)
        warning = binary_module.BeatbotFilterBasketMissing(self.manager)
        self.assertIsNone(warning.is_on)
        self.assertFalse(warning.available)
        self.assertTrue(warning.extra_state_attributes["last_known_filter_basket_missing"])
        self.assertTrue(warning.extra_state_attributes["stale"])

    async def test_filter_entity_registered_once_for_same_device(self):
        await test_manager.ManagerTests.asyncSetUp(self)
        self.hass.data = {"beatbot_aquasense2_local": {"test": self.manager}}
        added = Mock()
        await binary_module.async_setup_entry(self.hass, self.manager.entry, added)
        entities = added.call_args.args[0]
        filters = [entity for entity in entities if isinstance(entity, binary_module.BeatbotFilterBasketMissing)]
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]._attr_unique_id, "test_filter_basket_missing")
        self.assertEqual(filters[0]._attr_device_info["identifiers"], {("beatbot_aquasense2_local", "test")})

    service = test_manager.ManagerTests.service
