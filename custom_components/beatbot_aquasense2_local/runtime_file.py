"""Bounded, non-secret imports of explicitly confirmed per-robot run samples."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .runtime import MAX_RUN, Program, PROGRAMS

MAX_FILE_BYTES = 128 * 1024


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def parse_runtime_file(data: bytes, device_id: str) -> list[dict] | dict:
    """Validate the entire file before touching the manager or storage."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Runtime file too large")
    try:
        payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError, RecursionError) as err:
        raise ValueError("Invalid JSON") from err
    if not isinstance(payload, dict) or payload.get("device_id") != device_id:
        raise ValueError("Wrong format or robot")
    if payload.get("format") == "beatbot-history-v2":
        return _parse_backup(payload)
    if payload.get("format") != "beatbot-runtime-v1":
        raise ValueError("Wrong format")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 100:
        raise ValueError("Invalid samples")
    result = []
    seen = set()
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("confirmed") is not True:
            raise ValueError("Only explicitly confirmed samples may be imported")
        sample_id = sample.get("id")
        if not isinstance(sample_id, str) or not 1 <= len(sample_id) <= 128 or sample_id in seen:
            raise ValueError("Invalid or duplicate sample ID")
        seen.add(sample_id)
        values = sample.get("program")
        if not isinstance(values, dict) or set(values) - {"mode", "floor", "wall", "duration"}:
            raise ValueError("Invalid program")
        try:
            program = Program(**values)
        except (TypeError, ValueError) as err:
            raise ValueError("Invalid program") from err
        # Combinations must be explicit, never silently assume missing options.
        if ((program.mode == "Bereich" and not {"floor", "wall"} <= values.keys())
                or (program.mode == "MultiZone" and "duration" not in values)):
            raise ValueError("Missing program options")
        duration = sample.get("duration_seconds")
        if type(duration) not in (int, float) or not 60 <= duration <= MAX_RUN:
            raise ValueError("Invalid duration")
        start, end = sample.get("start_battery"), sample.get("end_battery")
        used = None
        if start is not None or end is not None:
            if not (type(start) is int and type(end) is int and 0 <= end <= start <= 100):
                raise ValueError("Invalid battery endpoints")
            used = start - end
        fingerprint = hashlib.sha256(json.dumps([program.key, float(duration), used]).encode()).hexdigest()
        result.append({"id": sample_id, "key": program.key, "duration_seconds": float(duration),
                       "battery_used": used, "fingerprint": fingerprint})
    return result


def read_runtime_file(path: Path, device_id: str) -> list[dict] | dict:
    with path.open("rb") as stream:
        return parse_runtime_file(stream.read(MAX_FILE_BYTES + 1), device_id)


def _parse_backup(payload: dict) -> dict:
    programs = payload.get("programs")
    if not isinstance(programs, list) or len(programs) != len(PROGRAMS):
        raise ValueError("Backup must contain all program combinations")
    result = {"history": {}, "battery_history": {}, "manual_seconds": {}, "imported_samples": {}}
    seen = set()
    for row in programs:
        if not isinstance(row, dict) or not isinstance(row.get("program"), dict):
            raise ValueError("Invalid program")
        try:
            program = Program(**row["program"])
        except (TypeError, ValueError) as err:
            raise ValueError("Invalid program") from err
        if asdict(program) != row["program"] or program.key in seen:
            raise ValueError("Incomplete or duplicate program")
        seen.add(program.key)
        for field, destination, minimum, maximum in (
            ("duration_seconds", "history", 60, MAX_RUN), ("battery_used", "battery_history", 0, 100)
        ):
            samples = row.get(field)
            if not isinstance(samples, list) or len(samples) > 10 or any(
                type(v) not in (int, float) or not minimum <= v <= maximum for v in samples
            ):
                raise ValueError("Invalid samples")
            if destination == "battery_history" and any(type(v) is not int for v in samples):
                raise ValueError("Invalid battery samples")
            if samples:
                result[destination][program.key] = list(samples)
        manual = row.get("manual_seconds")
        if manual is not None:
            if type(manual) not in (int, float) or not 60 <= manual <= MAX_RUN:
                raise ValueError("Invalid manual estimate")
            result["manual_seconds"][program.key] = float(manual)
    if seen != set(PROGRAMS):
        raise ValueError("Missing combinations")
    imported = payload.get("imported_samples", {})
    if not isinstance(imported, dict) or len(imported) > 1000:
        raise ValueError("Invalid deduplication data")
    for key, value in imported.items():
        if (not isinstance(key, str) or not 1 <= len(key) <= 128 or not isinstance(value, str)
                or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("Invalid sample fingerprint")
    result["imported_samples"] = dict(imported)
    return result


def export_runtime_file(learner, device_id: str) -> dict:
    payload = {"format": "beatbot-history-v2", "device_id": device_id,
               "programs": [{"program": asdict(program),
                             "duration_seconds": list(learner.history.get(key, [])),
                             "battery_used": list(learner.battery_history.get(key, [])),
                             "manual_seconds": learner.manual_seconds.get(key)}
                            for key, program in PROGRAMS.items()],
               "imported_samples": dict(learner.imported_samples)}
    # Exported files must satisfy the same bounds and schema as imports.
    parse_runtime_file(json.dumps(payload).encode(), device_id)
    return payload
