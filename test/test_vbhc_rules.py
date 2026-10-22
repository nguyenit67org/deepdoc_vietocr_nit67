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
        self.assertEqual(info["receiverDate"]["value"], "")
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
        self.assertEqual([item["block_id"] for item in debug["evidence"]["receiverDate"]], [])
        for field in ("title", "first_recipients"):
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

    def test_header_typed_office_accepted_but_signature_annotation_rejected(self):
        pages = [[
            block("BỘ TÀI CHÍNH", [100, 40, 460, 110], "header"),
            block("Người ký Cục Thông tin", [510, 10, 920, 35], "header"),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 10/QĐ-BTC", [100, 140, 460, 185]),
            block("QUYẾT ĐỊNH\nVề việc ban hành quy chế", [250, 220, 800, 300]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "BỘ TÀI CHÍNH"
        )

    def test_merged_office_country_block_keeps_office_part(self):
        pages = [[
            block("THỦ TƯỚNG CHÍNH PHỦ CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [150, 70, 850, 120], "doc_title"),
            block("Số 27/CT-TTg", [200, 140, 450, 185]),
            block("Hà Nội, ngày 25 tháng 6 năm 2026", [510, 140, 920, 185]),
            block("CHỈ THỊ\nVề việc thử nghiệm", [250, 220, 800, 300]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "THỦ TƯỚNG CHÍNH PHỦ"
        )

    def test_consolidated_heading_code_without_so_anchor(self):
        pages = [[
            block("VĂN BẢN HỢP NHẤT 05/2026/VBHN-TT-BTP", [210, 90, 790, 130]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Hà Nội, ngày 28 tháng 8 năm 2026", [510, 140, 920, 185]),
            block("THÔNG TƯ\nQuy định thử nghiệm", [250, 220, 800, 300]),
            block("Thông tư số 07/2022/TT-BTP ngày 01 tháng 11 năm 2022.", [140, 330, 900, 380]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["code"]["value"], "05/2026/VBHN-TT-BTP")
        self.assertEqual(info["documentDate"]["value"], "28/08/2026")

    def test_diacritic_damaged_type_heading_resolves_canonical(self):
        pages = [[
            block("THỦ TƯỚNG CHÍNH PHỦ", [150, 70, 480, 120]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 29/CT-TTg", [200, 140, 450, 185]),
            block("CHÌ THỊ Về đẩy nhanh tiến độ", [250, 220, 800, 300]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["type"]["value"], "CHỈ THỊ")
        self.assertEqual(info["title"]["value"], "Về đẩy nhanh tiến độ")

    def test_place_prefixed_date_wins_over_bare_stamp_date(self):
        pages = [[
            block("CÔNG TY THỬ NGHIỆM", [150, 60, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 12/QĐ-TN/2017", [150, 120, 460, 160]),
            block("Hà Nam, ngày 29 tháng 06 năm 2017", [510, 120, 900, 160]),
            block("Ngày: 03-07-2017", [700, 170, 920, 210]),
            block("NGHỊ QUYẾT\nVề việc thử nghiệm", [250, 230, 800, 310]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["documentDate"]["value"], "29/06/2017"
        )

    def test_recipient_anchor_without_lower_zone_still_closes_document(self):
        pages = [
            [block("BỘ THỬ NGHIỆM", [100, 40, 460, 110])],
            [block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [60, 300, 400, 450])],
            [block("Phụ lục thống kê.", [100, 100, 900, 200])],
        ]
        prediction, debug = extract(pages)
        self.assertEqual(debug["document_end_page"], 2)
        self.assertEqual(
            prediction["information"][0]["recipients"]["value"], "Như trên"
        )

    def test_urgency_stamp_with_dropped_h_still_detected(self):
        pages = [[
            block("BỘ THỬ NGHIỆM", [100, 40, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("OA TỐC", [20, 160, 150, 200], "image"),
            block("Số 60/CĐ-TN", [200, 140, 450, 185]),
            block("CÔNG ĐIỆN\nVề việc thử nghiệm", [250, 230, 800, 310]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["priority_level"]["value"], "1_HỎA TỐC"
        )

    def test_inline_filing_suffix_stripped_from_recipients(self):
        pages = [
            [
                block("BỘ THỬ NGHIỆM", [100, 40, 460, 110]),
                block("QUYẾT ĐỊNH\nVề việc thử nghiệm", [250, 220, 800, 300]),
            ],
            [block("Nơi nhận:\n- Như Điều 5;\n- HĐQT, Ban TGĐ Lưu VT, TK HĐCS 10.", [100, 500, 470, 750])],
        ]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["recipients"]["value"],
            "Như Điều 5; HĐQT, Ban TGĐ",
        )

    def test_wrapped_arrival_stamp_den_prefix_out_of_scope(self):
        # receiverDate is out of extraction scope this round: the API key is
        # still returned (always "") for schema stability, but no stamp block
        # is read.
        pages = [[
            block("CÔNG TY THỬ NGHIỆM", [150, 60, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 12/QĐ-TN/2017", [150, 120, 460, 160]),
            block("Hà Nam, ngày 29 tháng 06 năm 2017 Đến", [510, 120, 900, 165]),
            block("Ngày: 03-07-2017", [700, 175, 920, 210]),
            block("NGHỊ QUYẾT\nVề việc thử nghiệm", [250, 230, 800, 310]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["receiverDate"]["value"], ""
        )

    def test_vv_wrapped_type_word_is_not_a_heading(self):
        pages = [[
            block("CÔNG TY THỬ NGHIỆM", [150, 60, 460, 110]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 270/TN-HĐ", [150, 120, 460, 160]),
            block("V/v: Công bố thông tin\nNghị quyết Đại hội đồng cổ đông", [150, 200, 850, 280]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["type"]["value"], "Công văn")
        self.assertTrue(info["title"]["value"].startswith("V/v:"))

    def test_top_strip_signature_portal_is_not_office(self):
        pages = [[
            block("VG PHI Công Tháng Lin điên từ Chính phủ", [160, 5, 600, 35], "header"),
            block("THỦ TƯỚNG CHÍNH PHỦ", [250, 125, 700, 170]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 27/CT-TTg", [200, 140, 450, 185]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "THỦ TƯỚNG CHÍNH PHỦ"
        )

    def test_first_recipient_continuation_ignores_stamp_serial(self):
        pages = [[
            block("Kính gửi: Ủy ban Chứng khoán Nhà nước", [490, 450, 1190, 500]),
            block("Số: 10608", [1200, 400, 1450, 480]),
            block("Số: 138/DLTM", [150, 120, 460, 160]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["first_recipients"]["value"],
            "Ủy ban Chứng khoán Nhà nước",
        )

    def test_consolidated_document_type_recognized(self):
        pages = [[
            block("VĂN BẢN HỢP NHẤT", [250, 100, 750, 150]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số 27/2026/VBHN-NĐ-BTC", [200, 160, 500, 200]),
            block("NGHỊ ĐỊNH\nQuy định thử nghiệm", [250, 230, 800, 310]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["type"]["value"], "NGHỊ ĐỊNH"
        )

    def test_title_continuation_stops_at_citation_lines(self):
        pages = [[
            block("BỘ THỬ NGHIỆM", [100, 40, 460, 110]),
            block("QUYẾT ĐỊNH", [300, 215, 700, 260]),
            block("Hướng dẫn thử nghiệm", [280, 270, 720, 310]),
            block("Căn cứ Luật thử nghiệm", [140, 330, 900, 370]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["title"]["value"], "Hướng dẫn thử nghiệm"
        )

    def test_form_template_block_is_not_office(self):
        pages = [[
            block("Mẫu 08 CBTT/SGDHN Ban hành kèm theo", [100, 40, 900, 90]),
            block("TỔNG CÔNG TY THỬ NGHIỆM", [100, 110, 460, 160]),
            block("Số: 01/TN-2020", [100, 180, 460, 220]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "TỔNG CÔNG TY THỬ NGHIỆM"
        )

    def test_allcaps_authority_phrase_is_title_not_signer(self):
        pages = [
            [block("BỘ THỬ NGHIỆM", [100, 40, 460, 110])],
            [
                block("Nơi nhận:\n- Như trên.", [100, 500, 470, 600]),
                block("TM. CHÍNH PHỦ THỦ TƯỚNG", [550, 500, 950, 580]),
                block("Nguyễn Xuân Phúc", [550, 620, 950, 670]),
            ],
        ]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["signer_title"]["value"], "TM. CHÍNH PHỦ THỦ TƯỚNG")
        self.assertEqual(info["signer"]["value"], "Nguyễn Xuân Phúc")

    def test_cong_dien_recipients_after_dispatch_line(self):
        pages = [[
            block("THỦ TƯỚNG CHÍNH PHỦ", [150, 70, 480, 120]),
            block("Số 32/CĐ-TN", [200, 140, 450, 185]),
            block("CÔNG ĐIỆN Về việc thử nghiệm", [250, 200, 800, 260]),
            block("THỦ TƯỚNG CHÍNH PHỦ ĐIỆN:", [300, 290, 700, 330]),
            block("- Giám đốc các sở; - Chủ tịch UBND các tỉnh.", [250, 340, 800, 420]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["type"]["value"], "CÔNG ĐIỆN")
        self.assertEqual(
            info["first_recipients"]["value"],
            "Giám đốc các sở; Chủ tịch UBND các tỉnh.",
        )

    def test_mid_sentence_authority_mention_is_not_signature(self):
        pages = [
            [block("BỘ THỬ NGHIỆM", [100, 40, 460, 110])],
            [
                block("Điều 3. Đại hội giao cho Hội đồng quản trị, Ban Tổng Giám đốc Công ty thực hiện đúng theo nội dung Nghị quyết đã ban hành.", [100, 200, 900, 320]),
                block("Nơi nhận:\n- Như trên.", [100, 500, 470, 600]),
                block("TM. ĐOÀN CHỦ TỊCH", [550, 500, 950, 560]),
                block("- Cổ đông", [550, 570, 950, 610]),
                block("CHỦ TỌA", [550, 620, 950, 660]),
            ],
        ]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["signer_title"]["value"], "TM. ĐOÀN CHỦ TỊCH CHỦ TỌA")

    def test_office_left_of_country_wins_over_full_width_form_header(self):
        pages = [[
            block("Mẫu 08 CBTT/SGDHN Ban hành kèm theo Quyết định số 600", [140, 70, 930, 110], "header"),
            block("TỔNG CÔNG TY THỬ NGHIỆM", [120, 100, 470, 150]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM Độc lập - Tự do - Hạnh phúc", [530, 100, 910, 180]),
            block("Số: 88/TN-2022", [120, 190, 400, 230]),
            block("Thành phố Hồ Chí Minh, ngày 21 tháng 01 năm 2022", [530, 180, 910, 220]),
            block("CÔNG BỐ THÔNG TIN BẤT THƯỜNG", [330, 230, 740, 280]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["officeSender"]["value"], "TỔNG CÔNG TY THỬ NGHIỆM")
        self.assertEqual(info["code"]["value"], "88/TN-2022")
        self.assertEqual(info["documentDate"]["value"], "21/01/2022")


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
                patch("module.pipeline.document_pipeline.load_pdf_page_count", return_value=1),
                patch("module.pipeline.document_pipeline.load_pdf_page_window", return_value=[image]),
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


class SignatureClusterAndTitleBoundaryTests(unittest.TestCase):
    """Title boundaries and signer clusters per contract 3.1 (synthetic)."""

    def test_consolidated_title_stops_before_cited_instrument(self):
        pages = [[
            block("VĂN BẢN HỢP NHẤT", [200, 150, 600, 200]),
            block("Số 66/2026/VBHN-TT-BXD", [150, 250, 550, 290]),
            block("THÔNG TƯ", [700, 350, 950, 400], "paragraph_title"),
            block("Quy định về thử nghiệm", [230, 460, 870, 540]),
            block("Thông tư số 46/2024/TT-BGTVT ngày 15 tháng 11 năm 2024 của Bộ trưởng", [220, 560, 900, 700]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["title"]["value"], "Quy định về thử nghiệm"
        )

    def test_title_skips_stamp_serial_and_letterless_fragments(self):
        pages = [[
            block("THÔNG BÁO", [300, 200, 700, 250]),
            block("Ngày", [500, 260, 600, 290]),
            block("03311-2020", [500, 300, 650, 330]),
            block("Số 14501", [700, 300, 850, 330]),
            block("(Về ngày đăng ký cuối cùng)", [400, 340, 800, 390]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["title"]["value"], "(Về ngày đăng ký cuối cùng)"
        )

    def test_adjacent_authority_blocks_merge_with_space(self):
        pages = [[
            block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 700, 400, 800]),
            block("KT. BỘ TRƯỞNG", [600, 600, 850, 640]),
            block("THỨ TRƯỞNG AY 4", [610, 645, 840, 685]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["signer_title"]["value"], "KT. BỘ TRƯỞNG THỨ TRƯỞNG")
        self.assertEqual(info["signer"]["value"], "")

    def test_org_fragment_without_anchor_is_not_a_second_cluster(self):
        pages = [[
            block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 700, 400, 800]),
            block("TỔNG GIÁM ĐỐC", [700, 550, 900, 590], "figure_title"),
            block("TỔNG CÔNG TY X Trịnh Văn An", [650, 600, 950, 800], "image"),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["signer_title"]["value"], "TỔNG GIÁM ĐỐC")
        self.assertEqual(info["signer"]["value"], "Trịnh Văn An")

    def test_org_fragment_suffix_is_not_signer_beside_printed_name(self):
        pages = [[
            block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 700, 400, 800]),
            block("TL. BỘ TRƯỞNG", [700, 680, 950, 720]),
            block("KT. CỤC TRƯỞNG CỤC QUẢN LÝ VÀ PHÁT TRIỂN", [600, 725, 950, 770]),
            block("Nguyễn Thúy Hiền", [650, 780, 950, 900], "image"),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(
            info["signer_title"]["value"],
            "TL. BỘ TRƯỞNG KT. CỤC TRƯỞNG CỤC QUẢN LÝ VÀ PHÁT TRIỂN",
        )
        self.assertEqual(info["signer"]["value"], "Nguyễn Thúy Hiền")

    def test_code_anchor_is_not_office_sender(self):
        pages = [[
            block("Số:", [100, 150, 200, 180]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(prediction["information"][0]["officeSender"]["value"], "")

    def test_damaged_country_header_still_splits_office(self):
        pages = [[
            block("BỘ VĂN HÓA VÀ DU LỊCH CỘNG HÒA NGHĨA VIỆT NAM", [100, 40, 700, 110]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "BỘ VĂN HÓA VÀ DU LỊCH"
        )

    def test_empty_recipients_collect_unbulleted_short_items(self):
        pages = [[
            block("Nơi nhận:", [80, 600, 200, 625]),
            block("Văn phòng A;", [80, 630, 400, 655]),
            block("Văn phòng B;", [80, 660, 400, 685]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["recipients"]["value"], "Văn phòng A; Văn phòng B"
        )

    def test_empty_kinh_gui_collects_items_below(self):
        pages = [[
            block("Kính gửi:", [300, 300, 500, 340]),
            block("- Sở Tài chính", [320, 350, 700, 390]),
            block("- UBND tỉnh", [320, 400, 700, 440]),
            block("1. Tên tổ chức: X", [200, 450, 800, 490]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["first_recipients"]["value"],
            "Sở Tài chính; UBND tỉnh",
        )

    def test_stamp_serial_segment_dropped_from_recipients(self):
        pages = [[
            block("Nơi nhận:\n- Uỷ ban A;\n- số 1.772;\n- Sở B;", [100, 500, 470, 750]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["recipients"]["value"], "Uỷ ban A; Sở B"
        )

    def test_comma_break_continues_value_bare_break_opens_item(self):
        pages = [[
            block("Nơi nhận:\nĐồng chí A,\nĐồng chí B\nĐồng chí C;", [100, 500, 470, 800]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["recipients"]["value"],
            "Đồng chí A, Đồng chí B; Đồng chí C",
        )

    def test_disclosure_form_takes_content_item_as_title(self):
        pages = [[
            block("CÔNG BỐ THÔNG TIN BẤT THƯỜNG", [300, 200, 700, 250]),
            block("Kính gửi:", [300, 260, 500, 290]),
            block("2. Nội dung thông tin công bố:", [200, 400, 600, 440]),
            block("Nghị quyết về việc thử nghiệm", [200, 450, 800, 500]),
            block("3. Thông tin đã công bố", [200, 520, 600, 560]),
        ]]
        prediction, _ = extract(pages)
        info = prediction["information"][0]
        self.assertEqual(info["type"]["value"], "CÔNG BỐ THÔNG TIN BẤT THƯỜNG")
        self.assertEqual(info["title"]["value"], "Nghị quyết về việc thử nghiệm")

    def test_xac_thuc_office_fallback_on_closing_page(self):
        pages = [[
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 66/2026/VBHN-TT-BXD", [100, 140, 460, 185]),
            block("QUYẾT ĐỊNH\nVề việc thử nghiệm", [250, 220, 800, 300]),
            block("BỘ THỬ NGHIỆM", [700, 600, 950, 640]),
            block("XÁC THỰC VĂN BẢN HỢP NHẤT", [680, 660, 970, 700]),
            block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 700, 400, 800]),
        ]]
        prediction, _ = extract(pages)
        self.assertEqual(
            prediction["information"][0]["officeSender"]["value"], "BỘ THỬ NGHIỆM"
        )


if __name__ == "__main__":
    unittest.main()
