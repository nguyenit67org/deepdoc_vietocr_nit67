import json
import unittest
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "prediction_schema.json"
SAMPLE_PATH = REPO_ROOT / "docs" / "predict_schema_sample.json"

ELIGIBLE_FIELDS = [
    "type",
    "title",
    "code",
    "documentDate",
    "officeSender",
    "recipients",
    "signer",
    "priority_level",
    "security_level",
    "first_recipients",
    "signer_title",
    "province",
]


class TestStampAffectedMetadata(unittest.TestCase):
    def setUp(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
            self.sample = json.load(f)

    def test_schema_definition_exists(self):
        self.assertIn("stampAffectedFieldsField", self.schema.get("definitions", {}))
        def_obj = self.schema["definitions"]["stampAffectedFieldsField"]
        self.assertEqual(def_obj["type"], "object")
        self.assertIn("value", def_obj["properties"])
        val_prop = def_obj["properties"]["value"]
        self.assertEqual(val_prop["type"], "array")
        self.assertTrue(val_prop.get("uniqueItems", False))
        self.assertEqual(set(val_prop["items"]["enum"]), set(ELIGIBLE_FIELDS))
        self.assertNotIn("receiverDate", val_prop["items"]["enum"])

    def test_sample_is_valid_and_contains_metadata(self):
        jsonschema.validate(instance=self.sample, schema=self.schema)
        meta = self.sample.get("metadata", {})
        self.assertIn("stamp_affected_fields", meta)
        sof = meta["stamp_affected_fields"]
        self.assertEqual(sof.get("type"), "array")
        self.assertIsInstance(sof.get("value"), list)
        for f in sof["value"]:
            self.assertIn(f, ELIGIBLE_FIELDS)

    def test_backward_compatibility_without_key(self):
        sample_copy = json.loads(json.dumps(self.sample))
        sample_copy["metadata"].pop("stamp_affected_fields", None)
        # Should remain valid without the optional key
        jsonschema.validate(instance=sample_copy, schema=self.schema)

    def test_valid_empty_array(self):
        sample_copy = json.loads(json.dumps(self.sample))
        sample_copy["metadata"]["stamp_affected_fields"] = {
            "value": [],
            "type": "array",
        }
        jsonschema.validate(instance=sample_copy, schema=self.schema)

    def test_reject_ineligible_field(self):
        sample_copy = json.loads(json.dumps(self.sample))
        sample_copy["metadata"]["stamp_affected_fields"] = {
            "value": ["receiverDate"],
            "type": "array",
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=sample_copy, schema=self.schema)

    def test_reject_duplicate_fields(self):
        sample_copy = json.loads(json.dumps(self.sample))
        sample_copy["metadata"]["stamp_affected_fields"] = {
            "value": ["signer", "signer"],
            "type": "array",
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=sample_copy, schema=self.schema)

    def test_reject_non_array_value(self):
        sample_copy = json.loads(json.dumps(self.sample))
        sample_copy["metadata"]["stamp_affected_fields"] = {
            "value": "signer",
            "type": "array",
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=sample_copy, schema=self.schema)


if __name__ == "__main__":
    unittest.main()
