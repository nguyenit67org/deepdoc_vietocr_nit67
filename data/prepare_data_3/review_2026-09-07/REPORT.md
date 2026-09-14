# Kết quả rà soát PDF/JSON — 07/09/2026

Đã đối chiếu 30 cặp chưa được người dùng kiểm tra và sửa 156 giá trị. 9 JSON đã kiểm tra được giữ nguyên từng byte; cặp phụ lục 155 được xử lý riêng theo yêu cầu xóa.

## Phạm vi và quy ước

- Kiểm tra nội dung cần gán nhãn từ PDF địa phương: trích text, đọc ảnh trang đầu và trang có nơi nhận/người ký; các trang dẫn chứng được ghi theo số trang PDF (bắt đầu từ 1). Đây không phải đọc soát toàn bộ điều khoản và từng ô biểu mẫu của hơn một nghìn trang phụ lục.
- Mỗi JSON tiếp tục mô tả văn bản chính đầu tiên. Người ký lấy ở trang đầu tiên có khối ký định danh; không trộn với quyết định/nghị quyết/biên bản đính kèm.
- `recipients` lấy mục “Nơi nhận”, giữ “Như trên” thay vì tự mở rộng. Theo quy ước trong 10 nhãn người dùng đã kiểm tra, bỏ dòng lưu nội bộ “Lưu: …”. Riêng SPC không có mục Nơi nhận ở trang 1 nên để trống, không lấy từ trang 2.
- Giữ chữ hoa/chữ thường của văn bản, nối các dòng cùng trường bằng khoảng trắng; danh sách ngăn bằng dấu chấm phẩy. Ngày đọc từ PDF, không dùng ngày chạy OCR, tên file hoặc ngày đăng tin làm ngày nhận.
- `document_format`: dùng `print`/`scan` theo mô tả yêu cầu. Bản scan có lớp OCR vẫn là scan. Không đổi nhãn đã được người dùng kiểm tra, vì vậy bộ dữ liệu còn có `pdf_in` ở nhãn đã kiểm tra; cần thống nhất riêng nếu pipeline yêu cầu một enum duy nhất.
- `has_handwriting` chỉ tính chữ/số viết tay trong trường cần trích; không tính chữ ký, ký nháy, số đến ngoài schema, ghi chú lưu văn thư hoặc tên đóng dấu bằng phông chữ viết tay. Một file scan không mặc nhiên có handwriting.
- Giữ `0_BÌNH THƯỜNG` cho độ khẩn/độ mật khi phần văn bản được rà soát không có chỉ dấu khác. Không chạy lại Viettel API, không đọc `.env.local`.
- Không sửa mã nguồn thu thập hoặc các thay đổi đang có trong checkout. `changes.json` ghi đầy đủ nhãn gốc, trước/sau của từng thay đổi để có thể phục hồi.

## Những chỗ cần bạn xem lại

| File | Trang | Vấn đề / quyết định đã áp dụng |
|---|---:|---|
| BCF_DHCD2.PDF | 1 | Số là **03/BC**, không phải 93/BC. Ngày văn bản **26/02/2020** nhưng dấu đến **24/02/2020**. Giữ cả hai theo ảnh; cần duyệt mâu thuẫn này. Xem [ảnh phóng to](bcf-crop.jpg). |
| 31772-bn_2020-12-21_1.PDF | 1 | Sửa chức danh thành **TỔNG GIÁM ĐỐC**, tên thành **Ngô Trí Thịnh**. Dấu đè tên đệm; đối chiếu hỗ trợ với tin Công đoàn TKV cùng tháng 12/2020. Cần kiểm tra lại [ảnh phóng to](tkv-crop.jpg). |
| 20170912_thong_tu_87_ban_day_du.pdf | 1, 33 | PDF hỗn hợp: trang đầu print, trang ký 33 là scan. Tạm gán `scan` vì phần thông tin ký/nơi nhận nằm trong ảnh; bạn duyệt quy ước toàn file. |
| Ban_hanh_Quy_tac_Chi_so_VNX_Allshare.pdf | 1 | Hai cơ quan đồng ban hành, không phải con/cha. Giữ tên cả hai với dấu “ - ” theo đầu trang; hai người ký ngăn bằng “;”. Duyệt nếu bạn cần một quy ước khác cho nhiều cơ quan. |
| SPC_CBTT_Quy_che_cong_bo_thong_tin_nam_2022_cham_dut_VPDD_Bac_Lieu.pdf | 1–2 | Đã sửa về văn bản công bố trang 1, signer **ĐIÊU QUANG TRUNG**. Trích yếu lấy nguyên câu ở mục Nội dung thông tin công bố; `recipients` trống vì không có mục Nơi nhận. Tên Lê Thị Phượng và “Như điều 3” thuộc quyết định trang 2. |

Nguồn hỗ trợ tên người ký TKV: [Công đoàn TKV — Nhiệt điện Cẩm Phả hoàn thành kế hoạch 2020](https://congdoantkv.vn/tin-tuc/chi-tiet/25499/Nhiet-%C4%91ien-Cam-Pha-hoan-thanh-ke-hoach-2020-%C4%91at-36-ty-kWh-%C4%91ien). Đây chỉ là đối chiếu hỗ trợ; không thay thế việc đọc vùng tên bị dấu che trong PDF.

## File cần duyệt giữ / tách / loại — chưa thực hiện thêm hành động

| File | Nhận xét | Đề xuất chờ duyệt |
|---|---|---|
| GDW-TB_chot_DS.pdf (1 trang) | Thông báo dạng bản in chưa hoàn chỉnh: khuyết phần số, chỉ còn `/TB–QLNY`, không có nơi nhận/người ký/chức danh. Còn nhảy mục từ 2. Năm 2018 ngoài khoảng HNX được yêu cầu. | Ưu tiên loại nếu cần văn bản hành chính hoàn chỉnh; hoặc giữ làm mẫu thiếu trường. |
| 20170726_ND_71.2017_thay_the_TT121.pdf (15 trang) | Bản in lại nghị định: cuối trang 14–15 có nơi nhận nhưng hoàn toàn không có khối ký. `signer`/`signer_title` giữ trống. | Giữ nếu chấp nhận bản in lại thiếu khối ký; nếu cần bản ký thì thay nguồn, không tự điền người ký của một bản khác. |
| 20210119_Thong_tu_118.2020_TT-BTC.pdf (353 trang) | Văn bản chính trang 1–12; từ trang 13 là danh mục và các mẫu phụ lục, gồm mẫu bản cáo bạch/báo cáo rất dài. Không phải một báo cáo tài chính thực tế, nhưng phần lớn file là biểu mẫu. | Giữ bản raw, tạo riêng bản 12 trang cho đánh giá nếu bạn duyệt. |
| 20170912_thong_tu_87_ban_day_du.pdf (71 trang) | Thông tư kết thúc trang 33; phần còn lại gồm các mẫu báo cáo và bảng biểu. | Cân nhắc bản đánh giá trang 1–33; không xóa cả văn bản chỉ vì có biểu mẫu. |
| 20171012_Thong_tu_95_2017.pdf (40 trang) | Thông tư kết thúc trong trang 2, phụ lục bắt đầu ngay cùng trang. | Giữ hoặc tách riêng bản đánh giá, cần xử lý ranh giới cùng trang nếu muốn bỏ phụ lục. |
| QC_niem_yet_tai_SGDCK_TPHCM.pdf (94 trang); 20160819-QD340-QD_ban_hanh_quy_che_CBTT_tai_SGDCK.pdf (67 trang) | Quyết định chính trang 1–2, sau đó là quy chế và phụ lục dài. | Có hình thức hành chính ở văn bản chính; giữ raw hoặc tạo riêng bản 2 trang nếu bạn duyệt. |
| 20171205_Dieu_le_So_2017_so_2399.pdf (28 trang); 20170912_Quyet_dinh_1191_cua_Thu_tuong.pdf (25 trang) | Lần lượt quyết định kèm điều lệ, quyết định kèm lộ trình/bảng công việc; văn bản chính kết thúc trang 2 và 11. | Không đề nghị xóa chỉ vì dài; có thể tách bản đánh giá nếu cần. |
| BCF_DHCD.PDF; 14501-bn_2017-07-03_1651_1.PDF; 30233-bn_2020-11-26_1.PDF; 30829-bn_2020-12-07_1.PDF; SPC_CBTT_Quy_che_cong_bo_thong_tin_nam_2022_cham_dut_VPDD_Bac_Lieu.pdf | Nhiều văn bản trong một PDF. Nhãn đã thống nhất về văn bản đầu. | Giữ nguyên hoặc tách nhiều mẫu nếu bạn muốn; chưa tách. |

Không thấy căn cứ để xóa thêm một file chỉ vì nội dung chính là báo cáo tài chính/báo cáo thường niên/prospectus trong 30 file đã rà soát. Các mẫu báo cáo/bản cáo bạch đính kèm thông tư được nêu riêng ở trên. Những văn bản quy phạm (thông tư/nghị định) có bố cục gần văn bản hành chính nhưng bạn cần quyết định chúng có thuộc tập đánh giá mong muốn hay không.

## Metadata nguồn và điều kiện thời gian

- 19 file HSX: ID trang nguồn có trong danh sách chính thức, đường dẫn PDF khớp API tệp đính kèm theo ID. Bằng chứng: `hsx-news-evidence.json` và `hsx-attachments-evidence.json`. Đây là đối chiếu quan hệ bài viết–tệp, không phải so hash tải lại từng PDF.
- 11 file HNX rà soát: link chi tiết cũ là trang danh sách chung nên đã xóa giá trị đó thành chuỗi rỗng, không bịa link chi tiết. Giữ link PDF cũ; xác minh trực tuyến bị lỗi certificate issuer trên portal.hnx.vn và owa.hnx.vn. Cần bổ sung link chi tiết đúng cho cả 11 file HNX trong bảng kiểm kê dưới đây.
- Script thu thập hiện có ghi rõ HNX không lọc thời gian, giải thích vì sao bộ dữ liệu vi phạm điều kiện ban đầu. Có **14/17 file HNX** ngoài 2000–2017 (10 chưa kiểm tra trước đây và 4 đã được bạn kiểm tra). Chưa xóa hay thay các file này. Điều kiện thời gian trong prompt gốc áp dụng trang 1 HNX; không tự áp sang HSX.

| File HNX ngoài 2000–2017 | Ngày văn bản | Trạng thái |
|---|---|---|
| 125-v_2021-01-19_1 | 13/01/2021 | Người dùng đã kiểm tra; không sửa |
| 126-v_2021-01-19_1 | 13/01/2021 | Người dùng đã kiểm tra; không sửa |
| 28914-bn_2020-11-02_1 | 30/10/2020 | Đã rà soát lần này |
| 28981-bn_2020-11-03_1 | 30/10/2020 | Đã rà soát lần này |
| 30233-bn_2020-11-26_1 | 23/11/2020 | Đã rà soát lần này |
| 30829-bn_2020-12-07_1 | 04/12/2020 | Đã rà soát lần này |
| 31772-bn_2020-12-21_1 | 21/12/2020 | Đã rà soát lần này |
| 434-bn_2021-01-08_1 | 06/01/2021 | Người dùng đã kiểm tra; không sửa |
| 4623-bn_2020-03-05_1 | 04/03/2020 | Người dùng đã kiểm tra; không sửa |
| BCF_DHCD | 20/02/2020 | Đã rà soát lần này |
| BCF_DHCD2 | 26/02/2020 | Đã rà soát lần này |
| GDW-TB_chot_DS | 11/12/2018 | Đã rà soát lần này |
| PRE_Ngay_dang_ky_cuoi_cung | 02/11/2020 | Đã rà soát lần này |
| SPC_CBTT_Quy_che_cong_bo_thong_tin_nam_2022_cham_dut_VPDD_Bac_Lieu | 21/01/2022 | Đã rà soát lần này |

## Những nhãn đã kiểm tra: chỉ ghi nhận, không sửa

`155.2020_Nd-CP_-_huong_dan_LCK.json` vẫn có `receiverDate = 07/09/2026`. Vì bạn đã kiểm tra file này, mình không sửa; bạn nên kiểm tra lại dấu ngày đến trước khi dùng làm GT. Không coi ghi nhận này là kết luận sai sau đối chiếu PDF, vì file thuộc nhóm loại trừ rà soát.

## Kiểm kê 30 file và các trường đã sửa

| JSON | Trang dẫn chứng | Trường sửa |
|---|---|---|
| [28914-bn_2020-11-02_1.json](../raw/28914-bn_2020-11-02_1.json) | 1, 2 | type, title, recipients, signer_title, receiverDate, source_url_detail |
| [28981-bn_2020-11-03_1.json](../raw/28981-bn_2020-11-03_1.json) | 1, 2 | type, officeSender, receiverDate, source_url_detail |
| [30233-bn_2020-11-26_1.json](../raw/30233-bn_2020-11-26_1.json) | 1 | signer, signer_title, receiverDate, source_url_detail |
| [30829-bn_2020-12-07_1.json](../raw/30829-bn_2020-12-07_1.json) | 1 | signer, signer_title, receiverDate, source_url_detail |
| [31772-bn_2020-12-21_1.json](../raw/31772-bn_2020-12-21_1.json) | 1 | type, signer_title, recipients, signer, source_url_detail |
| [BCF_DHCD2.json](../raw/BCF_DHCD2.json) | 1 | code, officeSender, signer_title, receiverDate, source_url_detail |
| [BCF_DHCD.json](../raw/BCF_DHCD.json) | 1, 2 | type, title, code, recipients, signer_title, province, source_url_detail |
| [PRE_Ngay_dang_ky_cuoi_cung.json](../raw/PRE_Ngay_dang_ky_cuoi_cung.json) | 1, 2 | type, receiverDate, source_url_detail |
| [14501-bn_2017-07-03_1651_1.json](../raw/14501-bn_2017-07-03_1651_1.json) | 1, 2, 3, 4 | type, documentDate, receiverDate, source_url_detail |
| [20160819-QD340-QD_ban_hanh_quy_che_CBTT_tai_SGDCK.json](../raw/20160819-QD340-QD_ban_hanh_quy_che_CBTT_tai_SGDCK.json) | 1, 2 | type, recipients, receiverDate, has_handwriting |
| [20170419_Quy_Che_HDCS-HOSE.json](../raw/20170419_Quy_Che_HDCS-HOSE.json) | 1, 2 | type, signer_title, recipients, receiverDate |
| [QCGD_QĐ_342.json](../raw/QCGD_QĐ_342.json) | 1, 2 | type, recipients, receiverDate |
| [QC_niem_yet_tai_SGDCK_TPHCM.json](../raw/QC_niem_yet_tai_SGDCK_TPHCM.json) | 1, 2 | type, recipients, province, receiverDate |
| [hdcs.json](../raw/hdcs.json) | 1, 2 | type, documentDate, recipients, province, receiverDate, document_format |
| [20171127_20171122-Luu_y_viec_chot_danh_sach_co_dong_thuc_hien_quyen.json](../raw/20171127_20171122-Luu_y_viec_chot_danh_sach_co_dong_thuc_hien_quyen.json) | 1 | receiverDate |
| [20171205_Dieu_le_So_2017_so_2399.json](../raw/20171205_Dieu_le_So_2017_so_2399.json) | 1, 2 | type, officeSender, recipients, receiverDate, has_handwriting |
| [20150512_20150512_-_QD_sua_doi_bo_sung_Quy_che_CBTT_ve_Quy_ETF_tai_SGDCK_TP.HCM.json](../raw/20150512_20150512_-_QD_sua_doi_bo_sung_Quy_che_CBTT_ve_Quy_ETF_tai_SGDCK_TP.HCM.json) | 1, 2, 3 | type, recipients, receiverDate, document_format, has_handwriting |
| [20170705_20170705_-_Qd_QTCS_PTBV.json](../raw/20170705_20170705_-_Qd_QTCS_PTBV.json) | 1 | type, recipients, receiverDate, document_format |
| [Ban_hanh_Quy_tac_Chi_so_VNX_Allshare.json](../raw/Ban_hanh_Quy_tac_Chi_so_VNX_Allshare.json) | 1, 2 | type, officeSender, signer, signer_title, province, receiverDate, document_format |
| [20210119_Thong_tu_117.2020_TT-BTC.json](../raw/20210119_Thong_tu_117.2020_TT-BTC.json) | 1, 9 | type, title, officeSender, province, recipients, receiverDate, document_format, has_handwriting |
| [20210119_Thong_tu_120.2020_TT-BTC.json](../raw/20210119_Thong_tu_120.2020_TT-BTC.json) | 1, 14 | type, title, officeSender, province, recipients, receiverDate, document_format, has_handwriting |
| [20170912_Quyet_dinh_1191_cua_Thu_tuong.json](../raw/20170912_Quyet_dinh_1191_cua_Thu_tuong.json) | 1, 11 | type, officeSender, recipients, receiverDate, has_handwriting |
| [20210106_Nghị_định_156.2020NĐ-CP_XPHC_trong_LVCK.json](../raw/20210106_Nghị_định_156.2020NĐ-CP_XPHC_trong_LVCK.json) | 1, 69 | type, signer, signer_title, recipients, receiverDate, has_handwriting |
| [20210119_Thong_tu_119.2020_TT-BTC.json](../raw/20210119_Thong_tu_119.2020_TT-BTC.json) | 1, 45 | type, officeSender, signer, signer_title, recipients, receiverDate |
| [20210119_Thong_tu_118.2020_TT-BTC.json](../raw/20210119_Thong_tu_118.2020_TT-BTC.json) | 1, 12, 13, 14, 15 | type, officeSender, signer, signer_title, recipients, receiverDate, has_handwriting |
| [20170912_thong_tu_87_ban_day_du.json](../raw/20170912_thong_tu_87_ban_day_du.json) | 1, 33 | type, officeSender, recipients, receiverDate, document_format, has_handwriting |
| [20171012_Thong_tu_95_2017.json](../raw/20171012_Thong_tu_95_2017.json) | 1, 2 | type, officeSender, recipients, receiverDate, document_format, has_handwriting |
| [20170726_ND_71.2017_thay_the_TT121.json](../raw/20170726_ND_71.2017_thay_the_TT121.json) | 1, 14, 15 | type, recipients, receiverDate, document_format |
| [GDW-TB_chot_DS.json](../raw/GDW-TB_chot_DS.json) | 1 | type, code, province, officeSender, receiverDate, document_format, source_url_detail |
| [SPC_CBTT_Quy_che_cong_bo_thong_tin_nam_2022_cham_dut_VPDD_Bac_Lieu.json](../raw/SPC_CBTT_Quy_che_cong_bo_thong_tin_nam_2022_cham_dut_VPDD_Bac_Lieu.json) | 1, 2 | type, title, signer, signer_title, recipients, receiverDate, document_format, source_url_detail |

## Xóa được ủy quyền và kiểm tra cuối

Chỉ cặp `155.2020_Nd-CP_-_huong_dan_LCK_-_Phu_luc.pdf` và JSON cùng tên được xóa theo yêu cầu trực tiếp. Chi tiết hash và kiểm tra bảo toàn được ghi tại `validation.json`. Các file chờ duyệt bên trên vẫn còn nguyên.

Các thay đổi được kiểm tra bằng parse JSON, kiểu/schema so với nhãn gốc, đủ 30 file được rà soát, đúng cặp PDF/JSON, so hash các PDF còn giữ và so byte 9 JSON đã được người dùng kiểm tra. Không chạy inference OCR vì đây là sửa GT dựa trên PDF.
