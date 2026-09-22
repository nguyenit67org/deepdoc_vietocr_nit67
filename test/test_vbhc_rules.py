import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from module.extract.vbhc_rules import extract_vbhc
from module.layout.base import LayoutLabelSchema
from module.pipeline.config import PipelineConfig
from module.pipeline.document_pipeline import DocumentPipeline
from module.pipeline.loader import load_pdf_pages


def block(text, bbox, block_type="text", content_type="text"):
    return {
        "type": block_type,
        "bbox": bbox,
        "score": 0.9,
        "content_type": content_type,
        "content": text,
    }


def extract(pages):
    sizes = [(1000, 1000)] * len(pages)
    return extract_vbhc(pages, sizes, sizes, [(0.0, 0.0)] * len(pages))


def validate_prediction(prediction):
    """Use the repository's system jsonschema 3.2.0 / Draft 7 runtime."""
    script = """
import json, sys
from jsonschema import Draft7Validator
schema = json.load(open('docs/prediction_schema.json', encoding='utf-8'))
Draft7Validator.check_schema(schema)
Draft7Validator(schema).validate(json.load(sys.stdin))
"""
    subprocess.run(
        ["/usr/bin/python3", "-c", script],
        input=json.dumps(prediction, ensure_ascii=False),
        text=True,
        check=True,
    )


class VBHCRuleExtractionTests(unittest.TestCase):
    def test_extracts_first_document_and_preserves_source_text(self):
        pages = [
            [
                block("BỘ TÀI CHÍNH", [100, 40, 460, 110]),
                block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc", [510, 40, 920, 130]),
                block("Số: 12/QĐ-BTC.01", [100, 145, 460, 190]),
                block("Hà Nội, ngày 29 tháng 02 năm 2024", [510, 145, 920, 190]),
                block("V/v: Giữ nguyên /, - và dấu chấm.", [130, 220, 650, 270]),
                block("Kính gửi: Sở Tài chính; UBND tỉnh.", [300, 310, 850, 370]),
                block("MẬT", [20, 220, 150, 260]),
                block("HỎA TỐC", [20, 275, 180, 315]),
                block("ĐẾN\nNgày: 02/03/2024", [20, 340, 230, 430]),
            ],
            [
                block("Nội dung có từ khẩn và ngày 31/12/2030 nhưng không phải metadata.", [150, 300, 900, 600]),
            ],
            [
                block("Nơi nhận:\n- Bộ Nội vụ;\n- UBND tỉnh;\n- Lưu: VT.", [100, 620, 470, 920]),
                block("KT. CHỦ TỊCH\nPHÓ CHỦ TỊCH", [550, 600, 920, 720]),
                block("ỦY BAN NHÂN DÂN", [600, 710, 820, 850], "seal"),
                block("Nguyễn Văn An", [620, 850, 850, 910]),
            ],
            [
                block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
                block("Số: 99/TB-ABC", [100, 140, 460, 185]),
                block("Hà Nội, ngày 01 tháng 03 năm 2025", [510, 140, 920, 185]),
                block("THÔNG BÁO\nVăn bản đính kèm không được lấy", [250, 220, 800, 300]),
            ],
        ]

        prediction, debug = extract(pages)
        info = prediction["information"][0]

        self.assertEqual(info["type"]["value"], "Công văn")
        self.assertEqual(info["title"]["value"], "V/v: Giữ nguyên /, - và dấu chấm.")
        self.assertEqual(info["code"]["value"], "12/QĐ-BTC01")
        self.assertEqual(info["documentDate"]["value"], "29/02/2024")
        self.assertEqual(info["province"]["value"], "Hà Nội")
        self.assertEqual(info["officeSender"]["value"], "BỘ TÀI CHÍNH")
        self.assertEqual(info["first_recipients"]["value"], "Sở Tài chính; UBND tỉnh.")
        self.assertEqual(info["recipients"]["value"], "Bộ Nội vụ; UBND tỉnh")
        self.assertEqual(info["signer_title"]["value"], "KT. CHỦ TỊCH PHÓ CHỦ TỊCH")
        self.assertEqual(info["signer"]["value"], "Nguyễn Văn An")
        self.assertEqual(info["security_level"]["value"], "1_MẬT")
        self.assertEqual(info["priority_level"]["value"], "1_HỎA TỐC")
        self.assertEqual(info["receiverDate"]["value"], "02/03/2024")
        self.assertEqual(debug["document_start_page"], 1)
        self.assertEqual(debug["document_end_page"], 3)
        self.assertEqual(debug["next_document_start_page"], 4)

    def test_named_document_invalid_date_and_body_false_positives(self):
        pages = [[
            block("ỦY BAN NHÂN DÂN TỈNH A", [100, 40, 470, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 07/QĐ-UBND", [100, 140, 470, 185]),
            block("Tỉnh A, ngày 31 tháng 02 năm 2024", [510, 140, 920, 185]),
            block("QUYẾT ĐỊNH\nBan hành quy chế thử nghiệm", [260, 220, 790, 310]),
            block("CÔNG VĂN ĐẾN Ngày: 32/13/2024", [20, 330, 250, 420]),
            block("Thời hạn từ ngày 30/10/2020 đến ngày 30/01/2021.", [140, 430, 900, 490]),
            block("Điều 1. Xử lý việc khẩn trong nội dung.", [140, 500, 900, 650]),
            block("Báo cáo Chủ tịch xem xét và quyết định nội dung này.", [140, 670, 900, 760]),
        ]]

        prediction, _ = extract(pages)
        info = prediction["information"][0]

        self.assertEqual(info["type"]["value"], "QUYẾT ĐỊNH")
        self.assertEqual(info["title"]["value"], "Ban hành quy chế thử nghiệm")
        self.assertEqual(info["documentDate"]["value"], "")
        self.assertEqual(info["receiverDate"]["value"], "")
        self.assertEqual(info["priority_level"]["value"], "0_BÌNH THƯỜNG")
        self.assertEqual(info["security_level"]["value"], "0_BÌNH THƯỜNG")
        self.assertEqual(info["signer_title"]["value"], "")
        self.assertEqual(info["signer"]["value"], "")

    def test_named_type_wins_over_vv_and_recipient_does_not_absorb_body(self):
        pages = [[
            block("BỘ Y TẾ", [100, 40, 470, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 15/TB-BYT", [100, 140, 470, 185]),
            block("THÔNG BÁO", [300, 215, 700, 260]),
            block("V/v: lịch làm việc", [260, 275, 760, 320]),
            block("Kính gửi: Sở Y tế tỉnh A", [260, 350, 760, 395]),
            block("Trụ sở: 12 phố X", [260, 430, 760, 475]),
        ]]

        prediction, _ = extract(pages)
        info = prediction["information"][0]

        self.assertEqual(info["type"]["value"], "THÔNG BÁO")
        self.assertEqual(info["title"]["value"], "V/v: lịch làm việc")
        self.assertEqual(info["first_recipients"]["value"], "Sở Y tế tỉnh A")

    def test_multiple_signature_clusters_keep_reading_order(self):
        pages = [[
            block("BỘ TƯ PHÁP", [100, 40, 450, 100]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 01/QĐ-BTP", [100, 140, 450, 185]),
            block("QUYẾT ĐỊNH\nVề việc thử nghiệm", [260, 220, 790, 300]),
            block("GIÁM ĐỐC", [500, 600, 690, 680]),
            block("PHÓ GIÁM ĐỐC", [730, 600, 950, 680]),
            block("Nguyễn Văn An", [500, 820, 690, 880]),
            block("Trần Thị Bình", [730, 820, 950, 880]),
        ]]

        prediction, _ = extract(pages)
        info = prediction["information"][0]

        self.assertEqual(info["signer_title"]["value"], "GIÁM ĐỐC; PHÓ GIÁM ĐỐC")
        self.assertEqual(info["signer"]["value"], "Nguyễn Văn An; Trần Thị Bình")

    def test_multiblock_values_report_every_contributing_evidence_region(self):
        pages = [[
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 01/QĐ-TEST", [100, 140, 460, 185]),
            block("Hà Nội, ngày 01 tháng 01 năm 2026", [510, 140, 920, 185]),
            block("QUYẾT ĐỊNH", [300, 215, 700, 260], "doc_title"),
            block("Về việc thử nghiệm", [280, 270, 720, 310], "doc_title"),
            block("Kính gửi: Sở Tài chính", [260, 340, 760, 380]),
            block("ỦY BAN NHÂN DÂN TỈNH A", [260, 385, 760, 425]),
            block("ĐẾN", [20, 440, 150, 485]),
            block("Ngày: 02/03/2024", [20, 490, 230, 535]),
        ]]

        prediction, debug = extract(pages)

        self.assertEqual(prediction["information"][0]["title"]["value"], "Về việc thử nghiệm")
        self.assertEqual([item["block_id"] for item in debug["evidence"]["title"]], [5])
        self.assertEqual([item["block_id"] for item in debug["evidence"]["first_recipients"]], [6, 7])
        self.assertEqual([item["block_id"] for item in debug["evidence"]["receiverDate"]], [8, 9])
        for field in ("title", "first_recipients", "receiverDate"):
            for item in debug["evidence"][field]:
                self.assertEqual(len(item["bbox"]), 4)
                self.assertIn("block_type", item)

    def test_office_sender_multiline_joined_with_space(self):
        pages = [[
            block("BỘ VĂN HÓA, THỂ THAO\nVÀ DU LỊCH", [100, 40, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 4977/BVHTTDL VP", [100, 140, 460, 185]),
            block("Hà Nội, ngày 07 tháng 08 năm 2026", [510, 140, 920, 185]),
            block("V/v tổ chức hội nghị", [250, 220, 800, 270]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["officeSender"]["value"], "BỘ VĂN HÓA, THỂ THAO VÀ DU LỊCH")
        self.assertEqual(info["code"]["value"], "4977/BVHTTDL-VP")

    def test_office_sender_stops_before_merged_first_recipient(self):
        pages = [[
            block("TỔNG CÔNG TY CỔ PHẦN TÁI BẢO HIỂM PVI\nKính gửi: ỦY BAN CHỨNG KHOÁN NHÀ NƯỚC", [80, 40, 480, 130]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 90]),
            block("Số: 262/PVIRe-HĐ", [100, 145, 460, 185]),
            block("Hà Nội, ngày 23 tháng 11 năm 2020", [510, 145, 920, 185]),
            block("HỢP ĐỒNG", [300, 230, 700, 280]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"],
            "TỔNG CÔNG TY CỔ PHẦN TÁI BẢO HIỂM PVI",
        )

    def test_closing_page_adoption_date_not_used_as_document_date(self):
        pages = [
            [
                block("BỘ TÀI CHÍNH", [100, 40, 460, 110]),
                block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
                block("Số: 10/QĐ-BTC", [100, 140, 460, 185]),
                block("QUYẾT ĐỊNH\nVề việc ban hành quy chế", [250, 220, 800, 300]),
            ],
            [
                block("Hai bên thông qua ngày 15 tháng 05 năm 2020.", [150, 500, 850, 550]),
                block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 620, 470, 800]),
                block("GIÁM ĐỐC", [600, 620, 850, 680]),
                block("Nguyễn Văn An", [600, 750, 850, 800]),
            ],
        ]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["documentDate"]["value"], "")

    def test_empty_document_obeys_prediction_schema(self):
        prediction, debug = extract_vbhc([], [], [], [])
        validate_prediction(prediction)
        self.assertIsNone(debug["document_start_page"])


class LoaderAndPipelineIntegrationTests(unittest.TestCase):
    @patch("module.pipeline.loader.convert_from_path")
    def test_loader_renders_all_pages_in_one_ordered_call(self, convert):
        expected = [Image.new("RGB", (10, 10), (value, value, value)) for value in (1, 2, 3)]
        convert.return_value = expected

        actual = load_pdf_pages("document.pdf", dpi=180)

        self.assertIs(actual, expected)
        convert.assert_called_once_with("document.pdf", dpi=180)

    def test_process_pdf_returns_prediction_and_keeps_raw_artifacts(self):
        image = Image.new("RGB", (1000, 1000), "white")
        pages_blocks = [[
            block("BỘ TƯ PHÁP", [100, 40, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 01/TB-BTP", [100, 140, 460, 185]),
            block("Hà Nội, ngày 01 tháng 01 năm 2026", [510, 140, 920, 185]),
            block("THÔNG BÁO\nKết quả thử nghiệm", [250, 220, 800, 300]),
        ]]
        label_schema = LayoutLabelSchema(
            table_types=frozenset({"table"}),
            skip_types=frozenset(),
            title_types=frozenset({"doc_title"}),
            h2_types=frozenset({"paragraph_title"}),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = PipelineConfig.from_conf({
                "output": {"dir": tmpdir},
                "crop_whitespace": {"enabled": False},
            })
            pipeline = DocumentPipeline(
                layout=SimpleNamespace(label_schema=label_schema),
                ocr=Mock(),
                table_processor=Mock(),
                config=config,
            )
            pdf_path = Path(tmpdir) / "source.pdf"
            pdf_path.write_bytes(b"test")
            with (
                patch("module.pipeline.document_pipeline.load_pdf_pages", return_value=[image]),
                patch.object(
                    pipeline,
                    "_process_pages_batch",
                    return_value=(pages_blocks, [(0.0, 0.0)], [image]),
                ),
            ):
                prediction = pipeline.process_pdf(str(pdf_path), source_filename="sample.pdf")

            validate_prediction(prediction)
            self.assertEqual(prediction["information"][0]["type"]["value"], "THÔNG BÁO")
            self.assertGreaterEqual(prediction["processing_time"], 0)
            out_dir = Path(tmpdir) / "sample"
            self.assertTrue((out_dir / "output.json").exists())
            self.assertTrue((out_dir / "output.md").exists())
            self.assertTrue((out_dir / "prediction.json").exists())


if __name__ == "__main__":
    unittest.main()
