import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from module.layout.base import LayoutLabelSchema
from module.pipeline.config import PipelineConfig
from module.pipeline.debug import PipelineDebugTrace, build_structured_debug
from module.pipeline.document_pipeline import DocumentPipeline
from server.schemas import VBHCPredictionResponse


FIELDS = (
    "type", "title", "code", "documentDate", "officeSender", "recipients",
    "signer", "priority_level", "security_level", "first_recipients",
    "signer_title", "province", "receiverDate",
)


def prediction():
    values = {field: "" for field in FIELDS}
    values.update({
        "type": "Công văn",
        "title": "V/v thử nghiệm",
        "priority_level": "0_BÌNH THƯỜNG",
        "security_level": "0_BÌNH THƯỜNG",
    })
    return {
        "information": [{field: {"value": values[field], "type": "string"} for field in FIELDS}],
        "processing_time": 0.1,
    }


class StructuredDebugTests(unittest.TestCase):
    def test_links_layout_ocr_blocks_and_extraction_evidence(self):
        line = {
            "text": "V/v thử nghiệm",
            "bbox": [10.0, 20.0, 90.0, 35.0],
            "quad": [[10.0, 20.0], [90.0, 20.0], [90.0, 35.0], [10.0, 35.0]],
        }
        block = {
            "type": "doc_title",
            "bbox": [8.0, 18.0, 92.0, 38.0],
            "score": 0.95,
            "source_layout_id": 1,
            "content_type": "text",
            "content": "V/v thử nghiệm",
            "text_items": [line],
        }
        trace = PipelineDebugTrace(
            layout_blocks=[[{"type": "doc_title", "bbox": [8, 18, 92, 38], "score": 0.95}]],
            ocr_lines=[[line]],
        )
        extract_debug = {
            "document_start_page": 1,
            "document_end_page": 1,
            "next_document_start_page": None,
            "geometry_reliable": True,
            "evidence": {
                **{field: [] for field in FIELDS},
                "title": [{
                    "page": 1,
                    "block": 1,
                    "block_id": 1,
                    "block_type": "doc_title",
                    "source_layout_id": 1,
                    "rule": "v-v-title-preserved",
                    "value": "V/v thử nghiệm",
                    "source_text": "V/v thử nghiệm",
                    "bbox": [8.0, 18.0, 92.0, 38.0],
                    "bbox_normalized": [0.08, 0.09, 0.92, 0.19],
                    "geometry_reliable": True,
                }],
            },
        }

        result = build_structured_debug(
            trace, [[block]], [(100, 200)], ["/page.png"],
            "# V/v thử nghiệm", prediction(), extract_debug,
            document_id="sample_doc",
            source_filename="sample_doc.pdf",
            pdf_path="/path/to/sample_doc.pdf",
        )
        response = VBHCPredictionResponse(**{**prediction(), "debug": result})

        self.assertEqual(response.debug.document_id, "sample_doc")
        self.assertEqual(response.debug.source_filename, "sample_doc.pdf")
        self.assertEqual(response.debug.pdf_path, "/path/to/sample_doc.pdf")
        page = response.debug.pages[0]
        self.assertEqual(page.ocr_lines[0].block_id, 1)
        self.assertEqual(page.blocks[0].source_layout_id, 1)
        self.assertEqual(page.blocks[0].ocr_line_ids, [1])
        self.assertEqual(page.width, 100)
        self.assertEqual(page.height, 200)
        self.assertEqual(response.debug.version, 2)
        self.assertEqual(response.debug.extraction.fields["title"].evidence[0].bbox, [8.0, 18.0, 92.0, 38.0])
        self.assertEqual(response.debug.extraction.fields["priority_level"].status, "default")
        self.assertEqual(response.debug.extraction.fields["receiverDate"].status, "not_found")
        for field_name in FIELDS:
            field_data = response.debug.extraction.fields[field_name]
            self.assertIn("value", field_data.model_dump())
            self.assertIn("status", field_data.model_dump())
            self.assertIn("evidence", field_data.model_dump())
            self.assertEqual(field_data.value, prediction()["information"][0][field_name]["value"])

        invalid_v2 = {**result, "document_id": None}
        with self.assertRaises(ValueError):
            VBHCPredictionResponse(**{**prediction(), "debug": invalid_v2})

    def test_process_pdf_debug_is_config_driven_and_not_persisted_in_prediction(self):
        image = Image.new("RGB", (1000, 1000), "white")
        line = {
            "text": "V/v thử nghiệm",
            "bbox": [250.0, 220.0, 800.0, 300.0],
            "quad": [[250.0, 220.0], [800.0, 220.0], [800.0, 300.0], [250.0, 300.0]],
        }
        pages_blocks = [[
            {"type": "text", "bbox": [510, 40, 920, 100], "score": 0.9, "source_layout_id": 1,
             "content_type": "text", "content": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", "text_items": []},
            {"type": "text", "bbox": [100, 140, 460, 185], "score": 0.9, "source_layout_id": 2,
             "content_type": "text", "content": "Số: 01/CV-TEST", "text_items": []},
            {"type": "doc_title", "bbox": [250, 220, 800, 300], "score": 0.95, "source_layout_id": 3,
             "content_type": "text", "content": "V/v thử nghiệm", "text_items": [line]},
        ]]
        raw_layout = [[
            {"type": block["type"], "bbox": block["bbox"], "score": block["score"]}
            for block in pages_blocks[0]
        ]]
        label_schema = LayoutLabelSchema(
            table_types=frozenset({"table"}),
            skip_types=frozenset(),
            title_types=frozenset({"doc_title"}),
            h2_types=frozenset({"paragraph_title"}),
        )

        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmpdir:
                config = PipelineConfig.from_conf({
                    "output": {"dir": tmpdir},
                    "debug": {"enabled": enabled, "dir": str(Path(tmpdir) / "debug")},
                    "crop_whitespace": {"enabled": False},
                })
                pipeline = DocumentPipeline(SimpleNamespace(label_schema=label_schema), Mock(), Mock(), config)
                pdf_path = Path(tmpdir) / "source.pdf"
                pdf_path.write_bytes(b"test")

                def fake_process(_pages, _debug_dir, debug_trace=None):
                    if debug_trace is not None:
                        debug_trace.layout_blocks = raw_layout
                        debug_trace.ocr_lines = [[line]]
                    return pages_blocks, [(0.0, 0.0)], [image]

                with (
                    patch("module.pipeline.document_pipeline.load_pdf_page_count", return_value=1),
                    patch("module.pipeline.document_pipeline.load_pdf_page_window", return_value=[image]),
                    patch.object(pipeline, "_process_pages_batch", side_effect=fake_process),
                ):
                    result = pipeline.process_pdf(str(pdf_path), source_filename="sample.pdf")

                VBHCPredictionResponse(**result)
                self.assertEqual("debug" in result, enabled)
                if enabled:
                    self.assertEqual(result["debug"]["document_id"], "sample")
                    self.assertEqual(result["debug"]["source_filename"], "sample.pdf")
                    self.assertEqual(result["debug"]["pdf_path"], str(pdf_path.resolve()))
                serialized = VBHCPredictionResponse(**result).model_dump(exclude_none=True)
                self.assertEqual("debug" in serialized, enabled)
                persisted = json.loads((Path(tmpdir) / "sample" / "prediction.json").read_text(encoding="utf-8"))
                self.assertNotIn("debug", persisted)


if __name__ == "__main__":
    unittest.main()
