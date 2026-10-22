"""CPU-only contracts for the hybrid diagnostic harness."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import cv2
from PIL import Image

from scripts import check_cached_ocr_equivalence as h
from module.pipeline.ocr_page import prepare_ocr_page, finish_ocr_page


class CachedOcrEquivalenceTests(unittest.TestCase):
    def test_physical_selection_union_and_validation(self):
        meta = {"document_start_page": {"value": 0}, "document_end_pages": {"value": [13, 14]}}
        self.assertEqual(h.selected_pages(meta, 15), [0, 13, 14])
        meta["document_end_pages"]["value"] = [0]
        self.assertEqual(h.selected_pages(meta, 1), [0])
        for ends in ([], [True], [-1], [15], [1.0]):
            meta["document_end_pages"]["value"] = ends
            with self.assertRaises(ValueError):
                h.selected_pages(meta, 15)

    def test_snapshot_drift_rejected_before_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "source_snapshot").mkdir(parents=True)
            (source / "pipeline_config.json").write_text(json.dumps({"table": {"enabled": False}}))
            (root / "a.py").write_text("original")
            (source / "source_snapshot/a.py").write_text("original")
            with patch.object(h, "ROOT", root):
                self.assertIn("a.py", h.validate_source(source)[1])
                (root / "a.py").write_text("modified")
                with self.assertRaisesRegex(ValueError, "differs.*a.py"):
                    h.validate_source(source)

    def test_diagnostic_does_not_claim_source_evidence_or_resources(self):
        r = h.diagnostic_record({"trace_path": "old/trace.json", "peak_vram_mb": 123},
                                {"title": "new"}, {"title": []}, Path("new/diagnostic.json"))
        self.assertIsNone(r["trace_path"])
        self.assertIsNone(r["peak_vram_mb"])
        self.assertEqual(r["source_trace_path"], "old/trace.json")
        self.assertEqual(r["prediction"]["title"], "new")

    def test_prepare_preserves_detection_indices_and_bgr_crops(self):
        quads = np.array([[[0, 0], [20, 0], [20, 10], [0, 10]],
                          [[30, 0], [50, 0], [50, 10], [30, 10]],
                          [[60, 0], [80, 0], [80, 10], [60, 10]]], dtype=float)
        crop = Mock(side_effect=lambda image, box: image.copy())
        ocr = SimpleNamespace(detect_sorted=Mock(return_value=quads),
                              get_rotate_crop_image=crop, drop_score=0.5)
        prep, crops = prepare_ocr_page(Image.new("RGB", (100, 20), (255, 0, 0)), ocr,
                                      excluded_regions=[[30, 0, 50, 10]])
        self.assertEqual(prep.crop_indices, [0, 2])
        self.assertEqual(prep.excluded_indices, {1})
        self.assertEqual(len(crops), 2)
        self.assertEqual(crops[0][0, 0].tolist(), [0, 0, 255])
        lines = finish_ocr_page(prep, [("first", 1), ("last", 1)], ocr)
        self.assertEqual([line["text"] for line in lines], ["first", "last"])
        self.assertEqual(lines[-1]["quad"], quads[-1].tolist())
        self.assertIn("bbox_row", lines[0])

    def test_raw_change_is_not_hidden_by_equal_metric(self):
        record = dict(document_id="synthetic", page_count=1,
                      ground_truth={"title": "Văn bản"}, prediction={"title": "Văn bản"})
        report = h.compare([record], [{**record, "prediction": {"title": "VĂN BẢN"}}])
        self.assertEqual(report["exact_prediction_documents"], 0)
        self.assertEqual(len(report["raw_prediction_changes"]), 1)
        self.assertEqual(report["regressions"], [])
        title_metric = next(m for m in report["metrics"] if m["field"] == "title")
        self.assertEqual(title_metric["f1_delta"], 0)
        self.assertEqual(report["document_success_rate_delta"], 0)
        self.assertEqual(len(report["bucket_transitions"]), 4 * 6 * 6)
        self.assertEqual(sum(t["count"] for t in report["bucket_transitions"] if t["split"] == "all"), 12)

    def test_retained_line_comparison_keeps_duplicate_quads(self):
        line = dict(text="a", quad=[[0, 0], [1, 0], [1, 1], [0, 1]])
        report = h.line_comparison([line, line], [line, {**line, "text": "b"}])
        self.assertEqual(report["common_rounded_quads"], 2)
        self.assertEqual(report["common_quad_text_pairs"], 1)
        self.assertFalse(report["ordered_quad_text_equal"])

    def test_mismatched_document_sets_rejected(self):
        record = dict(document_id="a", page_count=1, ground_truth={}, prediction={})
        with self.assertRaisesRegex(ValueError, "identical document sets"):
            h.compare([record], [{**record, "document_id": "b"}])

    def make_page_cache(self, root):
        (root / "crops").mkdir()
        crop = np.zeros((3, 5, 3), dtype=np.uint8)
        crop[:] = [3, 17, 245]
        cv2.imwrite(str(root / "crops/1.png"), crop)
        data = dict(page_index_0based=44, detection_quads=[[[0, 0], [5, 0], [5, 3], [0, 3]]] * 2,
                    crop_indices=[1], excluded_indices=[0])
        h.dump(root / "input.json", data)
        h.dump(root / "crop_manifest.json", [dict(detection_index=1, path="crops/1.png",
            sha256=h.sha256(root / "crops/1.png"), shape_bgr=list(crop.shape),
            array_sha256=h.hashlib.sha256(crop.tobytes()).hexdigest())])
        return crop

    def test_load_cache_preserves_exact_bgr_and_mapping_without_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = self.make_page_cache(root)
            with patch("module.ocr.engine.OCR.detect_sorted", side_effect=AssertionError("must not detect")), \
                 patch.object(h, "sha256", wraps=h.sha256):
                prep, crops, _ = h.load_cached_page(root, {"page_index_0based": 44})
            self.assertEqual(prep.crop_indices, [1])
            self.assertEqual(prep.excluded_indices, {0})
            np.testing.assert_array_equal(crops[0], expected)
            lines = finish_ocr_page(prep, [("cached", 1)], SimpleNamespace(drop_score=0.5))
            self.assertEqual([line["text"] for line in lines], ["cached"])

    def test_load_cache_rejects_corruption_wrong_identity_and_index_mapping(self):
        for corruption in ("identity", "file", "array", "order", "partition", "path"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.make_page_cache(root)
                expected = {"page_index_0based": 44}
                data = json.loads((root / "input.json").read_text())
                entries = json.loads((root / "crop_manifest.json").read_text())
                if corruption == "identity":
                    expected["page_index_0based"] = 0
                elif corruption == "file":
                    (root / "crops/1.png").write_bytes(b"corrupt")
                elif corruption == "array":
                    entries[0]["array_sha256"] = "wrong"
                elif corruption == "order":
                    entries[0]["detection_index"] = 0
                elif corruption == "partition":
                    data["excluded_indices"] = [1]
                elif corruption == "path":
                    entries[0]["path"] = "../outside.png"
                h.dump(root / "input.json", data)
                h.dump(root / "crop_manifest.json", entries)
                with self.assertRaises(ValueError):
                    h.load_cached_page(root, expected)


if __name__ == "__main__":
    unittest.main()
