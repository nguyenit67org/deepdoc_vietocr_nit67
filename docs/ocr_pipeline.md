# Pipeline xử lý PDF trong `process_pdf()`

## Tổng quan

`process_pdf()` chuyển một tệp PDF thành **nội dung tài liệu đã sắp xếp theo thứ tự đọc và kết quả trích xuất VBHC có cấu trúc**.

```text
PDF
 → Kết xuất ảnh trang theo từng nhóm
 → Cắt khoảng trắng / tùy chọn hiệu chỉnh góc xoay
 → Phát hiện bố cục
 → Tạo khung khối văn bản và bảng
 → Xử lý bảng nếu được bật
 → Phát hiện dòng chữ → cắt ảnh dòng → nhận dạng chữ
 → Gán chữ đã nhận dạng vào các khối bố cục
 → Ghép đoạn văn và sắp xếp thứ tự đọc
 → Tùy chọn hiệu chỉnh văn bản
 → Tổng hợp tất cả các trang
 → Tạo JSON / Markdown và trích xuất các trường VBHC
 → Lưu tệp và trả về kết quả trích xuất
```

**Lưu ý:** xử lý ảnh và suy luận model được thực hiện **theo từng nhóm trang**, còn bước trích xuất trường cuối cùng sử dụng **toàn bộ tài liệu**.

## Model và cấu hình hiện tại

Cấu hình trong `conf/local.pipeline_conf.yaml` ghi đè các giá trị tương ứng trong cấu hình cơ sở.

| Thành phần | Cấu hình hiện tại |
|---|---|
| Kết xuất PDF | 200 DPI; mỗi nhóm tối đa 64 trang |
| Cắt khoảng trắng | Bật |
| Hiệu chỉnh độ nghiêng / hướng trang | Tắt |
| Phát hiện bố cục | **PP-DocLayout_plus-L** |
| Phát hiện chữ | **DeepDoc `det.onnx`** |
| Nhận dạng chữ | **FastOCR theo kiến trúc VietOCR `vgg_seq2seq`** |
| Bảng | **Tắt trong cấu hình local**; cấu hình cơ sở bật TSR |
| Hiệu chỉnh văn bản | Tắt |
| Debug | Bật trong cấu hình local |

Nguồn: [nạp cấu hình](../module/pipeline/config.py#L6-L8), [cấu hình cơ sở](../conf/pipeline_conf.yaml#L1-L95), [cấu hình local](../conf/local.pipeline_conf.yaml#L1-L85), [debug và hiệu chỉnh văn bản trong cấu hình local](../conf/local.pipeline_conf.yaml#L128-L161).

## Các bước xử lý

### 1. Khởi tạo yêu cầu

**Đầu vào:** đường dẫn PDF và tên tệp nguồn/tên hiển thị tùy chọn.

`process_pdf()`:

- Bắt đầu đo thời gian xử lý.
- Xác định tên tài liệu.
- Đếm số trang PDF.
- Tạo thư mục đầu ra của tài liệu và thư mục `pages/`.
- Khởi tạo dữ liệu theo dõi debug riêng cho yêu cầu nếu debug được bật.

**Đầu ra:** các thư mục, thông tin tài liệu và danh sách dùng để tổng hợp kết quả.

Các model đã được khởi tạo bởi `build_pipeline()`; chúng không được nạp lại cho từng trang.

Nguồn: [khởi tạo](../module/pipeline/document_pipeline.py#L93-L125), [xây dựng pipeline](../module/pipeline/document_pipeline.py#L929-L942).

### 2. Kết xuất một nhóm trang PDF

**Đầu vào:** PDF và phạm vi trang hiện tại.

`load_pdf_page_window()` sử dụng `pdf2image` để kết xuất các trang liên tiếp thành **ảnh PIL**. Kích thước ảnh gốc được ghi nhận trước khi tiền xử lý.

Ví dụ, với PDF 150 trang và kích thước nhóm là 64:

```text
Nhóm 1: trang 1–64
Nhóm 2: trang 65–128
Nhóm 3: trang 129–150
```

**Đầu ra:** danh sách ảnh trang được truyền vào `_process_pages_batch()`.

Cách này giới hạn lượng bộ nhớ dành cho ảnh đã kết xuất. Hàm xử lý batch cũng có thể chia nhỏ danh sách nếu số trang vượt giới hạn.

Nguồn: [vòng lặp kết xuất](../module/pipeline/document_pipeline.py#L127-L145), [hàm nạp PDF](../module/pipeline/loader.py#L17-L38), [hàm chia nhóm](../module/pipeline/document_pipeline.py#L334-L369).

### 3. Tiền xử lý ảnh trang

**Đầu vào:** ảnh PIL đã kết xuất.

Các bước tiền xử lý gồm:

1. **Cắt khoảng trắng:** dùng các phép xử lý ảnh để xác định vùng nội dung và loại bỏ lề trắng quá lớn.
2. **Tùy chọn hiệu chỉnh độ nghiêng:** ước lượng độ nghiêng nhỏ của trang từ góc các hộp chữ.
3. **Tùy chọn hiệu chỉnh hướng trang:** sử dụng độ tin cậy OCR để chọn góc xoay giúp trang đứng đúng hướng.

Bước cắt khoảng trắng lưu độ dịch chuyển `(x, y)`. Nếu hiệu chỉnh hướng trang được thực hiện, các hộp chữ và mẫu đã nhận dạng ở bước này có thể được tái sử dụng khi chạy OCR.

**Hiện tại:** có cắt khoảng trắng; bỏ qua hiệu chỉnh độ nghiêng và hướng trang.

**Đầu ra:** ảnh đã tiền xử lý, độ dịch chuyển do cắt ảnh và kết quả OCR có thể tái sử dụng nếu có.

Nguồn: [điều phối tiền xử lý](../module/pipeline/document_pipeline.py#L413-L466), [thuật toán cắt khoảng trắng](../module/pipeline/whitespace.py#L38-L74), [logic hiệu chỉnh độ nghiêng](../module/pipeline/page_orientation.py#L26-L63).

### 4. Phát hiện bố cục tài liệu

**Đầu vào:** ảnh trang đã tiền xử lý.

**Model:** `PP-DocLayout_plus-L`.

Model phát hiện các vùng lớn trong tài liệu:

```text
tiêu đề / đoạn văn / bảng / hình ảnh / các loại vùng bố cục khác
```

Mỗi vùng có **loại, hộp giới hạn và độ tin cậy**.

Bước này khác với phát hiện dòng chữ: model bố cục xác định *cấu trúc tài liệu*, không nhận dạng ký tự bên trong vùng.

**Đầu ra:** các vùng bố cục của từng trang.

Một lời gọi batch ở cấp pipeline có thể được backend chia thành nhiều lượt suy luận theo giới hạn batch.

Nguồn: [lời gọi phát hiện bố cục](../module/pipeline/document_pipeline.py#L468-L484), [triển khai batching bố cục](../module/layout/pp_doclayout.py#L73-L127).

### 5. Tạo khung khối và tùy chọn xử lý bảng

**Đầu vào:** các vùng bố cục và ảnh đã tiền xử lý.

Pipeline tạo các khối ban đầu:

- **Văn bản:** nội dung ban đầu còn trống.
- **Bảng:** chuẩn bị ảnh cắt để xử lý bảng.
- **Bỏ qua:** chủ động không xử lý nội dung.

Nếu bảng được bật, pipeline cắt ảnh bảng với một khoảng lề nhỏ và hiệu chỉnh độ nghiêng. Bộ xử lý bảng điền nội dung có cấu trúc, đồng thời xử lý theo batch nếu backend hỗ trợ.

**Trong cấu hình local hiện tại:** bảng trở thành khối bị bỏ qua. Các hộp OCR chồng lấn với bảng cũng bị loại ở bước sau, tránh việc nội dung bảng xuất hiện trở lại dưới dạng văn bản chưa được gán vào khối.

**Đầu ra:** khung khối của từng trang, có nội dung bảng nếu xử lý bảng được bật.

Nguồn: [tạo khung khối](../module/pipeline/document_pipeline.py#L753-L797), [xử lý bảng](../module/pipeline/document_pipeline.py#L507-L543), [loại vùng bảng khi OCR](../module/pipeline/document_pipeline.py#L560-L583).

### 6. Phát hiện dòng chữ và tạo ảnh cắt

**Đầu vào:** ảnh trang đã tiền xử lý.

**Model:** DeepDoc `det.onnx`.

`prepare_ocr_page()`:

1. Chuyển ảnh PIL từ **RGB sang mảng NumPy BGR**.
2. Phát hiện các tứ giác bao quanh chữ, hoặc tái sử dụng hộp từ bước hiệu chỉnh hướng trang.
3. Loại các vùng không cần xử lý.
4. Tạo ảnh cắt từng dòng, thêm lề và dùng biến đổi phối cảnh để làm thẳng ảnh.
5. Không nhận dạng lại các mẫu đã được nhận dạng trong bước đánh giá hướng trang.

**Đầu ra:**

- Trạng thái phát hiện chữ của trang.
- Danh sách ảnh từng dòng cần nhận dạng mới.

Model phát hiện xử lý **ảnh trang**; model tiếp theo xử lý **ảnh cắt từng dòng**.

Nguồn: [chuẩn bị OCR](../module/pipeline/ocr_page.py#L59-L97).

### 7. Nhận dạng chữ trong nhóm trang hiện tại

**Đầu vào:** ảnh dòng chữ được thu thập từ tất cả các trang trong nhóm hiện tại.

**Model:** FastOCR `vgg_seq2seq`, nạp trọng số từ `fastocr/weight/vgg_seq2seq.pth`.

Bộ nhận dạng chuyển ảnh cắt sang RGB và xử lý theo chuỗi:

```text
Đặc trưng ảnh từ VGG → bộ mã hóa GRU → bộ giải mã GRU có attention → văn bản
```

Pipeline truyền vào một danh sách ảnh cắt chung; bên trong bộ nhận dạng, mỗi lượt suy luận được giới hạn ở **128 ảnh cắt**.

Sau đó kết quả được gán ngược lại:

```text
Kết quả nhận dạng → trang tương ứng → hộp phát hiện ban đầu
```

**Đầu ra:** các mục OCR theo trang, gồm:

```python
{
    "text": "...",
    "bbox": [x0, y0, x1, y1],
    "quad": [[x, y], ...],
    "bbox_row": [...],
}
```

`bbox_row` là tọa độ suy ra để hỗ trợ nhóm dòng; nó không làm xoay ảnh trang.

Nguồn: [nhận dạng và gán kết quả về trang](../module/pipeline/document_pipeline.py#L591-L616), [batching nhận dạng](../module/ocr/engine.py#L160-L177), [tạo mục OCR](../module/pipeline/ocr_page.py#L100-L185).

### 8. Gán chữ OCR vào các khối bố cục

**Đầu vào:** các mục OCR và khung khối bố cục.

Các phép hậu xử lý hình học:

1. Loại các khối bao ngoài dư thừa.
2. Gán các mục OCR vào khối dựa trên mức chồng lấn không gian.
3. Loại một số vùng hình ảnh quá lớn đã gom quá nhiều chữ.
4. Gán lại chữ của các vùng đó vào khối phù hợp.
5. Tạo thêm khối văn bản cho các mục OCR vẫn chưa được gán.

**Đầu ra:** các khối chứa danh sách mục chữ tương ứng.

**Không có model chạy ở bước này.**

Nguồn: [gán và thu hồi chữ](../module/pipeline/document_pipeline.py#L833-L871), [các hàm hỗ trợ gán chữ](../module/pipeline/text_mapping.py#L16-L130).

### 9. Ghép nội dung khối và sắp xếp thứ tự đọc

**Đầu vào:** các khối chứa mục chữ OCR.

Pipeline:

- Nhóm các mục chữ thành hàng.
- Sắp xếp các từ từ trái sang phải.
- Ghép các dòng văn bản thông thường thành đoạn.
- Giữ xuống dòng cho các khối dạng tiêu đề hoặc đầu trang.
- Sắp xếp khối theo thứ tự đọc, bao gồm trường hợp ảnh quét chứa hai trang cạnh nhau.

**Đầu ra:** các khối của trang đã được sắp xếp và có nội dung văn bản/bảng hoàn chỉnh.

Nguồn: [ghép nội dung và sắp xếp](../module/pipeline/document_pipeline.py#L881-L904), [nhóm hàng](../module/pipeline/reading_order.py#L72-L117), [logic thứ tự đọc](../module/pipeline/reading_order.py#L169-L210).

### 10. Tùy chọn hiệu chỉnh văn bản đã ghép

**Đầu vào:** các khối văn bản hoàn chỉnh, không rỗng.

Nếu được cấu hình, bộ hiệu chỉnh xử lý các khối theo batch **sau khi ghép dòng**, nhờ đó có nhiều ngữ cảnh ngôn ngữ hơn so với từng dòng OCR riêng lẻ.

- Không xử lý bảng.
- Nếu có ngoại lệ hoặc số kết quả không khớp số đầu vào, nội dung OCR gốc được giữ nguyên.

**Hiện tại:** bỏ qua vì hiệu chỉnh văn bản đang tắt.

**Đầu ra:** các khối đã hiệu chỉnh hoặc giữ nguyên.

Nguồn: [hiệu chỉnh tùy chọn](../module/pipeline/document_pipeline.py#L628-L665).

### 11. Tổng hợp trang và lưu ảnh xem trước

**Đầu vào:** các khối hoàn chỉnh, độ dịch chuyển do cắt ảnh và ảnh đã tiền xử lý của nhóm trang.

`process_pdf()` nối kết quả theo thứ tự tài liệu và lưu **đúng ảnh đã biến đổi mà layout/OCR sử dụng**.

Sau đó, hàm giải phóng tham chiếu ảnh của nhóm hiện tại và chuyển sang nhóm tiếp theo.

**Đầu ra:** các khối và thông tin hình học của toàn bộ tài liệu, cùng các tệp `pages/page_N.png`.

Nguồn: [tổng hợp và lưu ảnh trang](../module/pipeline/document_pipeline.py#L139-L161).

### 12. Tạo biểu diễn tài liệu và trích xuất trường

**Đầu vào:** các khối đã tổng hợp từ mọi trang.

Pipeline tạo hai loại kết quả khác nhau:

- **JSON khối và Markdown:** biểu diễn nội dung và cấu trúc tài liệu.
- **Kết quả VBHC:** các trường thông tin văn bản hành chính được trích xuất.

`extract_vbhc()` sử dụng các khối **trực tiếp**, không sử dụng Markdown hoặc JSON đã tạo. Hàm dùng luật và thông tin hình học để xác định ranh giới tài liệu, các trường ở đầu văn bản và thông tin kết thúc/chữ ký.

Hợp đồng API gồm **13 trường chuỗi** trong một phần tử `information`.

Thông tin hình học được đánh dấu không đáng tin cậy nếu bật hiệu chỉnh độ nghiêng hoặc hướng trang, vì độ dịch chuyển do cắt ảnh không đủ để mô tả phép xoay.

Nguồn: [tạo biểu diễn và trích xuất](../module/pipeline/document_pipeline.py#L163-L176), [trích xuất VBHC](../module/extract/vbhc_rules.py#L2119-L2199), [hợp đồng các trường](ocr_pipeline_benchmark_metrics.md#L5-L37).

### 13. Lưu kết quả và trả về dự đoán

Thư mục đầu ra chứa:

```text
<document>/
├── <source>.pdf
├── pages/page_N.png
├── output.json
├── output.md
└── prediction.json
```

Chế độ debug tạo thêm ảnh chẩn đoán và bằng chứng trích xuất.

**Giá trị trả về:** kết quả trích xuất có `processing_time`, cộng thêm đối tượng `debug` có cấu trúc nếu debug được bật. Giá trị này **không phải** đối tượng JSON khối được lưu trong `output.json`.

Nguồn: [lưu tệp và xây dựng phản hồi](../module/pipeline/document_pipeline.py#L179-L209).

---

**Tóm lại:** model bố cục xác định **các vùng tài liệu**, model phát hiện chữ tìm **các dòng chữ**, model nhận dạng đọc **ký tự**, các phép ghép theo hình học tạo **nội dung có thứ tự**, và bộ trích xuất theo luật chuyển nội dung đó thành **các trường VBHC**.
