"""Report scope and discovery guards, without inference or benchmark rescoring."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import report_all_tested_recognizers as report


class AllRecognizerReportTests(unittest.TestCase):
    def test_csv_false_is_not_truthy_string(self):
        self.assertFalse(report.csv_bool("False"))
        self.assertFalse(report.csv_bool("0"))
        self.assertTrue(report.csv_bool("True"))
        with self.assertRaises(ValueError):
            report.csv_bool("unknown")

    def test_unknown_annotations_are_not_printed_negatives(self):
        self.assertFalse(report.in_scope({}, "code", "field_handwritten"))
        self.assertFalse(report.in_scope({}, "code", "field_not_handwritten"))
        self.assertTrue(report.in_scope({}, "code", "all"))

    def test_handwritten_and_stamp_are_field_specific(self):
        metadata = {"handwritten_fields": {"value": ["code"]}, "stamp_affected_fields": {"value": ["code", "documentDate"]}}
        self.assertTrue(report.in_scope(metadata, "code", "handwritten_and_stamp"))
        self.assertFalse(report.in_scope(metadata, "documentDate", "handwritten_and_stamp"))
        self.assertTrue(report.in_scope(metadata, "documentDate", "field_not_handwritten"))

    def test_missing_stamp_annotation_is_not_a_negative(self):
        metadata = {"handwritten_fields": ["code"]}
        self.assertTrue(report.in_scope(metadata, "code", "field_handwritten"))
        self.assertFalse(report.in_scope(metadata, "code", "handwritten_without_stamp"))

    def test_discovery_rejects_smoke_and_preserves_protocol(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            for name, count in (("pytesseract_psm6", 100), ("trocr_smoke", 5)):
                folder = root / "pytesseract_selected_pages_20261020" / name
                folder.mkdir(parents=True)
                (folder / "recognizer_config.json").write_text(json.dumps({"backend": "pytesseract_direct"}))
                (folder / "manifest.json").write_text(json.dumps({"status": "completed", "documents": list(range(count))}))
                (folder / "predictions.jsonl").write_text("")
            with patch.object(report, "ARTIFACTS", root):
                runs, excluded = report.discover()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["protocol"], "selected_pages_only")
            self.assertEqual(len(excluded), 1)
