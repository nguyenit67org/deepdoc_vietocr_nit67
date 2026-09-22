# Chuẩn OCR/KIE và benchmark văn bản hành chính

Tài liệu này là nguồn chuẩn hiện hành cho API 13 trường VBHC, quy tắc trích xuất, bằng chứng và benchmark. Các quy tắc còn hiệu lực từ đặc tả API cũ đã được tổng hợp trực tiếp tại đây; implementation và test không cần tham chiếu ngược đặc tả cũ.

## 1. Hợp đồng đầu ra

Pipeline trả đúng một phần tử trong `information`, gồm 13 trường sau. Mỗi trường có `type: "string"` và `value` là chuỗi.

| Field | Nhóm | Metric chính |
| --- | --- | --- |
| `type` | Critical + required | F1 Exact |
| `title` | Critical + required | F1@5% |
| `code` | Critical + required | F1 Exact |
| `documentDate` | Critical + required | F1 Exact |
| `officeSender` | Critical + required | F1@5% |
| `priority_level` | Critical + required | F1 Exact |
| `security_level` | Critical + required | F1 Exact |
| `recipients` | Critical + optional | F1@5% |
| `signer` | Critical + optional | F1 Exact |
| `first_recipients` | Critical + optional | F1@5% |
| `signer_title` | Critical + optional | F1@5% |
| `province` | Non-critical + optional | F1 Exact |
| `receiverDate` | Non-critical + optional | F1 Exact |

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

- Một giá trị bị xuống dòng, gồm `title`, `officeSender` và một chức danh trong `signer_title`, được nối bằng đúng một dấu cách.
- Nhiều giá trị độc lập của `recipients`, `first_recipients`, `signer` và nhiều chức danh độc lập trong `signer_title` được phân cách bằng `; `, giữ thứ tự đọc.
- `officeSender` là một giá trị cơ quan ban hành; nhiều dòng được nối bằng dấu cách. Không áp dụng quy tắc cũ `[Cơ quan con]/[Cơ quan cha]`.
- Raw OCR và xuống dòng gốc vẫn được giữ trong trace evidence.

### 3.2. Chuẩn hóa `code` ở đầu ra API

Theo đúng thứ tự:

1. Bỏ khoảng trắng đầu và cuối.
2. Xóa toàn bộ dấu `.`.
3. Rút nhiều whitespace liên tiếp thành một dấu cách.
4. Xóa whitespace quanh `/` và `-`.
5. Đổi các dấu cách còn lại thành `-`.
6. Rút nhiều dấu `-` liên tiếp thành một dấu `-`.
7. Bỏ `;`, `,`, `:` thừa ở cuối.

Ví dụ ` 4977 / BVHTTDL  VP: ` thành `4977/BVHTTDL-VP`.

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
- `receiverDate` chỉ lấy từ dấu đến/văn bản đến, không thay bằng ngày ban hành hay ngày chạy pipeline.

### 3.5. Các trường còn lại

- `type` lấy hình thức văn bản chính, không lấy từ câu nhắc trong thân văn bản.
- `title` giữ nội dung có nghĩa và dấu câu nguồn; phần tiếp dòng được nối theo mục 3.1.
- `recipients` lấy vùng Nơi nhận ở phần kết thúc.
- `first_recipients` lấy Kính gửi ở đầu văn bản.
- `signer` giữ họ tên người ký theo nguồn.
- `signer_title` giữ chức danh/thẩm quyền ký, nối dòng bằng dấu cách.
- `priority_level` và `security_level` chỉ trả lớp khác mặc định khi có bằng chứng trong tài liệu.

## 4. Ba tầng dữ liệu

1. **Raw evidence:** `source_text`, OCR lines, bbox pixel và bbox chuẩn hóa được giữ nguyên để audit.
2. **API output:** áp dụng quy tắc nghiệp vụ ở mục 3.
3. **Benchmark normalization:** chỉ tạo bản chuẩn hóa để so sánh; không sửa raw evidence hay GT trên đĩa.

Chuẩn hóa benchmark chung: Unicode NFKC, `casefold`, trim và rút whitespace, giữ dấu tiếng Việt, bỏ dấu câu không mang nghĩa theo implementation. Riêng `code`, bỏ dấu `.` và toàn bộ whitespace nhưng giữ `/` và `-`. Ngày được parse về `dd/mm/yyyy`; enum được map về lớp chuẩn.

## 5. Metric, bucket và target

Với trường text có GT, `CER = (S + D + I) / len(normalized_GT)`. CER không bị giới hạn ở 1. Ngày và enum không dùng CER.

| Trường hợp | Bucket | Đóng góp |
| --- | --- | --- |
| GT có, prediction đúng | Exact | TP |
| GT có, text F1@5% có `0 < CER <= 0.05` | Acceptable | TP |
| GT có, prediction sai | Wrong | FP + FN |
| GT có, prediction rỗng | Missing | FN |
| GT rỗng, prediction có | Hallucination | FP |
| GT rỗng, prediction rỗng | Correct Absent | TN |

Nhóm Exact không có bucket Acceptable. `NEM` là tỷ lệ Exact trên các mẫu GT có giá trị. F1, precision, recall và hallucination rate được tính từ TP/FP/FN/TN ở trên.

Target hiện tại cho mọi field là F1, NEM và recall `>=0.95`, precision `>=0.97`, hallucination `<=0.01`, ngoại trừ:

- `province`: precision `>=0.90`, hallucination `<=0.02`.
- `receiverDate`: F1/NEM/recall `>=0.75` hiện tại, `>=0.85` ở mốc kế tiếp; precision `>=0.90`, hallucination `<=0.02`.

Thiếu mẫu số hoặc thiếu lớp enum phải báo `Chưa đánh giá đầy đủ`, không tính là đạt.

## 6. Các chế độ chạy

| Chế độ | Thực hiện | Có thể chứng minh |
| --- | --- | --- |
| Full inference | PDF → layout → OCR → hậu xử lý → extraction | Chất lượng end-to-end, ảnh/trace mới, thời gian và tài nguyên của lượt chạy |
| Extraction replay | Chạy extraction mới trên OCR/layout đã lưu | Tác động riêng của luật extraction; không đại diện thay đổi OCR/layout |
| Rescore | Chấm lại prediction đã lưu | Tác động của metric/GT hiện tại; không phải cải thiện mô hình |

So sánh trước/sau phải dùng cùng tập document, cùng 13 field, cùng metric version và cùng snapshot GT. Công cụ so sánh phải nạp GT hiện tại cho cả hai phía; tuyệt đối không so trực tiếp hai `summary.json` được tạo từ hai phiên bản GT khác nhau.

## 7. Artifact và trace

Mỗi bundle tối thiểu có `manifest.json`, `predictions.jsonl`, `summary.json`, `metrics.csv`, `field_errors.csv`, `enum_metrics.csv`, `pipeline_config.json` nếu có, `source_snapshot/` và `evidence/`.

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
- process VRAM trung bình/đỉnh;
- device VRAM trung bình/đỉnh;
- số mẫu, nguồn đo, GPU UUID/tên và trạng thái GPU dùng chung khi xác định được.

Process VRAM ưu tiên `nvidia-smi` theo PID, rồi mới dùng allocator của Torch/Paddle. Device VRAM ưu tiên NVML, sau đó `nvidia-smi`. Hai phạm vi không được trộn. Nếu mọi cách thất bại, giá trị là `null` kèm nguồn/ghi chú; không thay bằng 0.

Resource của extraction replay là `null` vì replay không chạy model. Không báo delta tài nguyên giữa các lượt không cùng giao thức đo và điều kiện phần cứng; vẫn có thể báo số tuyệt đối cùng provenance.

## 9. Phân tích lỗi

Notebook và báo cáo phải hiển thị lỗi đại diện của từng field dưới target: ảnh trang, crop/bbox đúng hệ tọa độ, GT, prediction, OCR trung gian và trace tương ứng.

Taxonomy nguyên nhân chính:

- `OCR/chính tả`
- `Dấu mộc`
- `Vùng layout trộn nội dung`
- `Crop/bbox sai`
- `Extraction / Heuristics`
- `Nghi vấn GT`
- `Chưa xác định`

`Chữ viết tay` là yếu tố góp phần dưới `OCR/chính tả`, chỉ xét cho `code`, `documentDate`, `receiverDate`. `has_handwriting=true` chỉ cho phép ghi “Lỗi OCR (khả năng cao do chữ viết tay)”; chỉ ghi đã xác nhận khi evidence vùng field chứng minh trực tiếp.

Báo cáo so sánh tối thiểu gồm:

- `experiment_log.csv`: F1/NEM, target, số cải thiện/hồi quy và quyết định giữ/bỏ/chờ review.
- `sample_regressions.csv` và `sample_improvements.csv`: document, field, GT, prediction hai phía, trace/evidence và trạng thái review.
- Hồi quy mẫu là chuyển từ `Exact`/`Acceptable`/`Correct Absent` sang bucket lỗi; cải thiện là chiều ngược lại. Chuyển giữa `Wrong`, `Missing` và `Hallucination` được báo riêng để review, không tự gọi là hồi quy hay cải thiện.
- ma trận chuyển bucket đầy đủ 6×6 cho từng split và từng loại lượt chạy.
- `resource_comparison.csv`: dòng từng tài liệu và tổng hợp, kèm phạm vi/nguồn đo và cờ có thể so sánh delta hay không.

Các split cộng dồn là `<=2` trang, `<=5` trang và `<=14` trang. Baseline phải được bảo tồn; output mới dùng thư mục mới. Chỉ giữ thay đổi khi có lợi ích đo được và không làm giảm chất lượng tổng thể hoặc field quan trọng; thử nghiệm không hiệu quả cũng phải ghi lại.
