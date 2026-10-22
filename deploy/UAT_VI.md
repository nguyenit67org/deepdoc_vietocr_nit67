# Triển khai OCR CPU lên UAT bằng WinSCP

## Phạm vi

- Bản chính: `deepdoc-uat:py310-cpu`, Python 3.10 riêng bên trong container.
- Python 3.12 trên Ubuntu host không cần thay đổi hoặc cài thêm thư viện.
- Image đã chứa Python, thư viện hệ thống/Python, code và model. UAT không cần
  Internet, `pip install`, `apt install`, clone Git hay tải model để chạy ứng dụng.
- Giới hạn: 8 GiB RAM, không swap, tối đa 4 vCPU, một PDF/lượt. Không xử lý bảng.
- Không lưu PDF/ảnh/kết quả lâu dài. Model được giữ trong RAM giữa các request.
- PDF test nằm trong khoảng 1–20 trang. Chưa xác nhận xử lý tốt PDF dài hơn.
- Khi bận, API trả 503 + Retry-After; không có job queue/job_id hay lấy lại kết quả.
- Client ngắt kết nối: hủy giữa các batch, không dừng tức thì lệnh native đang chạy.

## 1. Chuyển gói từ Windows

Thư mục bản chính dự kiến trên Windows:

```text
D:\ocr-uat-release\py310
```

Chỉ dùng thư mục đã có `SHA256SUMS`, `release.json` và `validation-summary.json`.
Không dùng file `.partial` hoặc coi thư mục đang xuất dở là gói hoàn tất.

Bật cơ chế truy cập mạng/firewall công ty như khi SSH/WinSCP hiện tại. Trong WinSCP,
tạo thư mục `/home/app/ocr-uat` rồi chuyển **toàn bộ nội dung thư mục py310** vào đó,
gồm file ẩn `.env.example`. Không chuyển `py311-backup`, dataset hay venv lên UAT.

## 2. Kiểm tra và load image trên UAT

SSH vào UAT, chạy:

```bash
cd /home/app/ocr-uat
sha256sum -c SHA256SUMS
df -h / /home/app
sudo ss -ltnp 'sport = :8000'
grep -m1 '^flags' /proc/cpuinfo | grep -oE '\b(avx|avx2|fma)\b'
```

- Checksum phải đều `OK`; sai thì không load, chuyển lại file bị lỗi.
- Port 8000 phải chưa có dịch vụ listen. Nếu đã có, dừng ở đây để chọn port khác,
  không tắt dịch vụ đang chiếm cổng.
- Tính cả archive, image đã load và chừa tối thiểu khoảng 4 GB đĩa trống cho host.
  Docker có thể giữ cả layer nén và layer giải nén; không chỉ nhìn kích thước archive.
- Nếu VM thiếu AVX hoặc gặp `Illegal instruction`, báo lại; không tự nâng packages
  trên host hoặc tự thử các image khác không kiểm chứng.

```bash
sudo docker load -i deepdoc-uat-py310-cpu.tar.gz
sudo docker image inspect deepdoc-uat:py310-cpu --format '{{.Id}}'
df -h /
```

Đối chiếu ID với `release.json`. Không cần pull/build trên UAT. Archive có thể xóa
sau khi load và kiểm tra thành công để tiết kiệm đĩa; giữ bản gốc ở Windows.
Không chạy `docker system prune`, xóa cache chung hoặc restart Docker daemon.
Giới hạn 8 GiB/4 vCPU áp dụng cho container OCR lúc chạy, không áp dụng cho Docker
daemon trong bước `docker load`. Nên load khi server ít tải và theo dõi CPU/đĩa;
không chỉnh giới hạn chung của daemon vì sẽ ảnh hưởng các dịch vụ khác.

## 3. Tạo API key và khởi động

```bash
umask 077
cp .env.example .env
openssl rand -hex 32
nano .env
```

Giữ `OCR_IMAGE=deepdoc-uat:py310-cpu`. Thay `REPLACE_WITH_RANDOM_TOKEN` bằng key vừa
sinh ở dòng `VOCR_API_KEY`. Không gửi key lên chat/Git, không chia sẻ output môi trường.
Không copy lại `.env.example` đè lên `.env` trong các lần cập nhật sau.

```bash
sudo docker compose -p deepdoc-uat -f compose.yaml config --quiet
sudo docker compose -p deepdoc-uat -f compose.yaml up -d --pull never
sudo docker compose -p deepdoc-uat -f compose.yaml ps
sudo docker compose -p deepdoc-uat -f compose.yaml logs --tail 80
curl --fail http://127.0.0.1:8000/health
sudo docker stats --no-stream
```

Chờ nạp model một lần. Kết quả health mong đợi:

```json
{"status":"ready","model_loaded":true,"busy":false}
```

`busy:true` khi đang xử lý không có nghĩa unhealthy. Nếu container dừng/OOM/startup
lỗi thì xem log, không bật restart loop hay tăng RAM quá mức đã duyệt. Kiểm tra RAM
và CPU thực tế trong lượt PDF ngắn đầu tiên, cùng trạng thái các dịch vụ công ty.

Container chỉ bind `127.0.0.1:8000` trên server. Không mở cổng firewall ra mạng ở bước này.

## 4. Mở SSH tunnel từ Windows

Trong PowerShell trên Windows, thay `IP_UAT` bằng host đang dùng để SSH/WinSCP:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:8000 app@IP_UAT
```

Thêm `-p CONG_SSH` nếu SSH không dùng cổng mặc định. Giữ cửa sổ này mở; không có
output sau đăng nhập thường là bình thường. Nếu forwarding bị chính sách SSH chặn,
xin quản trị viên duyệt, không tự sửa sshd/firewall. Ctrl+C để đóng tunnel.

## 5. Test Postman

1. GET `http://127.0.0.1:18000/health`.
2. POST `http://127.0.0.1:18000/api/v1/ocr/pdf`.
3. Authorization: **Bearer Token**, nhập API key đã tạo trên UAT.
4. Body → **form-data** → key `file`, kiểu **File**, chọn PDF 1–2 trang trước.
5. Không tự đặt Content-Type; Postman tạo multipart boundary.
6. Đặt request timeout đủ dài cho OCR CPU; có thể dùng 0/no timeout khi kiểm thử
   có giám sát. Không tự retry liên tục một POST đang chạy.

Mã trả về: 200 thành công; 401 sai/thiếu key; 413 quá 100 MiB; 422 PDF/form không
hợp lệ; 503 đang bận/chưa sẵn sàng; 408 upload/processing timeout hoặc hủy.
HTTP 200 và đủ schema không đồng nghĩa tất cả giá trị OCR/trích xuất đều chính xác.

## 6. Dừng và rollback

```bash
sudo docker compose -p deepdoc-uat -f compose.yaml stop
```

Lệnh chỉ tác động project OCR này. `restart: "no"` là chủ ý để lỗi/OOM không tạo
vòng restart trên server dùng chung.

Giữ archive và ID của bản đã chạy ổn ở Windows. Khi cập nhật, dùng tag phiên bản
riêng, load bản mới, đổi `OCR_IMAGE` trong `.env`, rồi `up -d --pull never` và kiểm tra.
Rollback bằng image/tag cũ cùng Compose/config tương ứng. Không xóa bản tốt trước
khi bản mới được xác minh, và không giữ nhiều image trên UAT nếu thiếu đĩa.

Truy cập trực tiếp từ ứng dụng nội bộ là bước sau khi tunnel test đạt: cần chốt IP,
port, nguồn client được phép, TLS/proxy và chính sách công ty trước khi đổi bind.
