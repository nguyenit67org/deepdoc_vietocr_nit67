"""Regressions from visual review; synthetic text prevents document-specific rules."""
import unittest
from module.extract.vbhc_rules import extract_vbhc


def block(text, box, kind='text', items=None):
    return dict(content=text, bbox=box, type=kind, content_type='text', text_items=items or [])


def extract(blocks):
    prediction, _ = extract_vbhc([blocks], [(1000,1000)], [(1000,1000)], [(0,0)])
    return {key: value['value'] for key,value in prediction['information'][0].items()}


class EvidenceRegressionTests(unittest.TestCase):
    def test_split_recipients_follow_geometry_and_stop_at_archive(self):
        blocks = [block('Nơi nhận:', [80,600,180,625]),
                  block('- Lưu: VT.', [80,720,250,745]),
                  block('- Sở Tài chính;', [80,660,350,685]),
                  block('- Như trên;', [80,630,230,655]),
                  block('CHỦ TỊCH', [600,600,850,630]),
                  block('Nguyễn Văn An', [600,750,850,780])]
        self.assertEqual(extract(blocks)['recipients'], 'Như trên; Sở Tài chính')

    def test_unreadable_arrival_slot_does_not_borrow_body_date(self):
        blocks = [block('ĐẾN',[20,300,90,340]),
                  block('Ngày: 2911211',[90,325,230,355]),
                  block('Căn cứ Luật ngày 29 tháng 6 năm 2006;', [180,375,600,410])]
        self.assertEqual(extract(blocks)['receiverDate'], '')

    def test_arrival_stamp_can_be_in_right_column(self):
        blocks = [block('VĂN BẢN ĐẾN',[650,300,900,330]),
                  block('Ngày: 02/03/2024',[650,335,900,365])]
        self.assertEqual(extract(blocks)['receiverDate'], '02/03/2024')

    def test_noise_in_signature_image_is_not_authority(self):
        items = [dict(text='CHỦ TỊCH',bbox=[600,600,850,630]),
                 dict(text='ABCD',bbox=[610,680,800,710])]
        result = extract([block('CHỦ TỊCH ABCD',[590,590,860,720],'image',items)])
        self.assertEqual(result['signer_title'], 'CHỦ TỊCH')
        self.assertEqual(result['signer'], '')

    def test_existing_signer_and_title_are_preserved(self):
        items = [dict(text='CHỦ TỊCH',bbox=[600,600,850,630]),
                 dict(text='Nguyễn Văn An',bbox=[610,680,850,710])]
        result = extract([block('CHỦ TỊCH Nguyễn Văn An',[590,590,860,720],'image',items)])
        self.assertEqual(result['signer'], 'Nguyễn Văn An')
        self.assertEqual(result['signer_title'], 'CHỦ TỊCH')

    def test_empty_recipients_do_not_absorb_distant_body(self):
        result = extract([block('Nơi nhận:',[80,600,200,625]),
                          block('- Nội dung khác',[80,850,400,880])])
        self.assertEqual(result['recipients'], '')

    def test_department_letterhead_is_an_issuer(self):
        self.assertEqual(extract([block('PHÒNG TỔ CHỨC',[80,30,420,70])])['officeSender'], 'PHÒNG TỔ CHỨC')

    def test_must_accept_valid_code_patterns(self):
        # 1. Số: 4977/BVHTTDL VP -> 4977/BVHTTDL-VP
        blocks1 = [
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
            block("Số: 4977/BVHTTDL VP", [100, 140, 460, 185]),
        ]
        self.assertEqual(extract(blocks1)["code"], "4977/BVHTTDL-VP")

        # 2. Nghị quyết số: 36/2026/QH16 -> 36/2026/QH16
        blocks2 = [
            block("QUỐC HỘI", [100, 40, 460, 100]),
            block("Nghị quyết số: 36/2026/QH16", [200, 200, 800, 250]),
        ]
        self.assertEqual(extract(blocks2)["code"], "36/2026/QH16")

        # 3. Số: /TB-QLNY -> /TB-QLNY
        blocks3 = [
            block("PHÒNG QUẢN LÝ NIÊM YẾT", [100, 40, 460, 100]),
            block("Số: /TB-QLNY", [100, 140, 460, 185]),
        ]
        self.assertEqual(extract(blocks3)["code"], "/TB-QLNY")

    def test_must_not_match_false_positive_code_patterns(self):
        # 1. Địa chỉ: Số 1253 ...
        blocks1 = [
            block("CÔNG TY ABC", [100, 40, 460, 80]),
            block("Địa chỉ: Số 1253 đường Nguyễn Trãi, quận 1", [100, 90, 460, 130]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", [510, 40, 920, 100]),
        ]
        self.assertEqual(extract(blocks1)["code"], "")

        # 2. CÔNG BÁO ... SỐ 225+226
        blocks2 = [
            block("CÔNG BÁO NƯỚC CHXHCN VIỆT NAM SỐ 225+226", [100, 40, 600, 90]),
        ]
        self.assertEqual(extract(blocks2)["code"], "")

        # 3. Căn cứ Thông tư số 39/2016/TT-NHNN
        blocks3 = [
            block("Căn cứ Thông tư số 39/2016/TT-NHNN ngày 30/12/2016", [100, 300, 800, 350]),
        ]
        self.assertEqual(extract(blocks3)["code"], "")

        # 4. Số điều / số trang
        blocks4 = [
            block("Điều 1. Số lượng thành viên...", [100, 400, 800, 450]),
            block("Trang 1/2", [450, 950, 550, 980]),
        ]
        self.assertEqual(extract(blocks4)["code"], "")

    def test_regression_03_nq_dhcd_code_not_address_1253(self):
        blocks = [
            block("CÔNG TY CỔ PHẦN DU LỊCH THƯƠNG MẠI TN Số 1253, CMT8, Ninh Phước, phường Ninh Thạnh, thành phố Tây Ninh, tỉnh TN", [83, 95, 451, 174]),
            block("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM Độc lập - Tự do - Hạnh phúc", [452, 95, 905, 133]),
            block("Số: 03/NQ-ĐHCĐ", [171, 182, 350, 200]),
            block("Tây Ninh, ngày 25 tháng 4 năm 2017", [520, 175, 999, 210]),
            block("NGHỊ QUYẾT\nĐẠI HỘI ĐỒNG CỔ ĐÔNG THƯỜNG NIÊN NĂM 2017", [213, 217, 995, 278]),
        ]
        result = extract(blocks)
        self.assertNotEqual(result["code"], "1253")
        self.assertEqual(result["code"], "03/NQ-ĐHCĐ")
        self.assertEqual(result["officeSender"], "CÔNG TY CỔ PHẦN DU LỊCH THƯƠNG MẠI TN")
