import unittest

from test_vbhc_rules import block, extract


class PolicyFallbackTests(unittest.TestCase):
    def skipped_footnote(self, lines, kind="footnote"):
        return {
            "type": kind, "content_type": "skip", "content": None,
            "bbox": [100, 500, 900, 620], "source_layout_id": 7,
            "text_items": [{"text": line, "bbox": [100, 500 + i * 30, 900, 525 + i * 30]}
                           for i, line in enumerate(lines)],
        }

    def header(self):
        return [
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 12/QĐ-BTP", [100, 140, 460, 185]),
            block("QUYẾT ĐỊNH", [300, 220, 700, 260]),
        ]

    def test_adoption_fallback_and_header_priority(self):
        header = self.header()
        closing = [
            block("Luật này được Quốc hội thông qua ngày 24 tháng 8 năm 2026.", [100, 400, 900, 470]),
            block("Nơi nhận:\n- Bộ Tư pháp;\n- Lưu: VT.", [100, 650, 450, 850]),
        ]
        result, debug = extract([header, closing])
        self.assertEqual(result["information"][0]["documentDate"]["value"], "24/08/2026")
        self.assertEqual(debug["evidence"]["documentDate"][0]["page"], 2)
        header.append(block("Hà Nội, ngày 20 tháng 8 năm 2026", [510, 145, 920, 190]))
        result, _ = extract([header, closing])
        self.assertEqual(result["information"][0]["documentDate"]["value"], "20/08/2026")
        self.assertEqual(result["information"][0]["province"]["value"], "Hà Nội")

    def test_cited_adoption_rejected(self):
        result, _ = extract([self.header(), [
            block("Căn cứ Luật được thông qua ngày 24 tháng 8 năm 2026", [100, 400, 900, 470]),
        ]])
        self.assertEqual(result["information"][0]["documentDate"]["value"], "")

    def test_company_label_in_body_optional_colon(self):
        for label in ("Tên công ty phát hành", "Tên tổ chức:"):
            with self.subTest(label=label):
                result, _ = extract([self.header() + [
                    block(label + " CÔNG TY THỬ NGHIỆM", [100, 550, 900, 600]),
                ]])
                self.assertEqual(result["information"][0]["officeSender"]["value"], "CÔNG TY THỬ NGHIỆM")

    def test_recipient_label_not_issuer(self):
        result, _ = extract([self.header() + [
            block("Tên công ty nhận: CÔNG TY THỬ NGHIỆM", [100, 550, 900, 600]),
        ]])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "")

    def test_consolidated_type_uses_real_heading_split_or_merged(self):
        for kind in ("THÔNG TƯ", "NGHỊ ĐỊNH"):
            for merged in (False, True):
                with self.subTest(kind=kind, merged=merged):
                    label = "VĂN BÀN HỢP NHẤT"
                    headings = ([block(label + "\n" + kind + "\nQuy định thử nghiệm", [100, 100, 900, 300])]
                                if merged else [block(label, [100, 100, 450, 140]),
                                                block(kind + "\nQuy định thử nghiệm", [300, 220, 800, 300])])
                    result, debug = extract([headings])
                    self.assertEqual(result["information"][0]["type"]["value"], kind)
                    self.assertEqual(result["information"][0]["title"]["value"], "Quy định thử nghiệm")
                    self.assertEqual(debug["evidence"]["type"][0]["value"], kind)

    def test_vbhn_code_or_citation_cannot_supply_type(self):
        result, _ = extract([[
            block("VĂN BẢN HỢP NHẤT", [100, 80, 450, 120]),
            block("Số: 99/2026/VBHN-TT-ABC", [100, 140, 450, 180]),
            block("Thông tư số 12/2020/TT-ABC ngày 1 tháng 1 năm 2020", [100, 350, 900, 430]),
        ]])
        self.assertEqual(result["information"][0]["type"]["value"], "")

    def test_vbhn_does_not_stop_at_country_mention_or_old_signature(self):
        first = self.header() + [block("VĂN BẢN HỢP NHẤT", [100, 40, 450, 100])]
        middle = [
            block("Theo pháp luật của nước Cộng hòa xã hội chủ nghĩa Việt Nam là bên ký kết", [100, 100, 900, 300]),
            block("Số: 88/2020/QĐ-ABC", [100, 310, 450, 340]),
            block("QUYẾT ĐỊNH", [100, 350, 900, 400]),
            block("Nơi nhận:\n- Cơ quan cũ", [100, 600, 450, 700]),
        ]
        closing = [
            block("BỘ THỬ NGHIỆM", [580, 400, 900, 440]),
            block("XÁC THỰC VĂN BẢN HỢP NHẤT", [530, 460, 950, 500]),
            block("Nơi nhận:\n- Như trên;\n- Lưu: VT.", [100, 600, 450, 800]),
        ]
        result, debug = extract([first, middle, closing])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "BỘ THỬ NGHIỆM")
        self.assertEqual(debug["document_end_page"], 3)
        self.assertIsNone(debug["next_document_start_page"])

    def test_independent_document_boundary_prevents_borrowing_authentication(self):
        next_doc = self.header() + [
            block("BỘ KHÁC\nXÁC THỰC VĂN BẢN HỢP NHẤT", [550, 600, 950, 700]),
        ]
        first = self.header() + [block("VĂN BẢN HỢP NHẤT", [100, 40, 450, 100])]
        result, debug = extract([first, next_doc])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "")
        self.assertEqual(debug["next_document_start_page"], 2)

    def test_merged_authentication_and_body_footer_rejection(self):
        result, _ = extract([self.header(), [
            block("BỘ THỬ NGHIỆM\nXÁC THỰC VĂN BẢN HỢP NHẤT\nHà Nội, ngày 1 tháng 2 năm 2026", [550, 400, 950, 600]),
        ]])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "BỘ THỬ NGHIỆM")
        result, _ = extract([self.header() + [
            block("Ủy ban nhân dân Thành phố ban hành Quyết định này như sau", [100, 880, 900, 940]),
        ]])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "")

    def test_valid_header_issuer_wins_and_code_stays_on_first_page(self):
        header = self.header() + [block("BỘ BAN HÀNH", [100, 40, 450, 100])]
        closing = [
            block("BỘ XÁC THỰC", [550, 400, 900, 440]),
            block("XÁC THỰC VĂN BẢN HỢP NHẤT", [550, 460, 950, 500]),
        ]
        result, debug = extract([header, closing])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "BỘ BAN HÀNH")
        self.assertEqual(result["information"][0]["code"]["value"], "12/QĐ-BTP")
        self.assertEqual(debug["evidence"]["code"][0]["page"], 1)

    def test_closing_issuer_does_not_move_code_anchor(self):
        header = self.header() + [block("VĂN BẢN HỢP NHẤT", [100, 40, 450, 100])]
        closing = [
            block("BỘ THỬ NGHIỆM", [550, 400, 900, 440]),
            block("XÁC THỰC VĂN BẢN HỢP NHẤT", [550, 460, 950, 500]),
        ]
        result, debug = extract([header, closing])
        self.assertEqual(result["information"][0]["officeSender"]["value"], "BỘ THỬ NGHIỆM")
        self.assertEqual(result["information"][0]["code"]["value"], "12/QĐ-BTP")
        self.assertEqual(debug["evidence"]["code"][0]["page"], 1)

    def test_skipped_adoption_footnote_is_date_only_and_does_not_mutate_input(self):
        import copy
        footnote = self.skipped_footnote([
            "Nghị quyết này được Quốc hội nước Cộng hòa xã hội chủ nghĩa Việt",
            "Nam khóa XVI thông qua ngày 17 tháng 4",
            "năm 2025.",
        ])
        pages = [self.header(), [
            block("Nghị quyết này có hiệu lực thi hành từ ngày 1 tháng 7 năm 2025", [100, 300, 900, 400]),
            footnote,
            block("CHỦ TỊCH QUỐC HỘI\nNguyễn Văn An", [550, 700, 950, 850]),
        ]]
        original = copy.deepcopy(pages)
        result, debug = extract(pages)
        info = result["information"][0]
        self.assertEqual(info["documentDate"]["value"], "17/04/2025")
        self.assertEqual(info["province"]["value"], "")
        self.assertEqual(info["officeSender"]["value"], "")
        self.assertEqual(debug["document_end_page"], 2)
        ev = debug["evidence"]["documentDate"][0]
        self.assertEqual(ev["rule"], "closing-adoption-date-skipped-footnote")
        self.assertEqual((ev["page"], ev["block"], ev["source_layout_id"]), (2, 2, 7))
        self.assertEqual(ev["source_text"], "\n".join(x["text"] for x in footnote["text_items"]))
        self.assertEqual(pages, original)
        without_ocr = copy.deepcopy(pages)
        without_ocr[1][1]["text_items"] = []
        baseline, _ = extract(without_ocr)
        self.assertEqual(
            {f: v for f, v in info.items() if f != "documentDate"},
            {f: v for f, v in baseline["information"][0].items() if f != "documentDate"},
        )

    def test_skipped_footnote_cannot_override_header_date_or_province(self):
        result, debug = extract([self.header() + [
            block("Hà Nội, ngày 12 tháng 3 năm 2025", [510, 145, 920, 190]),
        ], [self.skipped_footnote(["Luật này được thông qua ngày 17 tháng 4 năm 2025."])]])
        self.assertEqual(result["information"][0]["documentDate"]["value"], "12/03/2025")
        self.assertEqual(result["information"][0]["province"]["value"], "Hà Nội")
        self.assertEqual(debug["evidence"]["documentDate"][0]["rule"], "issuance-date")

    def test_skipped_effective_date_citation_and_invalid_date_stay_empty(self):
        for text in (
            "Nghị quyết này có hiệu lực thi hành từ ngày 1 tháng 7 năm 2025.",
            "Căn cứ Luật này được thông qua ngày 17 tháng 4 năm 2025.",
            "Luật số 99 được thông qua ngày 17 tháng 4 năm 2025.",
            "Luật này được thông qua ngày 31 tháng 2 năm 2025.",
        ):
            with self.subTest(text=text):
                result, _ = extract([self.header(), [self.skipped_footnote([text])]])
                self.assertEqual(result["information"][0]["documentDate"]["value"], "")

    def test_adoption_in_other_skipped_types_or_next_document_is_not_used(self):
        adoption = "Luật này được thông qua ngày 17 tháng 4 năm 2025."
        for kind in ("header", "footer", "table", "number"):
            with self.subTest(kind=kind):
                result, _ = extract([self.header(), [self.skipped_footnote([adoption], kind)]])
                self.assertEqual(result["information"][0]["documentDate"]["value"], "")
        result, debug = extract([
            self.header(),
            [block("Nơi nhận:\n- Như trên;", [100, 600, 450, 700])],
            self.header() + [self.skipped_footnote([adoption])],
        ])
        self.assertEqual(debug["next_document_start_page"], 3)
        self.assertEqual(result["information"][0]["documentDate"]["value"], "")

    def test_type_number_line_does_not_duplicate_type_in_title(self):
        for merged in (False, True):
            with self.subTest(merged=merged):
                headings = ([block("NGHỊ QUYẾT\nVề nội dung thử nghiệm\ncho các đơn vị", [250, 220, 850, 330], "doc_title")]
                            if merged else [block("NGHỊ QUYẾT", [350, 220, 700, 260]),
                                            block("Về nội dung thử nghiệm\ncho các đơn vị", [250, 270, 850, 330])])
                result, debug = extract([[
                    block("QUỐC HỘI", [100, 40, 450, 100]),
                    block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
                    block("Nghị quyết số: 88/2025/QH99", [100, 140, 450, 185]),
                    *headings,
                    block("Căn cứ Luật thử nghiệm", [100, 370, 900, 420]),
                ]])
                self.assertEqual(result["information"][0]["type"]["value"], "NGHỊ QUYẾT")
                self.assertEqual(result["information"][0]["title"]["value"], "Về nội dung thử nghiệm cho các đơn vị")
                self.assertEqual(debug["evidence"]["type"][0]["block"], 4)

    def test_number_line_without_separate_heading_keeps_title(self):
        result, _ = extract([[
            block("Nghị quyết số: 88/2025/QH99", [100, 140, 450, 185]),
            block("Về nội dung thử nghiệm", [250, 220, 850, 280]),
            block("Căn cứ Luật thử nghiệm", [100, 370, 900, 420]),
        ]])
        self.assertEqual(result["information"][0]["type"]["value"], "NGHỊ QUYẾT")
        self.assertEqual(result["information"][0]["title"]["value"], "Về nội dung thử nghiệm")
