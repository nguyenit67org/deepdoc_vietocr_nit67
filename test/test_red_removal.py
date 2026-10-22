import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from module.pipeline.config import PipelineConfig
from module.pipeline.red_removal import masked_output, process_red_pages, remove_red_from_bgr
from module.pipeline.document_pipeline import DocumentPipeline, _PreparedPage
from module.pipeline.ocr_page import PageOcrPrep


def fake_ocr(text):
    def detect(image):
        h, w = image.shape[:2]
        return [[[2, 2], [w-2, 2], [w-2, h-2], [2, h-2]]]
    rec = Mock(side_effect=lambda crops: ([(text, 0.99) for _ in crops], 0.0))
    return SimpleNamespace(detect_sorted=Mock(side_effect=detect), drop_score=0.5,
                           get_rotate_crop_image=lambda image, box: image.copy(), text_recognizer=[rec])


class RedRemovalTests(unittest.TestCase):
    def setUp(self):
        self.cfg = PipelineConfig.from_conf({"remove_red": {"enabled": True, "max_probe_area_ratio": 0.5}})
        self.rgb = np.full((200, 200, 3), 255, np.uint8)
        self.rgb[60:100, 60:100] = [220, 30, 30]
        self.image = Image.fromarray(self.rgb)
        self.layout = [{"type": "seal", "bbox": [60, 60, 100, 100]}]

    def test_disabled_by_default(self):
        self.assertFalse(PipelineConfig.from_conf({}).remove_red_enabled)

    def test_masks_apply_after_all_color_writes(self):
        original = np.full((10, 10, 3), 50, np.uint8)
        keep = np.zeros((10, 10), bool)
        keep[4:6, 4:6] = True
        cleanup = np.zeros_like(keep)
        cleanup[2:8, 2:8] = True
        result = masked_output(original, np.full_like(original, 255), keep, cleanup)
        np.testing.assert_array_equal(result[keep | ~cleanup], original[keep | ~cleanup])
        self.assertTrue((result[cleanup & ~keep] == 255).all())
        self.assertTrue((original == 50).all())

    def test_no_red_no_extra_ocr(self):
        image = Image.new("RGB", (100, 100), "white")
        ocr = fake_ocr("unused")
        output, reports, _ = process_red_pages([image], [[]], ocr, self.cfg)
        self.assertIs(output[0], image)
        ocr.detect_sorted.assert_not_called()
        ocr.text_recognizer[0].assert_not_called()
        self.assertEqual(reports[0]["changed_pixels"], 0)

    def test_critical_names_and_uncertain_preserved(self):
        for text in ("HỎA TỐC", "TỐI MẬT", "GIÁM ĐỐC", "Nguyễn Văn An", "NGUYỄN VĂN AN", "", "illegible"):
            with self.subTest(text=text):
                output, reports, _ = process_red_pages([self.image], [self.layout], fake_ocr(text), self.cfg)
                np.testing.assert_array_equal(np.array(output[0]), self.rgb)
                self.assertEqual(reports[0]["changed_pixels"], 0)

    def test_org_seal_cleanup_and_source_unchanged(self):
        output, reports, _ = process_red_pages([self.image], [self.layout], fake_ocr("CÔNG TY ABC"), self.cfg)
        self.assertGreater(reports[0]["changed_pixels"], 0)
        np.testing.assert_array_equal(np.array(self.image), self.rgb)
        self.assertEqual(output[0].size, self.image.size)
        np.testing.assert_array_equal(np.array(output[0])[:40], self.rgb[:40])

    def test_limit_preserves_unprobed_regions(self):
        cfg = PipelineConfig.from_conf({"remove_red": {"max_regions_per_page": 0}})
        ocr = fake_ocr("CÔNG TY ABC")
        output, _, _ = process_red_pages([self.image], [self.layout], ocr, cfg)
        self.assertIs(output[0], self.image)
        ocr.text_recognizer[0].assert_not_called()

    def test_small_faint_red_outside_layout_is_probed(self):
        rgb = np.full((100, 100, 3), 255, np.uint8)
        rgb[40:42, 40:42] = [150, 139, 140]
        ocr = fake_ocr("HỎA TỐC")
        output, _, _ = process_red_pages([Image.fromarray(rgb)], [[]], ocr, self.cfg)
        ocr.detect_sorted.assert_called_once()
        np.testing.assert_array_equal(np.array(output[0]), rgb)

    def test_batch_owner_and_single_probe_recognition_call(self):
        ocr = fake_ocr("HỎA TỐC")
        _, reports, _ = process_red_pages([self.image, self.image], [self.layout, self.layout], ocr, self.cfg)
        ocr.text_recognizer[0].assert_called_once()
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(r["regions"][0]["lines"][0]["text"] == "HỎA TỐC" for r in reports))

    def test_v5_pixel_parity(self):
        # Load only the pure V5 definitions, never the standalone models/rules.
        path = Path(__file__).resolve().parents[1] / "ocr-public/src/full_remove_red.py"
        if not path.is_file():
            self.skipTest("Standalone V5 reference not available in this checkout")
        names = {"most_frequent_bgr_color", "_Analysis", "analyse", "clean_red", "recovery_boxes",
                 "apply_recovery", "find_red_regions", "remove_red_from_bgr"}
        tree = ast.parse(path.read_text())
        tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
        namespace = {"np": np, "cv2": cv2, "DEFAULT_RR_DENSE_THRESHOLD": 0.18,
                     "DEFAULT_RR_DARK_RED_MAX": 145, "DEFAULT_RR_MIN_BLACK_NEIGHBORS": 8}
        exec(compile(tree, str(path), "exec"), namespace)
        rng = np.random.default_rng(2)
        fixtures = [rng.integers(0, 256, (100, 100, 3), dtype=np.uint8), self.rgb[:, :, ::-1].copy()]
        fixtures[1][70:73, 55:110] = 20
        for img in fixtures:
            for neighbors in (0, 8):
                np.testing.assert_array_equal(remove_red_from_bgr(img, min_black_neighbors=neighbors),
                                              namespace["remove_red_from_bgr"](img, min_black_neighbors=neighbors))

    def test_pipeline_cache_invalidation_and_disabled_path(self):
        for enabled, changed in ((False, 0), (True, 0), (True, 12)):
            with self.subTest(enabled=enabled, changed=changed):
                cfg = PipelineConfig.from_conf({"crop_whitespace": {"enabled": False},
                                                "remove_red": {"enabled": enabled}})
                layout = SimpleNamespace(detect_batch=Mock(return_value=[[]]),
                                         label_schema=SimpleNamespace(table_types=frozenset({"table"})))
                pipeline = DocumentPipeline(layout, fake_ocr("unused"), None, cfg)
                old_boxes, old_rec = [], {0: ("original", 0.9)}
                state = _PreparedPage(self.image, old_boxes, old_rec)
                mask = np.zeros(self.rgb.shape[:2], bool)
                new_image = self.image.copy() if changed else self.image
                report = {"changed_pixels": changed, "seconds": 0.01, "regions": []}
                module = "module.pipeline.document_pipeline."
                with patch.object(pipeline, "_prepare_page_orientation", return_value=state), \
                     patch.object(pipeline, "_build_table_skeleton", return_value=([], [])), \
                     patch.object(pipeline, "_process_page_after_layout", return_value=[]), \
                     patch(module + "process_red_pages", return_value=([new_image], [report], [(mask, mask)])) as red, \
                     patch(module + "prepare_ocr_page", return_value=(PageOcrPrep(None), [])) as prep:
                    _, _, images = pipeline._process_page_chunk([self.image], None)
                self.assertEqual(red.call_count, int(enabled))
                expected_boxes = None if enabled and changed else old_boxes
                expected_rec = None if enabled and changed else old_rec
                self.assertIs(prep.call_args.kwargs["dt_boxes"], expected_boxes)
                self.assertIs(prep.call_args.kwargs["prerecognized"], expected_rec)
                self.assertIs(images[0], new_image if enabled else self.image)


if __name__ == "__main__":
    unittest.main()
