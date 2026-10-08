# PoC Demo – 6 PDF trình bày cho sếp (2 + 2 + 2)

Nguồn PDF: `data/benchmark_demo/raw/data_1/` + `data_2/` (file 26). Kết quả predict
đối chiếu từ bundle full-inference
`ocr-collab/artifacts/evidence_full_inference_all_v3/`
(`document_success.csv`, `field_errors.csv`, `predictions.jsonl`, metric v2.1).
File gốc giữ nguyên, chỉ copy.

## 1. `01_case_de/` – đúng tất cả các field / đạt chuẩn (3 file)

| File | Hồ sơ | Kết quả full-inference |
|---|---|---|
| 3116+QĐ-BKHCN_2026-07-14.pdf | Quyết định, print 2p, `has_handwriting=false` | `document_success_at_5=True`. 11 Exact + title Acceptable + `first_recipients`/`receiverDate` Correct Absent (GT trống, pred trống → đúng). Không có field nào Wrong/Missing/Hallucination. |
| 26+2026+NQ-HĐND_2026-06-19.pdf | Nghị quyết, print 5p, `has_handwriting=false` | `document_success_at_5=True`. 10 Exact + `recipients`/`first_recipients`/`receiverDate` Correct Absent. Sạch nhất nhóm: không có cả Acceptable. |
| 62+CĐ-TTg_2026-08-31.pdf | Công điện, print/scan 2p, **dấu HỎA TỐC** | `document_success_at_5=True`. **7/7 required Exact (đọc chuẩn `priority_level: 1_HỎA TỐC`)** + `recipients`/`first_recipients`/`signer`/`province` Exact. Chỉ có `signer_title` Wrong. |

Lưu ý trung thực về `first_recipients`: đã quét cả 3 bundle (full-inference v3,
replay v13/v14, 100 docs) — không tồn tại file nào vừa zero-error vừa có
`first_recipients` non-empty. 8 file zero-error đều có `first_recipients`
Correct Absent (GT trống, pred trống → tính là đúng theo taxonomy benchmark).
Trong bộ demo này, `first_recipients` non-empty đúng xem ở `62+CĐ-TTg` (Exact `Các đồng chí Bộ trưởng...`) và `03`
(8931+VPCP-PL, Exact `Bộ trưởng Bộ Tư pháp.`).

## 2. `02_case_pho_bien/` – 2 loại văn bản chiếm đa số (3 file)

Phân bố loại trên toàn bộ 100 docs benchmark
(`evidence_full_inference_all_v3/predictions.jsonl`):
Quyết định 30 + Công văn 17 (= 47%) > Nghị quyết 12 > Thông báo 9 >
Thông tư 8 > ... Vì vậy case phổ biến lấy đúng
Quyết định + Công văn (loại phổ biến nhất trong nghiệp vụ hành chính).

Đối chiếu template `docs/vbhc_administrative_layout_diagram.jpg` +
`docs/vbhc_administrative_layout_rules.md`: đủ cụm đầu trang ô 1 (Quốc hiệu/
Tiêu ngữ) – 2 (cơ quan) – 3 (Số) – 4 (địa danh/ngày), trích yếu 5a/5b,
Kính gửi 9a, Nơi nhận 9b, cụm ký 7a/7b/7c + dấu 8.

| File | Vì sao phổ biến + đúng |
|---|---|
| 1666+QĐ-TTg_2026-08-27.pdf | Quyết định (loại số 1, 30/100), scan 5p, `has_handwriting=false`. Zero-error: `document_success_at_5=True`, không field nào Wrong/Missing. Template QĐ chuẩn 5a. |
| 8906+VPCP-CN_2026-08-28.pdf | Công văn (loại số 2, 17/100), print 2p. Required 7/7 đúng: `document_success_at_5=True`. `signer_title` Acceptable CER 0.028 (chỉ lệch dấu `;`: `...CHỦ NHIỆM PHÓ...` → `...CHỦ NHIỆM; PHÓ...`). Template Công văn chuẩn: `V/v` (5b), Kính gửi nhiều Bộ/UBND (9a), Nơi nhận `Như trên...` (9b), ký Phạm Mạnh Cường + dấu. 2 lỗi còn lại đều ở trường optional (recipients/first_recipients Missing). |
| 5509+BCT-TTTN_2026-07-16.pdf | Công văn Bộ Công Thương về giá xăng dầu, scan 6p, **dấu HỎA TỐC**. **Required 7/7 đúng: `document_success_at_5=True` (đọc chuẩn `priority_level: 1_HỎA TỐC`)** + `signer_title` Exact. 2 lỗi ở trường optional (signer, first_recipients Missing). |

## 3. `03_case_kho/` – lỗi OCR / chữ viết tay / dấu mộc (3 file)

Cả 3 đều `scan + has_handwriting=true`, lỗi tập trung đúng lõi yêu cầu.

| File | Lỗi tiêu biểu (GT → Pred, bucket) |
|---|---|
| 8931+VPCP-PL_2026-08-29.pdf | `documentDate` Wrong (`29/08/2026`→`19/08/2026`); `officeSender` Wrong (`VĂN PHÒNG CHÍNH PHỦ`→`...PHỦNH PHỦ`, OCR dính chữ); `priority_level` Wrong (`1_HỎA TỐC`→`0_BÌNH THƯỜNG`, dấu mộc đỏ không đọc được). Tương phản tốt: `first_recipients` vẫn Exact (`Bộ trưởng Bộ Tư pháp.`). `document_success_at_5=False`. |
| 8948+VPCP-CN_2026-09-01.pdf | `documentDate` Missing (mất ngày); `first_recipients` Missing (mất Kính gửi); `signer_title` Wrong CER 0.64 (`KT. BỘ TRƯỞNG CHỦ NHIỆM PHÓ CHỦ NHIỆM` → `...; TO Es CHI Z s hong 0`, rác OCR vùng ký/dấu đè). `document_success_at_5=False`. |
| 29+CT-TTg_2026-07-16.pdf | Case dấu mộc: Chỉ thị scan 4p. `priority_level` Wrong (`1_HỎA TỐC`→`0_BÌNH THƯỜNG`, dấu Hỏa tốc đỏ ô 10b miss); `signer` Wrong (`Hồ Quốc Dũng`→`Huốc Dũng`, OCR mất chữ, nghi dấu/chữ ký đè vùng ký); `signer_title` Missing (mất `KT. THỦ TƯỚNG PHÓ THỦ TƯỚNG`). Header (type/code/date/sender) vẫn Exact — khoanh đúng bệnh ở cụm dấu/ký. `document_success_at_5=False`. |

## Phụ lục: kết quả F1 theo nhóm field (100 docs, giảm dần)

Nguồn: `ocr-collab/artifacts/evidence_full_inference_all_v3/metrics.csv`.
Vẽ lại bằng `.venv/bin/python data/reports/poc_demo/plot_field_results.py`.

![F1 theo nhóm field](./field_results_by_group.png)

### Required (target F1 ≥ 0.95)

| Field | F1 | Trạng thái |
|---|---|---|
| type | 1.000 | Chưa đánh giá đầy đủ (F1 đạt, thiếu mẫu hallucination) |
| security_level | 1.000 | Chưa đánh giá đầy đủ (F1 đạt, thiếu mẫu hallucination + lớp mật) |
| priority_level | 0.950 | Chưa đạt (precision 0.950 < 0.97) |
| code | 0.850 | Chưa đạt |
| documentDate | 0.785 | Chưa đạt |
| officeSender | 0.735 | Chưa đạt |
| title | 0.670 | Chưa đạt |

### Critical + optional (target F1 ≥ 0.95)

| Field | F1 | Trạng thái |
|---|---|---|
| recipients | 0.885 | Chưa đạt |
| signer | 0.802 | Chưa đạt |
| first_recipients | 0.667 | Chưa đạt |
| signer_title | 0.380 | Chưa đạt |

### Non-critical + optional (target F1 ≥ 0.75)

| Field | F1 | Trạng thái |
|---|---|---|
| province | 0.984 | Đạt |
| receiverDate | 0.455 | Chưa đạt |

Đọc nhanh cho sếp: nhóm required chỉ có `type`/`security_level` chạm 1.0
(nhưng chưa đủ mẫu để kết luận đạt); 3 field kéo điểm là `title`, `officeSender`,
`documentDate` — khớp đúng các case khó đã chọn (sai ngày, dính chữ, trích yếu).
`signer_title` (0.380) và `receiverDate` (0.455) là 2 đuôi yếu nhất toàn benchmark.

## Thứ tự present gợi ý (10 phút)
1. `01`: 3116 → QĐ đúng hết; 26 → NQ đúng hết (sạch nhất, toàn Exact).
2. `02`: 1666 → QĐ (loại phổ biến nhất, 30%) đúng hết; 8906 → Công văn (17%) required đúng hết + `signer_title` Acceptable CER 0.028.
3. `03`: 8931 → cùng họ VPCP mà scan+tay+dấu Hỏa tốc là sai 3 chỗ; 8948 → mất ngày + rác OCR vùng ký; 29 (Chỉ thị) → case dấu mộc: miss Hỏa tốc + tên người ký sai + mất chức danh, header vẫn đúng. Chốt: đầu tư tiền xử lý scan, OCR vùng dấu/ký, Document Success@5%.
