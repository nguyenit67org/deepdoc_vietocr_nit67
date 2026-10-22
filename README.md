# FastOCR — DeepDoc + VietOCR

Pipeline OCR tiếng Việt cho tài liệu PDF (giấy tờ đất, giấy chứng nhận...): nhận PDF, trả về **JSON có cấu trúc** + **Markdown** (giữ định dạng bảng, tiêu đề, danh sách). Chạy được cả **CPU** lẫn **GPU** trên cùng 1 codebase.

## 1. Pipeline hoạt động thế nào

Với mỗi PDF, mỗi trang được xử lý qua các model sau:

| Bước           | Model                           | Vai trò                                              |
| ---------------- | ------------------------------- | ----------------------------------------------------- |
| Layout detection | PP-DocLayout_plus-L (PaddleOCR) | Tìm vùng text/bảng/hình/tiêu đề... trên trang |
| Text detection   | DeepDoc `det.onnx`            | Tìm bbox từng dòng chữ                            |
| Text recognition | VietOCR `vgg_seq2seq`         | Đọc nội dung chữ tiếng Việt                     |
| Table structure  | DeepDoc `tsr.onnx`            | Dựng lại bảng thành Markdown                      |

Sau đó pipeline map các box chữ vào đúng khối layout, sắp thứ tự đọc (trái→phải, có xử lý trang ghép đôi), rồi build ra `output.json` + `output.md`.

Chi tiết code nằm ở `module/pipeline/document_pipeline.py` (orchestration), `module/layout/`, `module/ocr/`, `module/tsr/`.

### Tài liệu quan trọng

- [Pipeline OCR](docs/ocr_pipeline.md): luồng xử lý `process_pdf()` từng bước, đầu vào/đầu ra và model sử dụng.
- [Hợp đồng API và benchmark metrics](docs/ocr_pipeline_benchmark_metrics.md): nguồn chuẩn cho 13 trường API, quy tắc đánh giá và bằng chứng trích xuất; đọc trước khi thay đổi extraction hoặc benchmark.
- [Quy luật bố cục văn bản hành chính](docs/vbhc_administrative_layout_rules.md): vị trí các thành phần thể thức và tín hiệu hình học phục vụ trích xuất VBHC.

## 2. Cấu trúc thư mục

```
module/           # Toàn bộ logic pipeline (layout, ocr, tsr, mapping, reading-order...)
server/           # FastAPI app + giao diện web đơn giản (server/static/index.html)
conf/             # Cấu hình pipeline (pipeline_conf.yaml + local.pipeline_conf.yaml override riêng máy)
vietocr/          # Code VietOCR vendor riêng (tool/model/config) + thư mục weight/
onnx/             # Model .onnx (det.onnx, tsr.onnx...) -- quản lý qua Git LFS
utils/            # read_config(), get_project_base_directory() -- tối giản, chỉ giữ phần thật sự dùng
Dockerfile / docker-compose.yml          # Build & chạy bản CPU
Dockerfile.gpu / docker-compose.gpu.yml  # Build & chạy bản GPU (Docker)
requirements.txt / requirements-gpu.txt  # Dependency tương ứng CPU/GPU
vastai_gpu_deploy_SUCCESS.txt            # Quy trình chạy GPU trực tiếp (không Docker) đã verify thành công
```

## 3. Cấu hình trước khi chạy (bắt buộc, cả CPU lẫn GPU)

Tạo `conf/local.pipeline_conf.yaml` (không commit vào git, riêng theo máy) trỏ đúng weight VietOCR đang dùng:

```yaml
ocr:
    vietocr_weight_path: 'vietocr/weight/<ten-file-weight>.pth'
    vietocr_base_config: 'vgg_seq2seq'
```

Các config khác (threshold, DPI, crop viền trắng, debug ảnh...) nằm ở `conf/pipeline_conf.yaml`, có thể override tương tự qua `local.pipeline_conf.yaml` mà không cần sửa file chung.

Server bắt buộc có biến môi trường `VOCR_API_KEY` (token ASCII không rỗng, không có
khoảng trắng). Thiếu key thì dừng startup trước khi nạp model. Local đặt key ngẫu
nhiên trong `.env.local`, không commit hoặc dùng lại key này cho UAT/staging/prod.
Xem `.env.example`; có thể sinh key bằng:

```bash
uv run --no-project python -c "import secrets; print(secrets.token_urlsafe(32))"
```

YAML chỉ quản lý pipeline/debug, không lưu API key. FastAPI không tự chọn/nạp file
`.env*`; phải dùng `uvicorn --env-file <file>` hoặc môi trường của tiến trình/container.

---

## 4. Chạy trên CPU (Docker)

Yêu cầu: đã cài Docker Desktop.

```bash
git clone https://github.com/daothihuyen64/deepdoc_vietocr_dh.git
cd deepdoc_vietocr_dh
# tạo conf/local.pipeline_conf.yaml như mục 3

# UAT/staging/prod: debug.enabled phải false trong cấu hình đã merge.
# VOCR_API_KEY phải được export vào môi trường shell từ secret trên máy chủ.
docker compose build
docker compose run --rm --service-ports -e VOCR_API_KEY ocr-api
```

Docker ở đây dùng cho API triển khai, không public UI debug. UI local chạy native
với socket loopback theo mục 6. Compose không tự truyền `VOCR_API_KEY` vào container
chỉ vì có file `.env` ở host; lệnh trên truyền biến đã export, không nhúng vào image.

Sửa `conf/local.pipeline_conf.yaml` sau này (đổi weight...) → chỉ cần `docker compose restart`, không cần build lại (file này được mount live qua `docker-compose.yml`). `vietocr/weight/` cũng được mount live tương tự.

---

## 5. Chạy trên GPU

Model trong pipeline khá nhẹ (VietOCR ~90MB, det/tsr onnx vài MB) — **không cần GPU cao cấp**, 8GB VRAM (vd RTX 3060/3060 Ti) là dư dùng. Yêu cầu driver NVIDIA hỗ trợ **CUDA ≥ 12.6**.

Có 2 cách — khuyến nghị dùng cách A.

### Cách A — Cài trực tiếp bằng pip (khuyến nghị)

Xem đầy đủ, chi tiết từng bước tại **[`vastai_gpu_deploy_SUCCESS.txt`](vastai_gpu_deploy_SUCCESS.txt)**. Tóm tắt:

```bash
# 1. Trên máy GPU (vd thuê Vast.ai, dùng image có sẵn CUDA/Python như vastai/pytorch)
apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 fonts-dejavu-core git

# 2. Clone (bỏ qua Git LFS lúc clone để tránh lỗi hết quota, xem bước 4)
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/daothihuyen64/deepdoc_vietocr_dh.git
cd deepdoc_vietocr_dh

# 3. Cài package -- THỨ TỰ QUAN TRỌNG: paddle trước, torch SAU CÙNG không ghim version
#    (paddlepaddle-gpu tự ghim cứng version nvidia-nccl-cu12/cudnn-cu12; cài torch
#    trước sẽ bị paddle đè version làm vỡ torch)
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install -r requirements-gpu.txt
pip install --force-reinstall torch torchvision

# 4. Copy riêng onnx/ + weight + config (không qua Git LFS, scp thẳng từ máy có sẵn)
#    scp -P <PORT> -r onnx/ conf/local.pipeline_conf.yaml vietocr/weight/*.pth root@<HOST>:/path/to/repo/...

# 5. Kiểm tra cả 2 framework trước khi chạy
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
python3 -c "from paddleocr import LayoutDetection; LayoutDetection(model_name='PP-DocLayout_plus-L')"

# 6. Chạy
# File env trên server chứa key riêng; debug.enabled=false trong config đã merge.
uv run uvicorn server.main:app --env-file .env.staging --host 0.0.0.0 --port 8000
```

Model tự động detect GPU (`torch.cuda.is_available()`) — không cần chỉnh gì thêm trong `conf/`, kể cả layout PP-DocLayout cũng tự chuyển `gpu:0` nếu có GPU.

### Cách B — Docker

```bash
# VOCR_API_KEY đã export, debug.enabled=false trong config đã merge.
docker compose -f docker-compose.gpu.yml build
docker compose -f docker-compose.gpu.yml run --rm --service-ports -e VOCR_API_KEY ocr-api
```

`Dockerfile.gpu` build từ base `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04`, cùng ghim version như cách A. Cần Docker daemon hỗ trợ GPU passthrough cho container lồng bên trong instance thuê (không phải nhà cung cấp/loại image nào cũng hỗ trợ tốt — xem thêm ghi chú trong `docker-compose.gpu.yml`).

---

## 6. Gọi API

```bash
curl -X POST https://<host>/api/v1/ocr/pdf \
  -H "Authorization: Bearer ${VOCR_API_KEY}" \
  -F "file=@document.pdf"
```

Response:

```json
{
  "information": [
    {
      "type": { "value": "Công văn", "type": "string" },
      "title": { "value": "V/v ...", "type": "string" }
    }
  ],
  "processing_time": 12.34
}
```

Mọi route `/api/v1/ocr/*` đều yêu cầu `Authorization: Bearer <access_key>`, kể cả
khi bật debug. Thiếu/sai key trả `401` với `WWW-Authenticate: Bearer` và
`{"detail":"Invalid or missing API key"}`. Client không gửi key qua query string.
Dùng HTTPS khi truy cập qua mạng. Postman: Authorization → Bearer Token →
`{{vocr_api_key}}`, với biến local bằng key trong `.env.local`; không export/share
key thật. Response minh họa phía trên được rút gọn; response thực tế đủ 13 key.

### Debug local, không cấp key cho trình duyệt

Server đọc `conf/pipeline_conf.yaml` rồi deep-merge
`conf/local.pipeline_conf.yaml`. Để API và demo UI trả/hiển thị trace của các
bước layout, OCR, page blocks và extraction, bật debug ở file local runtime:

```yaml
debug:
    enabled: true
    dir: './debug_outputs'
```

Chạy native trên máy local, không đặt sau proxy/ngrok/tunnel:

```bash
uv run uvicorn server.main:app --env-file .env.local \
  --host 127.0.0.1 --port 8000 --reload --no-proxy-headers
```

Mở `http://127.0.0.1:8000/`. UI gửi PDF tới `POST /debug/ocr/pdf` và tải ảnh
qua `/pipeline_outputs/*`. Các đường dẫn local này không cần Bearer key nhưng
kiểm tra peer loopback, Host local, Origin cùng origin (nếu có), Fetch Metadata
và từ chối header chuyển tiếp của proxy. UI không lấy/lưu API key, không có
endpoint cấp key. Không dùng localhost debug như một cơ chế xác thực mạng.
Proxy không gắn header chuyển tiếp có thể giống client local, nên socket chỉ
bind `127.0.0.1` và tuyệt đối không public qua proxy/tunnel.

Khi `debug.enabled=true`, pipeline trả thêm `debug` gồm Markdown, ảnh, layout,
OCR và evidence; API có Bearer key vẫn có thể trả debug khi cấu hình local bật.
Sau khi đổi YAML phải restart. `test/local.pipeline_conf.yaml` không điều khiển
server runtime. Trace và output trên đĩa không tự xóa khi tắt static serving.

### UAT/staging/production

- Bảo đảm `debug.enabled=false` trong **cấu hình sau deep-merge**; không copy
  file local đang bật debug lên server. YAML mặc định đã tắt debug.
- Chỉ đăng ký các route `/api/v1/ocr/*` có xác thực. `/`, `/debug/ocr/pdf`,
  `/pipeline_outputs/*`, `/health`, `/docs`, `/redoc`, `/openapi.json` không
  được cung cấp. Endpoint cấp key không tồn tại ở bất kỳ chế độ nào.
- Dùng key riêng từng môi trường. Truyền `VOCR_API_KEY` qua môi trường triển khai,
  hoặc nạp `.env.staging` rõ ràng bằng `uvicorn --env-file` khi chạy native.
- Với Docker có thể upload file secret qua SSH lên host rồi tạo container bằng
  `docker run --env-file /path/.env.staging ...`; Compose dùng biến đã export như các
  ví dụ trên. `docker cp` file env vào container đang chạy không tự cấu hình key.
- `.dockerignore` chặn `.env*` và `*.env` (cả thư mục con) khỏi build context;
  không nhúng secret vào image hoặc tài liệu. Key đổi cần restart tiến trình native
  hoặc recreate container từ image cũ; không cần rebuild image. `docker restart`
  không nạp lại giá trị từ file được truyền bằng `docker run --env-file`.
- Dùng HTTPS/reverse proxy cho API deploy, nhưng không forward các surface debug.

### Kiểm tra HTTP không nạp model

```bash
uv run --no-project python -m unittest discover -s test -p test_api_auth.py -v
```
