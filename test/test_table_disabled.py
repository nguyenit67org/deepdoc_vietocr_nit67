import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.layout.pp_doclayout import PPDocLayoutBackend
from module.pipeline.config import PipelineConfig
from module.pipeline.content import build_json, build_markdown
from module.pipeline.document_pipeline import DocumentPipeline, build_pipeline
from module.pipeline.ocr_page import finish_ocr_page, prepare_ocr_page


def quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class TableDisabledTests(unittest.TestCase):
    def test_factory_defaults_enabled_and_skips_initialization_when_disabled(self):
        for table_conf, enabled in [({}, True), ({"enabled": True}, True), ({"enabled": False}, False)]:
            with (
                self.subTest(table_conf=table_conf),
                patch("module.pipeline.document_pipeline.get_layout_backend"),
                patch("module.pipeline.document_pipeline.get_ocr_engine"),
                patch("module.pipeline.document_pipeline.get_corrector_backend"),
                patch("module.pipeline.document_pipeline.get_table_processor") as factory,
            ):
                pipeline = build_pipeline({"table": table_conf})
                self.assertEqual(pipeline.config.table_enabled, enabled)
                if enabled:
                    factory.assert_called_once()
                    self.assertIs(pipeline.table_processor, factory.return_value)
                else:
                    factory.assert_not_called()
                    self.assertIsNone(pipeline.table_processor)

    def test_exclusion_preserves_indices_and_discards_orientation_samples(self):
        image = Image.new("RGB", (100, 100), "white")
        boxes = np.array([
            quad(0, 0, 10, 10), quad(0, 20, 10, 30),
            quad(0, 40, 10, 50), quad(0, 60, 10, 70),
        ], dtype=float)
        ocr = Mock(drop_score=0.5)
        prep, crops = prepare_ocr_page(
            image, ocr, dt_boxes=boxes,
            prerecognized={0: ("body sample", 1.0), 1: ("table sample", 1.0)},
            excluded_regions=[[0, 20, 10, 50]],
        )
        self.assertEqual(prep.excluded_indices, {1, 2})
        self.assertEqual(prep.crop_indices, [3])
        self.assertEqual(len(crops), 1)
        ocr.detect_sorted.assert_not_called()
        result = finish_ocr_page(prep, [("body fresh", 1.0)], ocr)
        self.assertEqual([b["text"] for b in result], ["body sample", "body fresh"])
        self.assertEqual(result[1]["bbox"], [0, 60, 10, 70])

    def test_overlap_boundary_and_all_excluded(self):
        boxes = np.array([quad(0, 0, 10, 10)], dtype=float)
        ocr = Mock(drop_score=0.5)
        for edge, excluded in [(5, False), (6, True)]:
            with self.subTest(edge=edge):
                prep, crops = prepare_ocr_page(
                    Image.new("RGB", (20, 20)), ocr, dt_boxes=boxes,
                    excluded_regions=[[0, 0, edge, 10]],
                )
                self.assertEqual(len(crops), 0 if excluded else 1)
                result = finish_ocr_page(prep, [] if excluded else [("text", 1.0)], ocr)
                self.assertEqual(len(result), 0 if excluded else 1)

    def test_document_flow_enabled_and_disabled(self):
        image = Image.new("RGB", (200, 300), "white")
        raw_blocks = [{"type": "table", "bbox": [0, 50, 150, 150], "score": 0.9}]
        boxes = np.array([quad(10, 10, 100, 20), quad(10, 70, 100, 80)], dtype=float)
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                layout = Mock(label_schema=PPDocLayoutBackend.label_schema)
                layout.detect_batch.return_value = [raw_blocks]
                ocr = Mock(drop_score=0.5)
                ocr.detect_sorted.return_value = boxes
                ocr.get_rotate_crop_image.return_value = np.zeros((10, 90, 3), dtype=np.uint8)
                recognizer = Mock(return_value=(
                    [("body", 1.0), ("table text", 1.0)] if enabled else [("body", 1.0)], 0.0
                ))
                ocr.text_recognizer = [recognizer]
                table = Mock(spec=["__call__"], return_value="| cell |")
                config = PipelineConfig.from_conf({
                    "table": {"enabled": enabled}, "crop_whitespace": {"enabled": False},
                })
                pipeline = DocumentPipeline(layout, ocr, table, config)
                with patch("module.pipeline.document_pipeline.deskew_crop", return_value=(image, 0)) as deskew:
                    pages, offsets, _ = pipeline._process_pages_batch([image], None)
                self.assertEqual(len(recognizer.call_args.args[0]), 2 if enabled else 1)
                table_block = next(b for b in pages[0] if b["type"] == "table")
                self.assertEqual(table_block["content_type"], "table" if enabled else "skip")
                self.assertEqual(table_block["content"], "| cell |" if enabled else None)
                if enabled:
                    table.assert_called_once()
                    deskew.assert_called_once()
                else:
                    table.assert_not_called()
                    deskew.assert_not_called()
                    self.assertEqual(build_markdown(pages, layout.label_schema), "<!-- Page 1 -->\n\nbody")
                    output = build_json("test", pages, offsets)
                    self.assertEqual(len(output["pages"][0]["blocks"]), 2)


if __name__ == "__main__":
    unittest.main()
