# Chuẩn OCR/KIE và benchmark văn bản hành chính

Tài liệu này là nguồn chuẩn hiện hành cho API 13 trường VBHC, quy tắc trích xuất, bằng chứng và benchmark. Các quy tắc còn hiệu lực từ đặc tả API cũ đã được tổng hợp trực tiếp tại đây; implementation và test không cần tham chiếu ngược đặc tả cũ.

## 1. Hợp đồng đầu ra

Pipeline trả đúng một phần tử trong `information`, gồm 13 trường sau. Mỗi trường có `type: "string"` và `value` là chuỗi. Khi liệt kê trong tài liệu hoặc slide, trình bày **mô tả tiếng Việt trước, key API trong ngoặc sau, rồi tới nhóm field**.

- **Critical + required (7):** bắt buộc cho Document Success@5%; đều là field quan trọng.
- **Critical + optional (4):** quan trọng, nhưng chỉ chấm giá trị khi GT có; GT trống vẫn kiểm tra hallucination khi có mẫu số.
- **Non-critical + optional (1):** `province`, cùng nguyên tắc chấm optional.
- **Out of scope (1):** `receiverDate` chỉ giữ key cho ổn định API, không tính vào 12 field được chấm.

| Mô tả tiếng Việt (key API)                         | Nhóm                   | Metric chính | Phạm vi vòng này                                                     |
| ------------------------------------------------------ | ----------------------- | ------------- | ----------------------------------------------------------------------- |
| Loại văn bản (`type`)                             | Critical + required     | F1 Exact      | trích xuất + đánh giá                                              |
| Trích yếu/tiêu đề (`title`)                     | Critical + required     | F1@5%         | trích xuất + đánh giá                                              |
| Số, ký hiệu văn bản (`code`)                    | Critical + required     | F1 Exact      | trích xuất + đánh giá                                              |
| Ngày ban hành (`documentDate`)                     | Critical + required     | F1 Exact      | trích xuất + đánh giá                                              |
| Cơ quan ban hành (`officeSender`)                  | Critical + required     | F1@5%         | trích xuất + đánh giá                                              |
| Độ khẩn (`priority_level`)                        | Critical + required     | F1 Exact      | trích xuất + đánh giá                                              |
| Độ mật (`security_level`)                         | Critical + required     | F1 Exact      | trích xuất + đánh giá                                              |
| Nơi nhận cuối văn bản (`recipients`)            | Critical + optional     | F1@5%         | trích xuất + đánh giá                                              |
| Họ tên người ký (`signer`)                      | Critical + optional     | F1 Exact      | trích xuất + đánh giá                                              |
| Kính gửi đầu văn bản (`first_recipients`)      | Critical + optional     | F1@5%         | trích xuất + đánh giá                                              |
| Chức danh/thẩm quyền người ký (`signer_title`) | Critical + optional     | F1@5%         | trích xuất + đánh giá                                              |
| Địa danh (`province`)                              | Non-critical + optional | F1 Exact      | trích xuất + đánh giá                                              |
| Ngày tiếp nhận (`receiverDate`)                   | Out of scope            | Không chấm  | giữ key API, luôn trả`""`, không trích xuất, không đánh giá |

Trường text hoặc ngày không tìm thấy trả `""`, không trả `null`. `priority_level` và `security_level` mặc định là `0_BÌNH THƯỜNG` khi tài liệu không có dấu hoặc không đọc được dấu.

Các enum hợp lệ:

- `priority_level`: `0_BÌNH THƯỜNG`, `1_HỎA TỐC`, `2_KHẨN`, `3_THƯỢNG KHẨN`.
- `security_level`: `0_BÌNH THƯỜNG`, `1_MẬT`, `2_TỐI MẬT`, `3_TUYỆT MẬT`.

Không có `article_one` trong hợp đồng mới. Không suy đoán giá trị từ tên file, metadata ngoài PDF hoặc GT.

## 2. Ranh giới văn bản thứ nhất

Pipeline trích xuất văn bản chính đầu tiên trong PDF.

- `document_start_page` dựa trên header hành chính: Quốc hiệu/Tiêu ngữ, cơ quan ban hành, số ký hiệu hoặc trích yếu. Bìa hay trang rác trước văn bản có thể bị bỏ qua.
- `document_end_page` dựa trên phần kết thúc: Nơi nhận, thẩm quyền ký, chữ ký hoặc con dấu.
- Khi phát hiện header độc lập của văn bản kế tiếp, `next_document_start_page` đánh dấu điểm dừng; không lấy trường của phụ lục hay văn bản đính kèm làm trường của văn bản thứ nhất.
- Người ký và chức danh lấy tại trang đầu tiên có vùng ký hợp lệ trong phạm vi văn bản thứ nhất.

## 3. Quy tắc giá trị đầu ra

### 3.1. Ghép dòng và nhiều giá trị

- Một giá trị bị xuống dòng, gồm `title`, `officeSender` và một cụm ký trong `signer_title`, được nối bằng đúng một dấu cách.
- Một cụm ký là các dòng chức vụ/thẩm quyền ký, dấu mộc/con dấu và họ tên người ký của cùng một người/vị trí ký. Nhiều dòng chức vụ trong cùng một cụm ký chỉ nối bằng dấu cách, không dùng `; `. Ví dụ `KT. CHỦ TỊCH PHÓ CHỦ TỊCH` là một cụm ký nên giữ nguyên nối cách.
- Nhiều giá trị độc lập của `recipients`, `first_recipients` được phân cách bằng `; `, giữ thứ tự đọc. Quy tắc nối mảnh OCR: xuống dòng sau dấu `,` là cùng một giá trị (nối cách, nuốt gạch đầu dòng của dòng tiếp); xuống dòng trần không có `,`/`;` phía trước thì mở mục mới (`; `). Dấu phân cách có sẵn (`; `, gạch đầu dòng, `/`) luôn được giữ.
- `signer` và `signer_title` có nhiều cụm ký khác nhau (chức vụ + dấu mộc + họ tên khác nhau) mới phân cách các cụm bằng `; `, giữ thứ tự đọc; bên trong mỗi cụm nối bằng dấu cách. Ví dụ văn bản liên tịch hai chữ ký: `signer_title` là `SỞ GDCK HÀ NỘI TM. HỘI ĐỒNG QUẢN TRỊ CHỦ TỊCH; SỞ GDCK TP.HCM TM. HỘI ĐỒNG QUẢN TRỊ CHỦ TỊCH`, `signer` là `Nguyễn Thành Long; Trần Đắc Sinh`.
- `officeSender` là một giá trị cơ quan ban hành; nhiều dòng được nối bằng dấu cách. KHÔNG ÁP DỤNG quy tắc phân cấp của API cũ`[Cơ quan con]/[Cơ quan cha]`.
- Raw OCR và xuống dòng gốc vẫn được giữ trong trace evidence.

### 3.2. Chuẩn hóa `code` ở đầu ra API

Theo đúng thứ tự:

1. Thay toàn bộ dấu `.` thành dấu cách.
1. Bỏ khoảng trắng đầu và cuối.
3. Rút nhiều whitespace liên tiếp thành một dấu cách.
4. Xóa whitespace quanh `/` và `-`.
5. Đổi các dấu cách còn lại thành `-`.
6. Rút nhiều dấu `-` liên tiếp thành một dấu `-`.
7. Bỏ `;`, `,`, `:` thừa ở cuối.

Ví dụ `4977 / BVHTTDL  VP:` thành `4977/BVHTTDL-VP`.

### 3.3. Xác định vùng `code`

Ưu tiên hình học trước, regex sau:

1. Xác định Quốc hiệu/Tiêu ngữ ở vùng trên bên phải.
2. Xác định `officeSender` ở vùng trên bên trái tương đối với Quốc hiệu/Tiêu ngữ.
3. Xác định vùng địa danh và ngày ban hành ngay dưới Quốc hiệu/Tiêu ngữ.
4. Giới hạn vùng tìm `code` ở bên trái vùng địa danh/ngày và dưới `officeSender`.
5. Trong vùng đó, ưu tiên anchor `Số:` hoặc `Số` rồi kiểm tra cấu trúc số/ký hiệu theo văn bản hành chính và các dạng hợp lệ đã quan sát trong tập benchmark.
6. Loại khối Công báo, căn cứ/thân văn bản, địa chỉ/liên hệ, số trang và số điều.

Không thêm quy tắc theo tên file hoặc đáp án GT. Dạng không bắt đầu bằng chữ số chỉ được nhận khi anchor và vị trí đủ mạnh; không nới regex toàn cục.

### 3.4. Ngày và địa danh

- `documentDate` và `province` được tìm trong vùng header mặc định.
- Khi không tìm được `documentDate`, hiện tại trả `""`. Fallback lấy câu “thông qua ngày...” ở trang ký cuối đang tạm bỏ; chỉ được thử lại trong một thí nghiệm riêng và phải chứng minh cải thiện không hồi quy.
- Fallback ngày, nếu được thử sau này, chỉ có quyền trả `documentDate`; không được xóa hoặc ghi đè `province`.
- `receiverDate` ngoài phạm vi vòng tối ưu hiện tại: pipeline luôn trả `""` (giữ key cho ổn định schema), không trích xuất từ dấu đến/văn bản đến và benchmark không chấm trường này.

### 3.5. Các trường còn lại

- `type` lấy hình thức văn bản chính, không lấy từ câu nhắc trong thân văn bản.
- Văn bản hợp nhất (`code` chứa `VBHN-`): `type` là hình thức của văn bản được hợp nhất (tên in lớn, căn giữa ở đầu văn bản như `THÔNG TƯ`, `NGHỊ ĐỊNH`), không lấy nhãn wrapper `VĂN BẢN HỢP NHẤT` ở góc trên bên trái làm `type`.
- `title` giữ nội dung có nghĩa và dấu câu nguồn; phần tiếp dòng được nối theo mục 3.1.
- `recipients` lấy vùng Nơi nhận ở phần kết thúc.
- `first_recipients` lấy Kính gửi ở đầu văn bản.
- `signer` giữ họ tên người ký theo nguồn; mỗi cụm ký một họ tên, nhiều cụm ký phân cách bằng `; ` theo mục 3.1.
- `signer_title` giữ chức danh/thẩm quyền ký theo cụm ký ở mục 3.1: trong cụm nối dòng bằng dấu cách, giữa các cụm phân cách bằng `; `.
- `priority_level` và `security_level` chỉ trả lớp khác mặc định khi có bằng chứng trong tài liệu.

## 4. Ba tầng dữ liệu

1. **Raw evidence:** `source_text`, OCR lines, bbox pixel và bbox chuẩn hóa được giữ nguyên để audit.
2. **API output:** áp dụng quy tắc nghiệp vụ ở mục 3.
3. **Benchmark normalization:** chỉ tạo bản chuẩn hóa để so sánh; không sửa raw evidence hay GT trên đĩa.

Chuẩn hóa benchmark chung: Unicode NFKC, `casefold`, trim và rút whitespace, giữ dấu tiếng Việt, bỏ dấu câu không mang nghĩa theo implementation. Từ metric version **2.2**, hai cách trình bày `ỦY`/`UỶ`, chỉ khi là một token riêng, được quy về `ủy` trước khi so sánh; không thay chuỗi con bên trong từ như `khuỷu`. Quy tắc chỉ tác động lên bản benchmark normalization, không sửa raw evidence, API output hay GT trên đĩa. So sánh/rescore phải dùng chung metric version; artifact v2.1 trở về trước giữ nguyên ý nghĩa lịch sử và cần được rescore riêng nếu đem so với v2.2. Riêng `code`, bỏ dấu `.` và toàn bộ whitespace nhưng giữ `/` và `-`. Ngày được parse về `dd/mm/yyyy`; enum được map về lớp chuẩn.

## 5. Metric, bucket và target

Với trường text có GT, `CER = (S + D + I) / len(normalized_GT)`. CER không bị giới hạn ở 1. Ngày và enum không dùng CER.

| Trường hợp                             | Bucket         | Đóng góp |
| ----------------------------------------- | -------------- | ----------- |
| GT có, prediction đúng                 | Exact          | TP          |
| GT có, text F1@5% có`0 < CER <= 0.05` | Acceptable     | TP          |
| GT có, prediction sai                    | Wrong          | FP + FN     |
| GT có, prediction rỗng                  | Missing        | FN          |
| GT rỗng, prediction có                  | Hallucination  | FP          |
| GT rỗng, prediction rỗng                | Correct Absent | TN          |

Nhóm Exact không có bucket Acceptable. `NEM` là tỷ lệ Exact trên các mẫu GT có giá trị. F1, precision, recall và hallucination rate được tính từ TP/FP/FN/TN ở trên.

### 5.1. Document Success@5%

**Document Success@5%** = tỷ lệ văn bản mà **tất cả required fields có trong Ground Truth đều đạt NCER ≤ 5% sau normalization** (metric version 2.1 trở lên).

- Required fields: `type`, `title`, `code`, `documentDate`, `officeSender`, `priority_level`, `security_level`.
- Một required field được tính là đạt khi bucket của nó (tái dùng `evaluate_field`, không implementation riêng) là `Exact` hoặc `Acceptable`. Với field nhóm Exact, `Acceptable` không tồn tại nên đạt đồng nghĩa khớp tuyệt đối; với ngày/enum, CER không áp dụng nên đạt đồng nghĩa parse/map đúng.
- Chỉ cần 1 required field fail → document fail (`document_success_at_5=false`, liệt kê trong `failed_required_fields`).
- Required field mà GT trống hoặc GT ghi `N/A` là không applicable: không đánh giá, không làm document fail. Document không có required field applicable nào được tính PASS rỗng (`evaluated_required_fields=0`).
- GT có value nhưng prediction thiếu (`Missing`) → document fail.
- Toàn dataset: `Document Success@5% = số document PASS / tổng số document được đánh giá` (mọi record trong artifact, kể cả document lỗi inference với prediction rỗng, đều nằm ở mẫu số).
- Target PoC/demo: `≥ 0.80`; stretch target: `≥ 0.90` (`DOCUMENT_SUCCESS_TARGET_POC/STRETCH` trong code, không hard-code ở notebook/report).
- Lưu trữ mỗi bundle: `document_success.csv` (`document_id`, `document_success_at_5`, `evaluated_required_fields`, `failed_required_fields`) và `summary.json → document_success_at_5` (`rate`, `passed_documents`, `evaluated_documents`, targets, `meets_poc`, `meets_stretch`).

Target hiện tại cho **cả 12 field được đánh giá**: **F1, precision, recall `>=0.85`; NEM `>=0.75`**. Hallucination rate giữ ngưỡng cũ: `<=0.01` cho mọi field trừ `province` (`<=0.02`). Không có target field cho `receiverDate`.

Trên slide/báo cáo, mỗi field hiển thị theo dạng **F1 (precision, recall) / NEM / VAI-style ACC (tham chiếu)**, đặt **target `0.85 (0.85, 0.85) / 0.75 / không áp dụng`** cạnh giá trị field thực tế. F1, NEM và VAI-style ACC là các chỉ số khác nhau; không lấy Document Success@5%, macro F1 hoặc ACC thay cho kết quả từng field. Trạng thái target trong artifact đã chấm bằng ngưỡng cũ chỉ có tính lịch sử; nếu muốn công bố trạng thái theo target mới, phải đối chiếu lại giá trị F1/precision/recall/NEM/hallucination trên đúng bundle, không sửa GT hay artifact gốc.

Thiếu mẫu số hoặc thiếu lớp enum phải báo `Chưa đánh giá đầy đủ`, không tính là đạt.

### 5.2. VAI-style ACC — metric tham chiếu bên cạnh NEM

Nguồn đối chiếu: datasheet Viettel AI `OCR.pdf`, trang 2 (trích xuất thông tin) và trang 3 (điều kiện đầu vào). Datasheet dùng `ACC = mean(AoC_i)`, `AoC_i = 1 - sum(S + D + I) / max(tổng ký tự GT, tổng ký tự AI trả ra)`; nhân 100 để hiển thị phần trăm. Đây không phải F1 kiểm tra thể thức hay điểm theo từ của chức năng chuyển toàn văn sang text.

**Tên báo cáo: “VAI-style ACC — chuẩn hóa nội bộ, chỉ tham chiếu”.** Datasheet chưa đặc tả đầy đủ normalization, căn chỉnh field và trường trống; giao thức dưới đây là lựa chọn nội bộ có version riêng `VAI_ACC_VERSION = 1.0`, không tuyên bố tái lập chính xác phép nghiệm thu VAI. Metric chính vẫn ở version 2.2; bucket, F1/precision/recall, NEM, hallucination, Document Success và target không thay đổi. Không thêm target ACC hay dùng mức 90% datasheet để quyết định `Đạt`.

- **Chuỗi so sánh:** tái dùng normalization benchmark hiện hành. Ngày parse được dùng dạng chuẩn; ngày không parse được dùng text chuẩn hóa của giá trị gốc để không làm mất output sai nhưng không rỗng. Enum dùng chuỗi lớp canonical (hoặc giá trị chuẩn hóa khi không map được). Ngày/enum chỉ nhận điểm ký tự trong metric phụ này; vẫn không dùng CER/dung sai cho metric chính.
- **Căn chỉnh:** tính Levenshtein riêng cho đúng cặp document-field, không nối toàn bộ field rồi căn chỉnh; giá trị đặt nhầm field không được khớp sang field khác. Giữ nguyên raw GT/prediction.
- **GT `N/A`:** loại field khỏi ACC, kể cả khi prediction có giá trị. GT trống không đồng nghĩa `N/A`: prediction có giá trị vẫn là nội dung thừa cần phạt.
- **Điểm mỗi ô:** `vai_acc = 1 - edits / max(len(GT), len(prediction))`. Một phía rỗng, phía còn lại có ký tự → 0; hai phía cùng rỗng sau chuẩn hóa → `null`, không cộng 100%. Điểm theo field là trung bình các ô có mẫu số, bao gồm missing/hallucination; báo số ô được chấm, số ô mẫu số 0 và số ô loại do `N/A`. Mẫu số này khác NEM (chỉ GT có giá trị).
- **Điểm văn bản:** `AoC_i = 1 - sum_field(edits) / max(sum_field(len(GT)), sum_field(len(prediction)))` trên scope đã chọn. Không lấy trung bình điểm field để thay AoC. Do cộng lỗi theo field nhưng dùng max của hai tổng độ dài, AoC có thể âm khi lỗi phân tán giữa các field; giữ nguyên công thức, không clamp âm hay cho nội dung sai field triệt tiêu lỗi.
- **ACC dataset:** trung bình AoC của các văn bản có mẫu số >0, mỗi văn bản có trọng số ngang nhau; không phải macro theo field hoặc tỷ lệ văn bản đạt. Văn bản mẫu số 0 giữ dòng `null`, báo rõ tổng document, document được chấm, document mẫu số 0 và số AoC âm. Document lỗi inference vẫn được chấm với prediction rỗng nếu GT trong scope có giá trị.
- **Hai scope độc lập:** `all_12` gồm 12 field nội bộ ở mục 1; `vai_common_6` gồm Số, ký hiệu văn bản (`code`, Critical + required), Ngày ban hành (`documentDate`, Critical + required), Cơ quan ban hành (`officeSender`, Critical + required), Loại văn bản (`type`, Critical + required), Họ tên người ký (`signer`, Critical + optional), Trích yếu/tiêu đề (`title`, Critical + required). Ngày tiếp nhận (`receiverDate`, Out of scope) không được chấm; scope sáu field không đại diện đầy đủ bảy field trong datasheet.
- **Điều kiện đối chiếu:** datasheet nêu tối thiểu 50 giấy tờ mỗi loại đáp ứng chất lượng đầu vào, gồm PDF scan ≥200 dpi, nội dung rõ và không bị che khuất; loại các trường bị dấu/logo che, đảo trang hoặc lẫn tài liệu. Benchmark nội bộ không tự loại tài liệu khó và chưa xác nhận đủ điều kiện này: ACC phải ghi “chưa đánh giá điều kiện đầu vào datasheet”, không kết luận nhà cung cấp đạt/không đạt cam kết từ con số nội bộ.

Lưu `field_errors.csv` với `vai_acc`, số edits và độ dài/mẫu số phục vụ audit; `metrics.csv` thêm `vai_acc` cạnh `nem` cùng coverage. Lưu `vai_acc_documents.csv` theo document/scope và `summary.json → vai_acc` với version, normalization version, unit, aggregation, điều kiện đầu vào và hai scope. Số lưu trên thang ratio; phần trăm chỉ là cách hiển thị. Artifact cũ thiếu ACC là “chưa tính”, không phải 0; rescore sang thư mục mới, không ghi đè artifact gốc và không gọi việc thêm metric là cải thiện mô hình.

## 6. Các chế độ chạy

| Chế độ         | Thực hiện                                        | Có thể chứng minh                                                                     |
| ----------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Full inference    | PDF → layout → OCR → hậu xử lý → extraction | Chất lượng end-to-end, ảnh/trace mới, thời gian và tài nguyên của lượt chạy |
| Extraction replay | Chạy extraction mới trên OCR/layout đã lưu   | Tác động riêng của luật extraction; không đại diện thay đổi OCR/layout       |
| Rescore           | Chấm lại prediction đã lưu                    | Tác động của metric/GT hiện tại; không phải cải thiện mô hình                |

So sánh trước/sau phải dùng cùng tập document, cùng 12 field được đánh giá (API vẫn trả đủ 13 key, `receiverDate` luôn rỗng và không chấm), cùng metric version và cùng snapshot GT. Công cụ so sánh phải nạp GT hiện tại cho cả hai phía; tuyệt đối không so trực tiếp hai `summary.json` được tạo từ hai phiên bản GT khác nhau.

## 7. Artifact và trace

Mỗi bundle tối thiểu có `manifest.json`, `predictions.jsonl`, `summary.json`, `metrics.csv`, `field_errors.csv`, `document_success.csv`, `enum_metrics.csv`, `pipeline_config.json` nếu có, `source_snapshot/` và `evidence/`.

Mỗi tài liệu có thư mục dễ tìm theo tên PDF:

```text
evidence/<pdf_stem>/trace.json
evidence/<pdf_stem>/page_1.png
evidence/<pdf_stem>/page_2.png
```

Phải có `unique(trace_path) == document_count`. Mỗi record trỏ tới trace cùng `document_id`; trace v2 thiếu identity hoặc sai identity không được dùng làm bằng chứng. `trace.json` chỉ có một nguồn kết quả extraction là `extraction.fields`; không giữ đồng thời kết quả baseline ở `fields` và kết quả mới ở nhánh khác.

Trace v2 có tối thiểu `version`, `document_id`, `source_filename`, `pdf_path`, `pages`, `markdown` và `extraction.fields`. Mỗi page trỏ tới ảnh đã copy trong cùng artifact. Mỗi evidence có page, rule, source text, bbox/bbox chuẩn hóa và cờ độ tin cậy hình học khi có.

Trang do người review chọn khi field không có evidence chỉ là trang kiểm tra, chưa phải vị trí GT xác nhận.

## 8. Đo tài nguyên

Mỗi PDF full inference ghi:

- thời gian wall-clock và thời gian pipeline;
- RAM trung bình/đỉnh của tiến trình;
- process VRAM trung bình/đỉnh (`avg_vram_mb`, `peak_vram_mb`);
- framework allocator trung bình/đỉnh (`avg_torch_allocated_mb`, `peak_torch_allocated_mb`, `avg_paddle_allocated_mb`, `peak_paddle_allocated_mb`, `avg_framework_allocated_mb`, `peak_framework_allocated_mb`);
- device VRAM trung bình/đỉnh (`avg_device_vram_mb`, `peak_device_vram_mb`);
- chênh lệch device so với nền sau nạp model (`device_vram_delta_from_preload_mb`);
- số mẫu, nguồn đo, GPU UUID/tên và trạng thái GPU dùng chung khi xác định được.

Phạm vi và nguồn đo (mọi field phải ghi cả hai, không suy diễn chéo):

- **Process VRAM** (`avg_vram_mb`, `peak_vram_mb`): bộ nhớ GPU của đúng tiến trình benchmark, chỉ đo bằng NVML per-process (`pynvml.compute-process.usedGpuMemory`, ưu tiên) hoặc `nvidia-smi --query-compute-apps=pid,used_gpu_memory` khớp PID (`nvidia-smi.compute-apps.pid`). Khớp PID phải bao gồm mọi alias host/container qua `NSpid` trong `/proc/self/status`. Hàng `[N/A]` (ví dụ WSL/WDDM) bị bỏ qua, không quy về 0. Nếu không có nguồn OS nào quy được byte về đúng PID thì giá trị là `null` kèm nguồn/ghi chú; không bao giờ thay bằng 0 hay bằng số allocator.
- **Framework allocation** (`torch_allocated_mb`, `paddle_allocated_mb`, `framework_allocated_mb`): chỉ số chẩn đoán bổ sung từ `torch.cuda.memory_allocated` và `paddle.device.cuda.memory_allocated`. Hai counter được đọc liền nhau trong cùng một mẫu và tổng `framework_allocated_mb` chỉ cộng các counter của cùng thời điểm đó. Chúng chỉ đếm tensor do allocator quản lý, không gồm CUDA context, reserved pool, fragmentation hay thư viện khác, nên luôn nhỏ hơn process VRAM thực và không được gán nhãn process VRAM.
- **Device VRAM** (`avg_device_vram_mb`, `peak_device_vram_mb`): toàn bộ GPU, mọi tiến trình. Nguồn ưu tiên NVML (`pynvml.device_memory_used`), sau đó `nvidia-smi memory.used`. Không bao giờ trộn với process VRAM.
- **Chênh lệch so với nền** (`device_vram_delta_from_preload_mb` = device đỉnh trong file trừ nền device sau nạp model; model-load delta tương tự ở `summary.performance`): chỉ là ước lượng có điều kiện, chỉ được diễn giải khi `shared_device is False` và `resource_delta_comparable is True` (GPU đã xác nhận không có tiến trình cạnh tranh trong suốt lượt đo). Nền thay đổi theo tiến trình khác trên GPU nên số tuyệt đối vẫn được báo kèm provenance, nhưng delta không được dùng làm process VRAM.

Resource của extraction replay là `null` vì replay không chạy model. Không báo delta tài nguyên giữa các lượt không cùng giao thức đo và điều kiện phần cứng; vẫn có thể báo số tuyệt đối cùng provenance.

## 9. Phân tích lỗi

Notebook và báo cáo phải hiển thị lỗi đại diện của từng field dưới target: ảnh trang, crop/bbox đúng hệ tọa độ, GT, prediction, OCR trung gian và trace tương ứng.

**Bốn nhóm nguyên nhân chính để báo cáo phân bố lỗi:**

| Nhóm hiển thị   | Bao gồm các nhãn chi tiết/hiện tượng                                                                   | Lưu ý                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `OCR/chính tả` | Nhận dạng ký tự sai, thiếu/dính chữ; chữ viết tay là yếu tố góp phần khi có evidence           | Không quy mọi lỗi trên file có chữ viết tay thành lỗi chữ viết tay. |
| `Trích xuất`   | `Extraction / Heuristics`, `Vùng layout trộn nội dung`, `Crop/bbox sai`                              | Gộp lỗi chọn vùng, cắt/ghép và hậu xử lý có OCR nguồn phù hợp.   |
| `Dấu mộc`      | Dấu khẩn/mật, dấu đè vùng cần đọc khi ảnh/trace ủng hộ                                           | Không suy ra nguyên nhân chỉ từ enum GT khác prediction.                 |
| `Khác`          | `Nghi vấn GT`, trường hợp thiếu evidence/chưa thể kết luận và nguyên nhân ngoài ba nhóm trên | Không coi nghi vấn GT là GT sai đã được xác nhận.                    |

Các artifact phân tích cũ có thể còn nhãn chi tiết `Chưa xác định`; khi **hiển thị thống kê** gộp nhãn đó vào `Khác`, không sửa artifact gốc và không đổi nhãn thầm lặng trong trace. Mỗi ô lỗi (`document_id`, `field_name`) thuộc đúng một nhóm chính; lỗi cùng một văn bản nhưng khác field vẫn là các ô riêng.

Phân bố nguyên nhân phải ghi rõ **bundle, mode chạy, tập 12 field, các bucket tính vào mẫu số, cỡ mẫu và nguồn phân loại**. Chỉ dùng `Wrong`, `Missing`, `Hallucination`; không tính `Exact`, `Acceptable`, `Correct Absent` hoặc `receiverDate`. Phải kiểm tra trực tiếp từng ô lỗi: đối chiếu text layer PDF nếu có, ảnh render trang đầu/cuối đã detect và trang/vùng liên quan đến field, cùng OCR/layout trace và crop/bbox. Ghi bằng chứng quan sát được và lý do cho nhãn; không suy nguyên nhân chỉ từ bucket, metadata, hoặc chuỗi GT/prediction. Nếu sau khi kiểm tra vẫn thiếu căn cứ, gán `Chưa xác định` (nhóm `Khác`) và nêu rõ điều gì chưa thể xác minh; không đoán. Bảng theo từng ô phải giữ liên kết tới trang, block/region, bbox và trace khi có. Số liệu và kết luận riêng của mỗi lượt chạy chỉ thuộc report/artifact gắn với bundle đó, không đưa vào spec này. Không lấy bảng nguyên nhân của bundle/split khác làm phân bố cho full inference 100 PDF.

`Chữ viết tay` là yếu tố góp phần dưới `OCR/chính tả`, chỉ xét cho `code`, `documentDate`. `has_handwriting=true` chỉ cho phép ghi “Lỗi OCR (khả năng cao do chữ viết tay)”; chỉ ghi đã xác nhận khi evidence vùng field chứng minh trực tiếp.

Báo cáo so sánh tối thiểu gồm:

- `experiment_log.csv`: F1/NEM, target, số cải thiện/hồi quy và quyết định giữ/bỏ/chờ review.
- `sample_regressions.csv` và `sample_improvements.csv`: document, field, GT, prediction hai phía, trace/evidence và trạng thái review.
- Hồi quy mẫu là chuyển từ `Exact`/`Acceptable`/`Correct Absent` sang bucket lỗi; cải thiện là chiều ngược lại. Chuyển giữa `Wrong`, `Missing` và `Hallucination` được báo riêng để review, không tự gọi là hồi quy hay cải thiện.
- ma trận chuyển bucket đầy đủ 6×6 cho từng split và từng loại lượt chạy.
- `resource_comparison.csv`: dòng từng tài liệu và tổng hợp, kèm phạm vi/nguồn đo và cờ có thể so sánh delta hay không.

Các split cộng dồn là `<=2` trang, `<=5` trang và `<=14` trang. Baseline phải được bảo tồn; output mới dùng thư mục mới. Chỉ giữ thay đổi khi có lợi ích đo được và không làm giảm chất lượng tổng thể hoặc field quan trọng; thử nghiệm không hiệu quả cũng phải ghi lại.
