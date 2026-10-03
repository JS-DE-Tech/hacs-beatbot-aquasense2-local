"""State, retry and charging control for one AquaSense 2."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CHARGER_SWITCH,
    CONF_NOTIFY_SERVICE,
    OFFLINE_IDLE_STATES,
    OFFLINE_OFF_DELAY,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_VERSION,
    FLOOR_ONLY_MODES,
    MODE_VALUES,
    PARK_ACCEPTED_STATES,
    PARK_ACTIVE_STATES,
    PARK_AVAILABLE_DELAY,
    PARK_DONE_STATES,
    PARK_MAX_DURATION,
    PARK_RETRY_INTERVAL,
    DOMAIN,
    STATUS_LABELS,
    LEGACY_STATUS_LABELS,
)
from .protocol import LocalBeatbot, decode_mode, discover, status_name, decode_filter_basket_missing
from .policy import charge_cutoff_due
from .runtime import Program, RuntimeLearner, MULTI_DURATIONS, MAX_EDGE_GAP, MAX_RUN, READY, PROGRAMS
from .runtime_file import export_runtime_file
from .charging import CooldownCharging
from .completion import CompletionTracker
from .notification import completion_call, validate_photo

_LOGGER = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


class BeatbotManager:
    """Polls locally, preserves last values and coordinates the selected plug."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.client = LocalBeatbot(
            entry.data[CONF_DEVICE_ID],
            entry.data[CONF_HOST],
            entry.data[CONF_LOCAL_KEY],
            float(entry.data.get(CONF_VERSION, 3.3)),
        )
        self.charger_switch: str | None = entry.options.get(CONF_CHARGER_SWITCH)
        self.store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")
        self.online = False
        self.battery: int | None = None
        self.battery_seen: datetime | None = None
        self.fault_code: int | None = None
        self.fault_seen: datetime | None = None
        self.last_mode: str | None = None
        self.last_program_key: str | None = None
        self._confirmed_program: Program | None = None
        self._confirmed_program_at: float | None = None
        self.selected_mode: str | None = None
        self.mode_pending = False
        self.floor_count = 1
        self.wall_count = 1
        self.multi_duration = "Max"
        self.runtime = RuntimeLearner()
        self.cooldown = CooldownCharging()
        self.completion = CompletionTracker()
        self.filter_cleaning_required = False
        self.completion_notifications = False
        self.last_completion_at: datetime | None = None
        self._offline_since: datetime | None = None
        self._auto_charge_command = False
        self._charge_start_retry_at: datetime | None = None
        self.robot_status: str | None = None
        self.cleaning_state: str | None = None
        self.cleaning_started_at: datetime | None = None
        self.position: int | None = None
        self.last_seen: datetime | None = None
        self.park_pending = False
        self.park_state = "idle"
        self.park_requested_at: datetime | None = None
        self.last_park_send_at: datetime | None = None
        self.charge_target = 100
        self.charge_state = "not_configured" if not self.charger_switch else "plug_off"
        self.charge_started_at: datetime | None = None
        self.cutoff_requested_at: datetime | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._executor_future: asyncio.Future | None = None
        self._unsubscribe_stop: Callable[[], None] | None = None
        self._unsubscribe_switch: Callable[[], None] | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._charge_lock = asyncio.Lock()
        self._failures = 0
        self._last_discovery: datetime | None = None

    async def async_initialize(self) -> None:
        """Load only non-secret state. The local key stays in HA's config entry."""
        saved = await self.store.async_load() or {}
        self.runtime.restore(saved.get("runtime"))
        self.completion.restore(saved.get("completion"))
        self.filter_cleaning_required = saved.get("filter_cleaning_required") is True
        self.completion_notifications = saved.get("completion_notifications") is True
        self.last_completion_at = _parse_time(saved.get("last_completion_at"))
        if isinstance(saved.get("last_program_key"), str):
            self.last_program_key = saved["last_program_key"]
        if saved.get("cooldown_switch") == self.charger_switch:
            self.cooldown.restore(saved.get("cooldown"))
        options = saved.get("program_options", {})
        try:
            program = Program("Bereich", options.get("floor", 1), options.get("wall", 1), options.get("duration", "Max"))
            self.floor_count, self.wall_count, self.multi_duration = program.floor, program.wall, program.duration
        except (ValueError, TypeError):
            pass
        battery = saved.get("battery")
        if type(battery) is int and 0 <= battery <= 100:
            self.battery = battery
        self.battery_seen = _parse_time(saved.get("battery_seen"))
        fault = saved.get("fault_code")
        self.fault_code = fault if type(fault) is int and fault >= 0 else None
        self.fault_seen = _parse_time(saved.get("fault_seen"))
        for field in ("last_mode", "selected_mode"):
            value = saved.get(field)
            if value in MODE_VALUES:
                setattr(self, field, value)
        self.mode_pending = bool(saved.get("mode_pending", False)) and self.selected_mode is not None
        status = saved.get("robot_status")
        self.robot_status = status if isinstance(status, str) else None
        started = _parse_time(saved.get("cleaning_started_at"))
        self.cleaning_started_at = (
            started if started and started <= _now()
            and self.robot_status in PARK_ACTIVE_STATES else None
        )
        cleaning_state = saved.get("cleaning_state")
        if isinstance(cleaning_state, str):
            self.cleaning_state = LEGACY_STATUS_LABELS.get(cleaning_state, cleaning_state)
            if self.cleaning_state not in STATUS_LABELS.values():
                self.cleaning_state = None
        # Upgrade old fallback labels (e.g. sleep -> Bereit), without treating
        # restored data as a fresh report or firing any completion side effects.
        if self.robot_status in STATUS_LABELS and self.robot_status != "standby":
            self.cleaning_state = STATUS_LABELS[self.robot_status]
        self.last_seen = _parse_time(saved.get("last_seen"))
        target = saved.get("charge_target")
        self.charge_target = target if target in (80, 100) else 100
        requested = _parse_time(saved.get("park_requested_at"))
        if saved.get("park_pending") and requested and _now() - requested < PARK_MAX_DURATION:
            self.park_pending = True
            self.park_state = "queued"
            self.park_requested_at = requested
        elif saved.get("park_pending"):
            self.park_state = "timed_out"

    def start(self) -> None:
        """Start once; a start during cleanup is deliberately ignored."""
        if (self._task and not self._task.done()) or (
            self._stop_task and not self._stop_task.done()
        ):
            return
        self._stopping = False
        self._stop_task = None
        self.client.clear_stop()
        if self._unsubscribe_stop is None:
            self._unsubscribe_stop = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._on_hass_stop
            )
        if self.charger_switch and self._unsubscribe_switch is None:
            self._unsubscribe_switch = async_track_state_change_event(
                self.hass, [self.charger_switch], self._on_switch_changed
            )
            if self.hass.states.is_state(self.charger_switch, "on"):
                if self.cooldown.state in {"cooling", "waiting_for_battery"}:
                    self.cooldown.manual()
                self.charge_started_at = _now()
                self.charge_state = "waiting_for_robot"
        self._task = self.entry.async_create_background_task(
            self.hass, self._run(), f"{DOMAIN} polling {self.entry.entry_id}"
        )

    async def _on_hass_stop(self, _event: Any) -> None:
        # HA has already removed this async_listen_once listener before dispatch.
        self._unsubscribe_stop = None
        await self.async_stop()

    async def async_stop(self) -> None:
        """Share cleanup; cancelling a caller never cancels or hides cleanup."""
        if self._stop_task is None:
            self._stopping = True
            self.client.request_stop()
            # Finite cleanup is tracked by HA, unlike the perpetual polling task.
            self._stop_task = self.hass.async_create_task(
                self._async_finish_stop(), f"{DOMAIN} stop {self.entry.entry_id}",
                eager_start=False,
            )
        await asyncio.shield(self._stop_task)

    async def _async_finish_stop(self) -> None:
        if self._unsubscribe_stop:
            self._unsubscribe_stop()
            self._unsubscribe_stop = None
        if self._unsubscribe_switch:
            self._unsubscribe_switch()
            self._unsubscribe_switch = None
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        # shield in _async_executor preserves the actual worker's completion.
        # Do not claim shutdown/unload is complete while its socket is still open.
        if self._executor_future is not None:
            await asyncio.gather(self._executor_future, return_exceptions=True)
            self._executor_future = None
        async with self._lock:
            await self.store.async_save(self._stored_data())

    async def _async_executor(self, function: Callable, *args: Any) -> Any:
        future = asyncio.ensure_future(self.hass.async_add_executor_job(function, *args))
        self._executor_future = future
        try:
            return await asyncio.shield(future)
        finally:
            if future.done():
                self._executor_future = None

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _stored_data(self) -> dict[str, Any]:
        return {
            "battery": self.battery,
            "battery_seen": self.battery_seen.isoformat() if self.battery_seen else None,
            "fault_code": self.fault_code,
            "fault_seen": self.fault_seen.isoformat() if self.fault_seen else None,
            "runtime": self.runtime.dump(),
            "completion": self.completion.dump(),
            "filter_cleaning_required": self.filter_cleaning_required,
            "completion_notifications": self.completion_notifications,
            "last_completion_at": self.last_completion_at.isoformat() if self.last_completion_at else None,
            "cooldown": self.cooldown.dump(),
            "cooldown_switch": self.charger_switch,
            "program_options": {"floor": self.floor_count, "wall": self.wall_count, "duration": self.multi_duration},
            "last_mode": self.last_mode,
            "last_program_key": self.last_program_key,
            "selected_mode": self.selected_mode,
            "mode_pending": self.mode_pending,
            "robot_status": self.robot_status,
            "cleaning_state": self.cleaning_state,
            "cleaning_started_at": self.cleaning_started_at.isoformat() if self.cleaning_started_at else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "charge_target": self.charge_target,
            "park_pending": self.park_pending,
            "park_requested_at": self.park_requested_at.isoformat() if self.park_requested_at else None,
        }

    def _save_soon(self) -> None:
        self.store.async_delay_save(self._stored_data, 2)

    @callback
    def _on_switch_changed(self, event: Any) -> None:
        if self._stopping:
            return
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if new is None:
            return
        if new.state in {"on", "off"} and old and old.state in {"on", "off"} and old.state != new.state:
            if not self._auto_charge_command and not (new.state == "off" and self.cutoff_requested_at):
                self.cooldown.manual()
            elif new.state == "off" and self.cutoff_requested_at:
                self.cooldown.state = "complete"
            self._save_soon()
        if new.state == "on" and (old is None or old.state != "on"):
            self.charge_started_at = _now()
            self.cutoff_requested_at = None
            self.charge_state = "waiting_for_robot"
        elif new.state == "off":
            self.charge_started_at = None
            self.charge_state = "limit_reached" if self.cutoff_requested_at else "plug_off"
        elif new.state in ("unavailable", "unknown"):
            self.charge_state = "switch_unavailable"
        self._notify()
        self._wake.set()

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                await self.async_poll()
                await self._check_cooldown()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Unexpected local poll failure")
            interval = (
                3 if self.park_pending
                else 5 if self.robot_status in PARK_ACTIVE_STATES or self.charge_started_at
                else 30
            )
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def async_poll(self) -> None:
        async with self._lock:
            if self._stopping:
                return
            now = _now()
            if self.park_pending and self.park_requested_at and now - self.park_requested_at >= PARK_MAX_DURATION:
                self.park_pending = False
                self.park_state = "timed_out"
                self._save_soon()
            park_due = (
                self.park_pending
                and not self.floor_only
                and self._park_delay_elapsed(now)
                and self.park_state != "accepted"
                and (not self.last_park_send_at or now - self.last_park_send_at >= PARK_RETRY_INTERVAL)
            )
            mode_to_set = self.selected_program if self.mode_pending and not self.park_pending else None
            try:
                result = await self._async_executor(self.client.poll, park_due, mode_to_set)
            except Exception as err:
                self.online = False
                if self._offline_since is None:
                    self._offline_since = now
                if self.inferred_off and self.filter_cleaning_required:
                    self.filter_cleaning_required = False
                    self._save_soon()
                self._failures += 1
                self._notify()
                _LOGGER.debug("AquaSense 2 LAN not reachable: %s", type(err).__name__)
                if self._failures >= 3 and (not self._last_discovery or now - self._last_discovery > timedelta(minutes=5)):
                    await self._rediscover()
                self._update_charge_state()
                return
            self._failures = 0
            self.online = True
            self._offline_since = None
            self.last_seen = now
            dps = result.dps
            if "107" in dps:
                fault = dps["107"]
                self.fault_code = fault if type(fault) is int and fault >= 0 else None
                self.fault_seen = now if self.fault_code is not None else None
            battery = dps.get("6")
            if type(battery) is int and 0 <= battery <= 100:
                self.battery = battery
                self.battery_seen = now
            state = status_name(dps)
            observed_program = Program.from_dps(dps)
            if observed_program:
                self.last_program_key = observed_program.key
                self._confirmed_program = observed_program
                self._confirmed_program_at = now.timestamp()
            learning_program = observed_program
            if self.runtime.active and observed_program is None:
                key = self.runtime.active["key"]
                if ("132" in dps or (key.startswith("Bereich:") and {"106", "114", "115"} & dps.keys())
                        or (key.startswith("MultiZone:") and "131" in dps)):
                    self.runtime.cancel_training("program_unconfirmed")
            if (learning_program is None and "132" not in dps and not self.mode_pending
                    and self.runtime.active is None and self.runtime.previous_state in READY
                    and self._confirmed_program_at is not None
                    and 0 <= now.timestamp() - self._confirmed_program_at <= MAX_EDGE_GAP):
                learning_program = self._confirmed_program
            position = dps.get("154")
            # Only a paired, fresh report proves readiness after pickup.
            # Saved state, absent fields and bool False are not dry readiness.
            dry_ready = state == "standby" and type(position) is int and position == 0
            if dry_ready or state in PARK_DONE_STATES | {"auto_dock", "sleep", "charging", "charge_done", "goto_charge"}:
                self.cleaning_started_at = None
            elif state in {"cleaning", "diving"} and self.cleaning_started_at is None:
                # Independent of runtime training: an unknown program or a
                # manually parked run must not invalidate the parking timer.
                self.cleaning_started_at = now
            fresh_battery = battery if type(battery) is int and 0 <= battery <= 100 else None
            self.runtime.observe(state, learning_program, now.timestamp(),
                                 self.park_pending, fresh_battery, position)
            completed = self.completion.observe(state, position, now.timestamp())
            # Charge planning may use the last stored battery even after power-off.
            # Charge cutoff below still requires a fresh post-switch-on reading.
            self.cooldown.observe(state, self.battery, now.timestamp(), completed, self.charge_target)
            if completed:
                self.last_completion_at = now
                self.filter_cleaning_required = True
            if "107" in dps and decode_filter_basket_missing(dps["107"]) is True:
                self.filter_cleaning_required = False
            if state:
                self.robot_status = state
                if state != "standby":
                    self.cleaning_state = STATUS_LABELS[state]
                elif dry_ready:
                    self.cleaning_state = "Bereit"
                elif self.runtime.active or self.completion.active:
                    pass  # Transient standby at the surface is not dry readiness.
                elif self.cleaning_state not in {
                    STATUS_LABELS["clean_done"], STATUS_LABELS["auto_dock"], STATUS_LABELS["dock"]
                }:
                    self.cleaning_state = "Bereit"
            if type(position) is int:
                self.position = position
            current_mode = decode_mode(dps.get("132"))
            if current_mode and not self.mode_pending:
                self.last_mode = self.selected_mode = current_mode
                if observed_program and current_mode == "Bereich":
                    self.floor_count, self.wall_count = observed_program.floor, observed_program.wall
                elif observed_program and current_mode == "MultiZone":
                    self.multi_duration = observed_program.duration
            if result.mode_confirmed and mode_to_set:
                self.last_mode = mode_to_set.mode
                self.last_program_key = mode_to_set.key
                self._confirmed_program = mode_to_set
                self._confirmed_program_at = now.timestamp()
                # An option can be changed while executor I/O is in progress.
                if self.selected_program == mode_to_set:
                    self.mode_pending = False
            if self.park_pending:
                if state in PARK_DONE_STATES or dry_ready:
                    self.park_pending = False
                    self.park_state = "completed"
                    self.park_requested_at = None
                    self.last_park_send_at = None
                elif state in PARK_ACCEPTED_STATES:
                    self.park_state = "accepted"
                elif result.park_sent:
                    self.last_park_send_at = now
                    self.park_state = "sent" if result.park_echo else "waiting_for_feedback"
                else:
                    self.park_state = "waiting_for_surface"
            self._save_soon()
            self._notify()
            if completed:
                # Persist deduplication before sending. A reload must not replay
                # a notification or restart an already running cooldown timer.
                await self.store.async_save(self._stored_data())
                await self._notify_completion()
            await self._check_charger(now, battery if type(battery) is int else None)

    @property
    def inferred_off(self) -> bool:
        return (not self.online and self._offline_since is not None
                and self.robot_status in OFFLINE_IDLE_STATES
                and _now() - self._offline_since >= OFFLINE_OFF_DELAY)

    @property
    def notify_service(self) -> str | None:
        return self.entry.options.get(CONF_NOTIFY_SERVICE)

    async def async_set_completion_notifications(self, enabled: bool) -> None:
        if enabled:
            try:
                domain, service, _ = completion_call(self.entry.options)
            except ValueError as err:
                raise HomeAssistantError("Bitte zuerst Smartphone oder Telegram mit Bot und Chat-ID konfigurieren") from err
            if not self.hass.services.has_service(domain, service):
                raise HomeAssistantError("Der konfigurierte Benachrichtigungsdienst ist nicht verfügbar")
        async with self._lock:
            if self._stopping:
                raise HomeAssistantError("Integration wird beendet")
            data = self._stored_data()
            data["completion_notifications"] = enabled
            await self.store.async_save(data)
            self.completion_notifications = enabled
            self._notify()

    async def _notify_completion(self) -> None:
        service = self.notify_service
        if not self.completion_notifications or not service:
            return
        try:
            domain, service, data = completion_call(self.entry.options)
            if domain == "telegram_bot" and service == "send_photo":
                photo = await self._async_executor(validate_photo, self.hass, data["file"])
                # Only our dedicated private image folder, never /config or www.
                self.hass.config.allowlist_external_dirs.add(str(Path(photo).parent))
                data["file"] = photo
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception:
            _LOGGER.warning("Fertigmeldung konnte nicht zugestellt werden")

    async def async_import_runtime_samples(self, samples: list[dict]) -> int:
        """Import only into this robot, serialized with polls; persist immediately."""
        async with self._lock:
            self._ensure_history_editable()
            # Do not leave a partial in-memory import if storage fails.
            learner = deepcopy(self.runtime)
            added = learner.import_samples(samples)
            await self._save_runtime(learner)
            return added

    def _ensure_history_editable(self) -> None:
        if (self._stopping or self.runtime.active is not None or self.completion.active
                or self.robot_status in PARK_ACTIVE_STATES):
            raise HomeAssistantError("Laufzeiten können nur außerhalb einer Reinigung bearbeitet oder importiert werden")

    async def _save_runtime(self, learner: RuntimeLearner) -> None:
        data = self._stored_data()
        data["runtime"] = learner.dump()
        await self.store.async_save(data)
        self.runtime = learner
        self._notify()

    async def async_restore_runtime_backup(self, data: dict) -> None:
        async with self._lock:
            self._ensure_history_editable()
            learner = deepcopy(self.runtime)
            for field in ("history", "battery_history", "manual_seconds", "imported_samples"):
                setattr(learner, field, deepcopy(data[field]))
            await self._save_runtime(learner)

    async def async_edit_runtime(self, key: str, samples: list[float], manual: float | None) -> None:
        if (key not in PROGRAMS or not isinstance(samples, list) or len(samples) > 10
                or any(type(v) not in (int, float) or not 60 <= v <= MAX_RUN for v in samples)
                or manual is not None and (type(manual) not in (int, float) or not 60 <= manual <= MAX_RUN)):
            raise ValueError("Ungültige Laufzeiten")
        async with self._lock:
            self._ensure_history_editable()
            learner = deepcopy(self.runtime)
            learner.history[key] = list(samples)
            if manual is None:
                learner.manual_seconds.pop(key, None)
            else:
                learner.manual_seconds[key] = float(manual)
            await self._save_runtime(learner)

    async def async_export_runtime(self) -> dict:
        async with self._lock:
            return export_runtime_file(self.runtime, self.entry.data[CONF_DEVICE_ID])

    @property
    def battery_stale(self) -> bool:
        return (not self.online or self.battery_seen is None
                or not 0 <= (_now() - self.battery_seen).total_seconds() <= MAX_EDGE_GAP)

    @property
    def fault_stale(self) -> bool:
        return (not self.online or self.fault_seen is None
                or not 0 <= (_now() - self.fault_seen).total_seconds() <= MAX_EDGE_GAP)

    @property
    def filter_basket_missing(self) -> bool | None:
        return decode_filter_basket_missing(self.fault_code)

    async def _rediscover(self) -> None:
        self._last_discovery = _now()
        try:
            found = await self._async_executor(discover, self.client.device_id, 6)
        except Exception:
            return
        if found:
            self.client.host = found[0]["host"]
            self.client.version = float(found[0]["version"])
            _LOGGER.debug("AquaSense 2 LAN address refreshed")

    def _update_charge_state(self) -> None:
        if self.charge_started_at and self.charger_switch:
            self.charge_state = "waiting_for_robot"
            self._notify()

    async def _check_charger(self, now: datetime, fresh_battery: int | None) -> None:
        switch = self.charger_switch
        if not switch:
            self.charge_state = "not_configured"
            return
        switch_state = self.hass.states.get(switch)
        if switch_state is None or switch_state.state in ("unknown", "unavailable"):
            self.charge_state = "switch_unavailable"
            self._notify()
            return
        if switch_state.state != "on":
            return
        if self.charge_started_at is None:
            self.charge_started_at = now
        if fresh_battery is None or now < self.charge_started_at:
            self.charge_state = "waiting_for_robot"
            self._notify()
            return
        if not charge_cutoff_due(True, fresh_battery, self.charge_target, self.charge_started_at, now):
            self.charge_state = "charging"
            self._notify()
            return
        if self.cutoff_requested_at and now - self.cutoff_requested_at < timedelta(seconds=30):
            return
        try:
            self.cutoff_requested_at = now
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
        except Exception:
            self.cutoff_requested_at = None
            self.charge_state = "switch_error"
            _LOGGER.exception("Could not turn off configured charging switch")
        else:
            self.cutoff_requested_at = now
            self.charge_state = (
                "limit_reached" if self.hass.states.is_state(switch, "off") else "cutoff_requested"
            )
        self._notify()

    @property
    def active_mode(self) -> str | None:
        """A queued preselection must not redefine the running cleaning mode."""
        return self.last_mode if self.mode_pending else self.selected_mode

    @property
    def can_park(self) -> bool:
        return (
            self.active_mode is not None
            and not self.floor_only
            and self._park_delay_elapsed(_now())
            and (self.robot_status in PARK_ACTIVE_STATES or self.park_pending)
        )

    def _park_delay_elapsed(self, now: datetime) -> bool:
        return (self.cleaning_started_at is not None
                and now - self.cleaning_started_at >= PARK_AVAILABLE_DELAY)

    @property
    def floor_only(self) -> bool:
        key = self.runtime.active["key"] if self.runtime.active else self.last_program_key
        return (key in FLOOR_ONLY_MODES or bool(key and key.startswith("Bereich:") and key.endswith("wall=0"))
                or (key is None and self.active_mode in FLOOR_ONLY_MODES))

    async def async_request_park(self) -> None:
        if not self.can_park:
            raise HomeAssistantError("Parking is unavailable for the selected mode or robot state")
        self.park_pending = True
        self.runtime.cancel_training("parking_excluded")
        self.park_state = "queued"
        self.park_requested_at = _now()
        self.last_park_send_at = None
        self._save_soon()
        self._notify()
        self._wake.set()

    async def async_set_charging(self, enabled: bool) -> None:
        """Manual requests cancel a pending automatic start, including while offline."""
        if not self.charger_switch:
            raise HomeAssistantError("No charging switch configured")
        async with self._charge_lock:
            self.cooldown.manual()
            self.cutoff_requested_at = None
            await self.store.async_save(self._stored_data())
            self._notify()
            await self.hass.services.async_call("switch", "turn_on" if enabled else "turn_off",
                                                {"entity_id": self.charger_switch}, blocking=True)
        self._wake.set()

    async def _check_cooldown(self) -> None:
        async with self._charge_lock:
            await self._start_cooled_charge()

    async def _start_cooled_charge(self) -> None:
        now = _now()
        if not self.charger_switch or not self.cooldown.due(now.timestamp()):
            return
        if self._charge_start_retry_at and now < self._charge_start_retry_at:
            return
        state = self.hass.states.get(self.charger_switch)
        if state is None or state.state not in {"on", "off"}:
            return  # Keep the deadline, never assume an unavailable plug is off.
        if state.state == "on":
            self.cooldown.manual()
            self._save_soon()
            self._notify()
            return
        self.cooldown.state = "starting"
        await self.store.async_save(self._stored_data())
        self._auto_charge_command = True
        try:
            await self.hass.services.async_call("switch", "turn_on", {"entity_id": self.charger_switch}, blocking=True)
        except Exception:
            self.cooldown.state = "cooling"
            self._charge_start_retry_at = now + timedelta(minutes=1)
            self.charge_state = "switch_error"
            _LOGGER.warning("Could not start the configured charging switch")
        else:
            self.cooldown.state = "charging" if self.hass.states.is_state(self.charger_switch, "on") else "start_uncertain"
            self.charge_started_at = now
            self.cutoff_requested_at = None
            self.charge_state = "waiting_for_robot"
        finally:
            self._auto_charge_command = False
            self._save_soon()
            self._notify()

    async def async_select_mode(self, mode: str) -> None:
        if mode not in MODE_VALUES:
            raise HomeAssistantError("Unsupported cleaning mode")
        if self.park_pending:
            raise HomeAssistantError("Cleaning mode cannot be changed while parking is pending")
        self.selected_mode = mode
        self.mode_pending = True
        self._save_soon()
        self._notify()
        self._wake.set()

    async def async_select_charge_target(self, value: int) -> None:
        if value not in (80, 100):
            raise HomeAssistantError("Unsupported charge target")
        self.charge_target = value
        self._save_soon()
        self._notify()
        self._wake.set()

    @property
    def selected_program(self) -> Program | None:
        if self.selected_mode is None:
            return None
        return Program(self.selected_mode, self.floor_count, self.wall_count, self.multi_duration)

    async def async_select_program_option(self, field: str, value: str) -> None:
        if self.park_pending:
            raise HomeAssistantError("Program cannot be changed while parking is pending")
        floor, wall, duration = self.floor_count, self.wall_count, self.multi_duration
        try:
            if field == "floor":
                floor = int(value)
            elif field == "wall":
                wall = int(value)
            elif field == "duration" and value in MULTI_DURATIONS:
                duration = value
            else:
                raise ValueError("Invalid option")
            Program("Bereich", floor, wall, duration)
        except ValueError as err:
            raise HomeAssistantError("Mindestens ein Bereich muss aktiv sein; erlaubt sind x0, x1, x2 bzw. Max, 2h, 1h") from err
        self.floor_count, self.wall_count, self.multi_duration = floor, wall, duration
        relevant = "MultiZone" if field == "duration" else "Bereich"
        if self.selected_mode == relevant:
            self.mode_pending = True
        self._save_soon()
        self._notify()
        self._wake.set()
