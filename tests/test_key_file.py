"""Credential import validation and export isolation, using dummy keys only."""

import base64
import importlib
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import test_runtime  # Bootstrap without importing Home Assistant.

key_file = importlib.import_module("custom_components.beatbot_aquasense2_local.key_file")
spec = importlib.util.spec_from_file_location("beatbot_key_export", Path(__file__).resolve().parents[1] / "tools" / "export_beatbot_key.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

DEVICE = "testrobot12345678"
KEY = "0123456789abcdef"


class KeyFileTests(unittest.TestCase):
    def setUp(self):
        self.content = export.key_document(DEVICE, KEY)

    def test_export_import_roundtrip(self):
        credentials = key_file.parse_key_file(self.content)
        self.assertEqual(credentials.device_id, DEVICE)
        self.assertEqual(credentials.local_key, KEY)
        self.assertNotIn(KEY, repr(credentials))

    def test_rejects_wrong_model_version_and_key(self):
        for field, value in [("format_version", 2), ("format_version", True), ("product_id", "other"),
                             ("local_key", "short"), ("protocol_version", "3.5"), ("device_id", "../file")]:
            with self.subTest(field=field):
                data = json.loads(self.content)
                data[field] = value
                with self.assertRaises(key_file.InvalidKeyFile):
                    key_file.parse_key_file(json.dumps(data).encode())

    def test_rejects_oversize_duplicates_malformed_without_disclosing_key(self):
        for content in [self.content + b" " * 16384, self.content[:-2], b"[]",
                        self.content.replace(b'"format_version": 1', b'"format_version": 1, "format_version": 1')]:
            with self.assertRaises(key_file.InvalidKeyFile) as error:
                key_file.parse_key_file(content)
            self.assertNotIn(KEY, str(error.exception))

    def test_validates_host_without_rewriting_secret(self):
        data = json.loads(self.content)
        data["local_key"] = " " + "a" * 13 + " "  # Fifteen characters must fail.
        with self.assertRaises(key_file.InvalidKeyFile):
            key_file.parse_key_file(json.dumps(data).encode())
        data["local_key"] = " " + "a" * 14 + " "
        data["host"] = "192.168.1.2"
        self.assertEqual(key_file.parse_key_file(json.dumps(data).encode()).local_key, data["local_key"])
        for host in ("8.8.8.8", "127.0.0.1", "0.0.0.0", "example.com"):
            data["host"] = host
            with self.assertRaises(key_file.InvalidKeyFile):
                key_file.parse_key_file(json.dumps(data).encode())

    def test_extracts_only_requested_robot_and_rejects_ambiguity(self):
        logs = 'prefix ' + json.dumps({"devId": "otherrobot", "localKey": "fedcba9876543210"}) + '\n'
        logs += 'prefix ' + json.dumps({"devId": DEVICE, "localKey": KEY})
        self.assertEqual(export.key_from_logs(logs, DEVICE), KEY)
        logs += '\n' + json.dumps({"devId": DEVICE, "localKey": "fedcba9876543210"})
        with self.assertRaises(ValueError):
            export.key_from_logs(logs, DEVICE)

    def test_existing_ha_entry_lookup_matches_domain_and_robot(self):
        data = {"data": {"entries": [
            {"domain": "unrelated", "data": {"device_id": DEVICE, "local_key": "fedcba9876543210"}},
            {"domain": export.DOMAIN, "data": {"device_id": DEVICE, "local_key": KEY}},
        ]}}
        self.assertEqual(export.key_from_ha(data, DEVICE), KEY)

    def test_keepass_includes_importable_attachment_and_escapes_values(self):
        key = '<>&"' + 'a' * 12
        xml = ET.fromstring(export.keepass_document(DEVICE, key, "Robot & pool", "robot.beatbot-key.json"))
        entry = xml.find("./Root/Group/Entry")
        fields = {node.findtext("Key"): node.findtext("Value") for node in entry.findall("String")}
        self.assertEqual(fields["Password"], key)
        content = base64.b64decode(entry.findtext("Binary/Value"))
        self.assertEqual(key_file.parse_key_file(content).local_key, key)

    def test_refuses_export_into_repository(self):
        with self.assertRaises(ValueError):
            export.validate_destination(Path(__file__).resolve().parents[1] / "dummy.beatbot-key.json", ".beatbot-key.json")
