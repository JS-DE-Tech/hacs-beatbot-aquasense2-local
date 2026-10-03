"""Export one robot's credentials from authorized ADB logs or existing HA config.

Only Python's standard library is required. Secrets are never printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

DOMAIN = "beatbot_aquasense2_local"
PRODUCT_ID = "c64wbaic8jnkqgix"


def key_from_logs(logs: str, device_id: str) -> str:
    decoder = json.JSONDecoder()
    keys = set()
    for line in logs.splitlines():
        if "localKey" not in line or device_id not in line:
            continue
        for match in re.finditer(r"\{", line):
            try:
                data, _ = decoder.raw_decode(line[match.start():])
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("devId") == device_id:
                key = data.get("localKey")
                if isinstance(key, str) and len(key) == 16:
                    keys.add(key)
    if len(keys) != 1:
        raise ValueError("No unique local key")
    return keys.pop()


def key_from_ha(data: dict, device_id: str) -> str:
    entries = data.get("data", {}).get("entries", [])
    keys = {entry["data"].get("local_key") for entry in entries
            if entry.get("domain") == DOMAIN and entry.get("data", {}).get("device_id") == device_id}
    if len(keys) != 1 or not isinstance(next(iter(keys)), str):
        raise ValueError("No unique configured local key")
    return keys.pop()


def key_document(device_id: str, key: str) -> bytes:
    if not re.fullmatch(r"[a-zA-Z0-9]{8,64}", device_id) or len(key) != 16 or not all(32 <= ord(c) <= 126 for c in key):
        raise ValueError("Invalid credentials")
    payload = {"format": "beatbot_aquasense2_local_key", "format_version": 1,
               "product_id": PRODUCT_ID, "device_id": device_id,
               "local_key": key, "protocol_version": "3.3"}
    return (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def keepass_document(device_id: str, key: str, title: str, attachment_name: str) -> bytes:
    root = ET.Element("KeePassFile")
    meta = ET.SubElement(root, "Meta")
    ET.SubElement(meta, "Generator").text = "Beatbot AquaSense 2 Local"
    group = ET.SubElement(ET.SubElement(root, "Root"), "Group")
    ET.SubElement(group, "UUID").text = base64.b64encode(uuid.uuid4().bytes).decode("ascii")
    ET.SubElement(group, "Name").text = "Beatbot"
    entry = ET.SubElement(group, "Entry")
    ET.SubElement(entry, "UUID").text = base64.b64encode(uuid.uuid4().bytes).decode("ascii")
    fields = {"Title": title, "UserName": device_id, "Password": key, "URL": "",
              "Notes": "Beatbot AquaSense 2 – lokaler Tuya-Schlüssel (kein Kontopasswort).\n"
                       "Protokoll: 3.3. Die angehängte JSON-Datei kann in Beatbot AquaSense 2 Local importiert werden.\n"
                       "Erneutes Koppeln kann den Schlüssel ändern."}
    for name, value in fields.items():
        string = ET.SubElement(entry, "String")
        ET.SubElement(string, "Key").text = name
        ET.SubElement(string, "Value").text = value
    binary = ET.SubElement(entry, "Binary")
    ET.SubElement(binary, "Key").text = attachment_name
    ET.SubElement(binary, "Value").text = base64.b64encode(key_document(device_id, key)).decode("ascii")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_destination(output: Path, suffix: str) -> Path:
    output = output.resolve()
    if any((parent / ".git").exists() for parent in output.parents):
        raise ValueError("Destination is in a Git repository")
    if not output.name.endswith(suffix) or output.exists():
        raise ValueError("Invalid or existing destination")
    return output


def write_private_file(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--adb", help="Pfad zu adb; liest die aktuellen App-Meldungen")
    source.add_argument("--ha-config", type=Path, help="Lokale .storage/core.config_entries einer eingerichteten Integration")
    parser.add_argument("--serial", help="ADB-Gerätekennung, z. B. 127.0.0.1:5555")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--output", required=True, type=Path, help="Ziel außerhalb von Git, Endung .beatbot-key.json")
    parser.add_argument("--keepass", type=Path, help="Zusätzlicher KeePass XML (2.x) Import mit JSON-Anhang")
    parser.add_argument("--title", default="Beatbot AquaSense 2 – lokaler Schlüssel")
    args = parser.parse_args()
    try:
        output = validate_destination(args.output, ".beatbot-key.json")
        keepass = validate_destination(args.keepass, ".xml") if args.keepass else None
        if args.adb:
            command = [args.adb]
            if args.serial:
                command.extend(["-s", args.serial])
            result = subprocess.run(command + ["logcat", "-d", "-t", "100000"], capture_output=True, timeout=30)
            if result.returncode:
                raise ValueError("ADB failed")
            key = key_from_logs(result.stdout.decode("utf-8", "replace"), args.device_id)
        else:
            with args.ha_config.open(encoding="utf-8") as source_file:
                key = key_from_ha(json.load(source_file), args.device_id)
        content = key_document(args.device_id, key)
        xml = keepass_document(args.device_id, key, args.title, output.name) if keepass else None
        write_private_file(output, content)
        print(f"Private HA-Schlüsseldatei erstellt: {output}")
        if keepass:
            write_private_file(keepass, xml)
            print(f"KeePass-Importdatei erstellt: {keepass}")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        print("Export fehlgeschlagen. Quelle, Geräte-ID und neues Ziel außerhalb von Git prüfen; bei ADB die angemeldete Beatbot-App erneut öffnen. Kein Schlüssel ausgegeben.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
