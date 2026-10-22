# Kế hoạch OCR recognizer A/B: từ cached crops/KIE tới handwriting và stamp

Ngày lập: 2026-10-15. Workspace: `/home/nguyen/projects/deepdoc_vietocr_dh`.

## 1. Mục tiêu và quyền thực thi

Mục tiêu của user:

1. Trước mắt benchmark 3–4 recognizer khác nhau trên crop cache và downstream KIE hiện có, tìm khả năng cải thiện FastOCR baseline mà chưa fine-tune.
2. Về sau đo recognition/CER trên chữ viết tay và chữ bị dấu mộc giao cắt, để đánh giá swap một model có đủ không, hay cần routing nhiều model, cải thiện detection/crop hoặc fine-tune.
3. Tối ưu effort: chạy swap-and-test trước; chỉ label pilot có chủ đích khi đã có output để phân tích. Không mặc định phải transcription-label cả 6.619 crop.

**Quyền trong yêu cầu tạo tài liệu này:** lưu kế hoạch/context, không tự chạy model mới, sửa production hoặc tạo dataset annotation. Khi tiếp tục, trình bày shortlist, phạm vi sửa harness/adapter/test, dependency, chi phí và xin duyệt trước khi thực thi. Các giai đoạn sau là roadmap, không phải blanket approval.

Quy ước đã chốt sau khi lập plan: FastOCR làm control **cộng 4 recognizer ứng viên**: OcrDoc Run 6, VietOCR handwriting vudang449, HTR-ConvText HANDS-VNOnDB và SenOCR-Vi.

### Cập nhật scope đã duyệt, 2026-10-15

User đã duyệt tải weights/source và implement/test **cả 4 theo hướng swap-and-play**, với code modular phù hợp interface recognition của OCR engine hiện tại. Cho phép registry/adapter, wiring opt-in trong engine/config, harness/test và artifact; giữ FastOCR làm mặc định. User đồng ý test HTR-ConvText dù license HF/GitHub chưa thống nhất; không suy rộng thành quyền phân phối sản phẩm hoặc legal clearance.

Inference thực ưu tiên GPU nếu backend hỗ trợ; CPU/mock chỉ để kiểm tra contract. Không fine-tune, không tạo transcription dataset, không đổi detection/extraction/GT, không chạy full pipeline 2.249 trang trong scope hiện tại. Confidence policy vòng đầu: score assembly trung tính 1.0, raw confidence riêng/null nếu model không có; không áp threshold native khác nhau để che khác biệt model.

Code/config hướng dẫn sử dụng: `docs/ocr_recognizer_adapters.md`, `conf/recognizers/`. Weight/source pin trong `catalog.json`, source reference commits trong `sources.json`; dữ liệu tải ở ignored `scratch/ocr-recognizers/`.

## 2. Policy và các nguồn chuẩn

Đọc trước khi tiếp tục:

- `/home/nguyen/projects/deepdoc_vietocr_dh/AGENTS.md`
- `/home/nguyen/projects/deepdoc_vietocr_dh/docs/ocr_pipeline_benchmark_metrics.md`
- Các `AGENTS.md` áp dụng ở thư mục dự định sửa, nếu có.

API giữ đúng 13 field, benchmark chấm 12 field; `receiverDate` ngoài scope. Cùng document set, GT snapshot và metric version cho mọi phía. Không lấy summary lịch sử khác GT để so trực tiếp. Policy repo có ưu tiên cao hơn đề xuất trong tài liệu này.

### Full baseline bất biến

Target manifest:

`/home/nguyen/projects/deepdoc_vietocr_dh/ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015/manifest.json`

Cùng thư mục có effective `pipeline_config.json`, `source_snapshot/`, `predictions.jsonl`, `evidence/<document_id>/trace.json`, `page_N.png`, `pipeline_outputs/<document_id>/output.json` với crop offsets. Không ghi đè nguồn này.

### Cache dùng cho A/B

Cache gốc đã kiểm chứng:

`/home/nguyen/projects/deepdoc_vietocr_dh/ocr-collab/artifacts/cached_ocr_equivalence_20261015/manifest.json`

Các file theo trang:

```text
cache/<document_id>/selection.json
cache/<document_id>/page_N/input.json
cache/<document_id>/page_N/crop_manifest.json
cache/<document_id>/page_N/crops/<detection_index>.png
cache/<document_id>/page_N/results.json
```

FastOCR control đọc lại PNG, không chạy detection/layout:

`/home/nguyen/projects/deepdoc_vietocr_dh/ocr-collab/artifacts/cached_crop_fastocr_control_20261015/manifest.json`

Đọc thêm `REPORT.md`, `recognition_vs_cache.json`, `runtime.json`, `summary.json` trong thư mục control trước khi suy luận từ kết quả cũ.

### Các entry point hiện có

- `scripts/check_cached_ocr_equivalence.py`: harness hiện tại, có `--crop-cache`, `--document-id`, `--preflight-only`.
- `test/test_cached_ocr_equivalence.py`: test CPU/mock cho selection, provenance, hash/BGR/index mapping và so sánh metric/prediction.
- `module/ocr/base.py`: `OCREngine` protocol cho cả detection và recognition.
- `module/ocr/engine.py`: `TextRecognizer.__call__()` và crop geometry của engine.
- `module/pipeline/ocr_page.py`: `PageOcrPrep`, `prepare_ocr_page()`, `finish_ocr_page()`.
- `module/pipeline/document_pipeline.py`: `_build_table_skeleton()`, `_process_page_after_layout()`.
- `module/extract/vbhc_rules.py`: extraction phải được giữ cố định trong recognizer A/B.
- `ocr-collab/benchmark.py`: scoring chuẩn hiện hành.

Lưu ý kỹ thuật: nhánh cached của harness hiện **hard-code FastOCR** và kiểm tra weight phải khớp lượt cache. Chưa có adapter registry hay generic multi-model runner. Khi triển khai cần tách kiểm chứng cache/control khỏi cấu hình recognizer ứng viên, không đơn giản xóa guard để mọi drift đều được bỏ qua.

## 3. Trạng thái đã kiểm chứng, không nhầm với việc chưa làm

Các kết quả dưới đây đã được chạy và đọc artifact trong session trước; phải revalidate hash/trạng thái khi bắt đầu session mới:

- Dataset có **100 PDF, 2.249 trang**, không phải 101 PDF.
- Metadata chọn 100 trang bắt đầu, 101 trang kết thúc, 18 trang trùng hai vai trò; union là **183 trang vật lý**.
- File `71+2017+NĐ-CP_2017-06-06` có end pages `[13, 14]` theo chỉ số vật lý 0-based.
- Cache có **6.619 crop**, từ DeepDoc ONNX text detector trên các trang được chọn, với padding/perspective warp/rotation của pipeline.
- Full baseline effective config: table, corrector, page orientation, page deskew và red removal đều disabled. Xác minh lại bằng config, không dựa vào YAML mặc định.
- Saved-block replay, saved-OCR reassembly và re-detect/FastOCR đều tái lập prediction baseline 100/100 tài liệu.
- Control đọc PNG có **6.619/6.619 kết quả crop khớp text và wrapper score** với lượt nhận dạng trực tiếp từ crop NumPy.
- Cả 6.618 retained OCR line khớp thứ tự, text và quad làm tròn. Crop còn lại trả text rỗng: `117+2020+TT-BTC_2020-12-31`, trang vật lý 1, detection index 14; lọc đúng contract.
- Control cached-crop khớp cả 13 giá trị prediction trên 100/100 tài liệu với full baseline và prior hybrid; không field/bucket đổi.
- Document Success@5% giữ 40/100; các delta metric bằng 0 nơi có mẫu số. Không coi metric null là 0 hoặc là đạt target.
- 9 test harness và 60 test extraction/policy pass ở thời điểm control.
- Các label hash hiện tại đều khác manifest full baseline; hai phía đã được rescore bằng GT hiện tại. Không sửa GT để làm khớp.

**Trạng thái tại thời điểm lập plan:** chưa chạy recognizer ứng viên, chưa có transcription GT/CER, router hay fine-tune. Xem nhật ký triển khai ở cuối tài liệu để biết thay đổi mới hơn. Báo cáo cũ không phải visual annotation cho handwriting/stamp.

## 4. Các bất biến và failure mode

- Kiểm tra `git status` trước khi sửa. Repo có nhiều staged/unstaged/untracked từ công việc trước; không reset, revert, overwrite, xóa hoặc stage thay user.
- Scope triển khai dự kiến để xin duyệt: harness/adapter thử nghiệm, test liên quan và artifact mới. Nếu cần sửa production engine/pipeline/extraction để vượt blocker, dừng giải thích và xin duyệt riêng.
- Không sửa GT, extraction rule, benchmark normalization hoặc thêm quy tắc theo filename/đáp án GT.
- Không chạy full pipeline 2.249 trang trong vòng cached A/B này. Không tạo PDF rút gọn hay đánh lại số trang.
- Metadata GT chỉ chọn trang và phân nhóm/scoring; không đưa field values vào recognizer, prompt, router hay extraction.
- Giữ cùng detection quads, crop pixels, crop-index mapping, exclusions, layout, original/processed dimensions, crop offsets và thứ tự trang. Không dùng bbox crop đơn giản thay warped crop.
- Debug crop cũ có thể bị ghi đè theo cửa sổ ở PDF dài; không dùng `debug_outputs/` làm nguồn cache chung.
- Trace baseline làm tròn tọa độ, lọc empty/low-score OCR và thiếu bbox_row. Control tái tạo bbox_row, không chứng minh mọi raw detection/crop baseline trùng byte.
- Code extraction/document assembly có source snapshot; một số dependency OCR/mapping/reading order không có snapshot baseline độc lập. Hash hiện tại giúp freeze từ lúc control, không tạo bằng chứng lịch sử còn thiếu.
- Cache chỉ chứa vùng detector tìm thấy/được pipeline cho nhận dạng. Swap recognizer không cứu được handwriting detector bỏ sót hoặc crop cắt thiếu chữ.
- Đây là **hybrid diagnostic**: các trang không chọn giữ OCR baseline. Không gọi là full inference hoặc kết quả OCR toàn bộ PDF.

## 5. Giai đoạn A: benchmark KIE 3–4 recognizer trước

### A0. Chốt shortlist và feasibility, xin duyệt

Ưu tiên độ đa dạng thực chất thay vì nhiều checkpoint gần giống nhau:

| Vai trò | Hướng khảo sát, chưa phải model đã chọn |
|---|---|
| Control | FastOCR hiện có, giữ checkpoint/config |
| Candidate 1 | Model line recognition mạnh tiếng Việt/chữ in |
| Candidate 2 | Khác kiến trúc hoặc dữ liệu huấn luyện với FastOCR |
| Candidate 3 | Có cơ sở hỗ trợ handwriting tiếng Việt, phải xác minh model card/khả năng thực tế |
| Candidate 4, tùy budget | VLM crop transcription hoặc family khác để khảo sát bổ trợ, không mặc định phù hợp production |

Với mỗi ứng viên, ghi exact model ID/revision, weight hash, license, ngôn ngữ, loại input, giới hạn width/token, preprocessing, package/runtime requirements, GPU/RAM và chi phí dự kiến. Checkpoint handwriting tiếng Anh không tự động hỗ trợ tiếng Việt.

Hỏi rõ giới hạn GPU/thời gian/download và cách xử lý dependency xung đột. Ưu tiên môi trường tách biệt thay vì nâng package làm hỏng baseline. Không upload tài liệu/crop lên API bên ngoài hoặc phát sinh phí khi chưa được duyệt.

### A1. Adapter trong harness và contract tests

Recognizer-only adapter cần khớp phần `text_recognizer[i]` mà pipeline dùng, không bắt buộc implement toàn bộ `OCREngine`:

```text
input: list[np.ndarray BGR], cùng crop pixels và thứ tự
output: list[(text, score)] + elapsed, cùng số lượng/thứ tự
```

- Cho phép chuyển BGR -> RGB, resize/normalize/pad theo model; ghi provenance, không đổi vùng crop hoặc chạy detection lại.
- Lưu raw model output riêng với text đưa vào assembly. Quy định newline, output rỗng, failure, truncation và VLM response format trước khi chạy đủ; không âm thầm bỏ crop lỗi.
- Test color channels, index/order restoration, cardinality, empty input/output, long crop/truncation, batch slicing, Unicode, OOM/retry và per-crop errors.
- Giữ nguyên batch document/page/crop order. Internal batch size có thể khác theo model nhưng phải ghi rõ. OOM retry không được đổi thứ tự/mất crop; không so tốc độ mà che batch-size khác biệt.
- **Chính sách confidence cần duyệt trước:** FastOCR wrapper hiện luôn trả 1.0. Đề xuất vòng đầu dùng cùng filter: giữ text không rỗng, dùng score trung tính 1.0 khi assembly, confidence thật lưu riêng (null nếu không có). Không so trực tiếp score giữa các family chưa calibration. Nhánh dùng native confidence threshold là ablation riêng, không trộn với thí nghiệm model identity.
- Giữ riêng config/hash của cache source, FastOCR control và candidate weights. Candidate phải được phép khác weights; geometry/cache hash guards vẫn bắt buộc.

### A2. Preflight và smoke trước khi chạy đủ

1. Revalidate source/cache hashes, đủ 100 document, 183 page và 6.619 crop; freeze current GT hash snapshot và code/config/metric version cho toàn experiment.
2. Chạy lại FastOCR control nếu harness/runtime thay đổi; so từng crop text/score và prediction, không chỉ summary metric. Nếu control drift, dừng tìm nguyên nhân trước candidate benchmark.
3. Smoke từng candidate trên các regression case bắt buộc:
   - `43+2026+QH16_2026-08-24`: title và ngày footnote.
   - `27+2026+VBHN-ND-BTC_2026-08-27`: trang xác thực vật lý 45, index 44.
   - `155+2020+NĐ-CP_2020-12-31`: trang kết thúc vật lý 254, index 253; nhiều cửa sổ.
   - `71+2017+NĐ-CP_2017-06-06`: nhiều trang kết thúc, index 13 và 14.
   - `117+2020+TT-BTC_2020-12-31`: crop có baseline text rỗng, không làm mất index.
4. Candidate không cần khớp text/prediction baseline để smoke pass. Gate là đúng input/output contracts, mapping, provenance và extraction/scoring chạy được; báo lỗi chất lượng quan sát được.

Lệnh control tham khảo (chọn output mới chưa tồn tại; đây không phải lệnh chạy candidate):

```bash
uv run python scripts/check_cached_ocr_equivalence.py \
  ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015 \
  ocr-collab/artifacts/<new_unique_control_output> \
  --crop-cache ocr-collab/artifacts/cached_ocr_equivalence_20261015
```

### A3. Chạy đủ và scoring

- Mỗi candidate chạy đủ 6.619 crop, rebuild 183 trang, giữ OCR các trang còn lại, extraction cùng code/config, scoring cùng GT frozen và metric version.
- Job dài chạy background, checkpoint theo document; chỉ resume nếu input/model/config/code hashes khớp. Báo progress trung thực; không gọi là xong khi chưa đọc kết quả cuối.
- Chấm lại FastOCR control và candidate trên cùng GT frozen, không so trực tiếp summary cũ. Giữ cả 100 document trong mẫu số kể cả lỗi inference; không âm thầm drop case khó.
- Metric chính theo từng field: F1, precision, recall, NEM, hallucination, Document Success@5%; VAI-style ACC chỉ tham chiếu theo policy.
- So sánh raw 13-field prediction riêng với normalized metric; metric bằng nhau chưa có nghĩa prediction giống nhau.
- Báo mọi document-field thay đổi và bucket trước/sau; regression/improvement theo policy, bucket lỗi -> bucket lỗi báo riêng. Có ma trận 6x6 cho all và các split <=2, <=5, <=14 trang.
- Phân nhóm sơ bộ theo metadata handwriting/stamp hiện có, ở cấp document và field khi phù hợp. Ghi số mẫu/coverage và hai flag có thể đồng thời đúng. Không gọi phân tích này là CER crop handwriting/stamp.
- Đo recognition wall-time/throughput, thời gian diagnostic riêng và tài nguyên theo cùng giao thức nếu muốn so sánh. Không kế thừa resource full baseline, không gọi device VRAM là process VRAM.

### A4. Deliverables và gate kết thúc giai đoạn A

Lưu mỗi model/run vào thư mục mới dưới `ocr-collab/artifacts/`, có model registry và experiment summary chung:

- Manifest với run status, exact model/revision/hash, dataset/cache/GT/code/config hashes và mode hybrid.
- Raw text/confidence, assembly text/score và recognition errors theo `(document_id, physical_page_index_0based, detection_index)` cùng crop hash.
- Predictions, per-field metrics/errors, document success và enum metrics theo policy; comparison JSON/CSV, `experiment_log.csv`, sample regressions/improvements, bucket transitions, resource comparison với cờ comparability.
- Source snapshot/code provenance, effective config, dependency/runtime versions, logs và thời gian.
- Evidence extraction mới đúng document/page/bbox. Không gán source trace cũ thành trace candidate. Nếu chỉ có diagnostic JSON, ghi rõ schema/mode và không giả làm trace v2/full inference; nếu xuất benchmark bundle chuẩn, tuân thủ đủ policy trace/artifact.
- Review trực tiếp ảnh crop và trang/vùng liên quan cho các field thay đổi. Phải thực sự mở xem ảnh thành công; file ảnh tồn tại hoặc report trước không thay thế visual evidence. Gom review nhiều field cùng trang để tránh đọc lặp.

Giai đoạn A xong khi 3–4 candidate đã chạy đủ hoặc có blocker được báo rõ, mọi lỗi/coverage được hạch toán, có bảng KIE và cost/latency so với control, có evidence cho nhận xét chất lượng và danh sách case cần pilot annotation. Chưa kết luận recognition CER khi chưa có transcription GT.

## 6. Giai đoạn B: pilot transcription và challenge set, sau khi duyệt riêng

Mục tiêu đề xuất: **150–300 crop** ban đầu, điều chỉnh theo số case handwriting/stamp thực sự tìm được. Không tự biến con số này thành quota đảm bảo đủ mẫu mọi nhóm.

Tách hai nguồn chọn mẫu và luôn báo riêng:

1. **Random reference sample** có seed, sampling frame và selection probability rõ ràng để ước lượng trên cache.
2. **Challenge sample** có chủ đích: handwriting/mixed, stamp overlap, model disagreement, field KIE sai/thay đổi, mọi model thất bại. Không gộp tỷ lệ lỗi challenge rồi gọi là tỷ lệ đại diện dataset.

Không chỉ chọn dòng có prediction evidence, vì sẽ bỏ qua field bị Missing/extraction chọn sai. Dùng ảnh trang và metadata làm gợi ý tìm vùng, rồi xác minh vị trí trực tiếp. Không suy line label từ document flag.

Schema pilot tối thiểu:

```text
document_id, physical_page_index_0based, detection_index, crop_sha256
transcription, annotation_status, annotator/review provenance
handwriting: none | partial | full | uncertain
stamp_interference: yes | no | uncertain
crop_quality: complete | clipped | mixed_lines | uncertain
legibility: readable | uncertain | unreadable
sampling_source, selection_reason, linked_field_names_if_verified
```

- Handwriting và stamp là hai trục độc lập; phân tích chữ in sạch, in+dấu, viết tay sạch, viết tay+dấu, và mixed khi đủ coverage.
- Stamp label cần thấy nét dấu giao cắt/can thiệp nét chữ thực tế, không chỉ bbox chồng nhau hoặc nằm gần. Autograph không tự là handwriting của field value.
- Lưu annotation thành dataset/version mới, không sửa KIE GT. Hiển thị crop và page context; thực sự mở ảnh trước khi gán nhãn. Các case không đọc được/không chắc giữ unresolved, không đoán đáp án.
- Có thể dùng model output làm prefill nhưng human phải đối chiếu ảnh. Model consensus không phải GT; ưu tiên tránh anchoring bằng cách đọc ảnh trước/ẩn output khi có thể.
- Chốt cách transcription của chữ bị che, nội dung dấu và crop cắt thiếu trước khi label. Không lấy ngữ cảnh/GT field để bịa ký tự không nhìn thấy trong crop. Có thể lưu expected full-line text riêng, nhưng không trộn với visible-crop transcription để phạt recognizer.
- Review lại case bất đồng/khó; ghi correction history, không âm thầm sửa gold để model mới tốt hơn.

## 7. Giai đoạn C: recognition metrics và chẩn đoán

Chốt recognition normalization/version riêng trước scoring: ưu tiên Unicode NFC và whitespace policy rõ ràng, giữ dấu tiếng Việt; lưu raw text. Không tái dùng normalization đặc thù field như code/date để làm đẹp recognition CER.

Báo trên cùng gold pilot:

- Micro CER: tổng edits / tổng ký tự GT.
- Mean per-line CER, exact line accuracy và tỷ lệ line CER > 0.05, kèm số mẫu/độ dài.
- Từng nhóm handwriting/stamp/crop quality và random/challenge sample riêng; confidence interval nếu đủ mẫu, ưu tiên resampling theo document khi có nhiều crop cùng PDF.
- CER có thể >1, không clamp. Gold trống, unreadable và unresolved phải có exclusion/denominator policy và coverage rõ; model output rỗng trên gold có chữ không được loại khỏi scoring.
- Dòng ngắn: 1 lỗi/10 ký tự đã là 10% CER. Không dùng duy nhất ngưỡng 5% để kết luận model yếu.
- Recognition CER khác CER của KIE field: extraction/assembly có thể làm sai field khi OCR đúng; OCR sai ngoài vùng extraction có thể không đổi KIE.

Audit thêm một tập nhỏ vùng handwriting trên ảnh trang gốc để tìm **detection miss**. Nếu tạo manual crop để chẩn đoán, tách thành thí nghiệm riêng, không thay crop cache của main A/B. Không khẳng định detection recall nếu chưa có region GT đầy đủ.

## 8. Giai đoạn D: oracle complementarity và quyết định hướng xử lý

Trên gold pilot, tính oracle chọn model có CER thấp nhất mỗi crop để ước lượng tiềm năng bổ trợ. Oracle dùng gold nên chỉ là upper bound phân tích, không phải router deploy hay kết quả độc lập.

| Quan sát có evidence | Hướng ưu tiên |
|---|---|
| Một model mạnh gần như mọi nhóm, KIE/cost phù hợp | Swap một recognizer, chưa cần routing |
| Các model bổ trợ theo nhóm; oracle tăng rõ so với best single | Thử routing/hard-case fallback sau khi duyệt |
| Mọi model sai trên crop đủ chữ, human đọc được | Khảo sát domain/language mismatch, model chuyên biệt hoặc fine-tune |
| Mọi model sai vì crop thiếu/trộn dòng hoặc detector bỏ sót | Ưu tiên detection/cropping, không đổ lỗi cho recognizer |
| OCR đúng nhưng KIE sai | Tách bài toán extraction/assembly ra experiment khác |
| Nhóm dấu che nội dung không đọc được | Báo giới hạn thông tin; không hứa swap/fine-tune khôi phục được |

Không mặc định router phải là in/viết tay. Có thể khảo sát crop quality, độ khó, disagreement hoặc fallback tuần tự. Trước khi làm router, cần chứng minh oracle headroom đáng kể so với chi phí thêm model.

Nếu thử routing/fine-tune sau này: tách train/dev/eval theo document, không để các crop cùng PDF rò sang hai phía; không dùng cùng challenge set để vừa chọn luật vừa tuyên bố chất lượng generalization. KIE 100 PDF dùng lặp để lựa chọn model vẫn là exploratory benchmark, không thay thế holdout độc lập. Full-inference validation chỉ là giai đoạn riêng được duyệt sau khi shortlist ổn định.

## 9. Checklist tiếp tục và cập nhật tiến độ

- [x] Full baseline và hybrid cache đã hoàn tất, control PNG FastOCR đạt.
- [x] Lưu kế hoạch này; chưa chạy recognizer mới.
- [x] Kiểm tra working tree, policy và artifact/hash state ở session triển khai.
- [x] Chốt 4 candidates + FastOCR control, user duyệt swap-and-play và GPU inference.
- [x] Tải pinned weights/source, thêm registry/adapter/wiring opt-in và CPU/mock tests; benchmark manifest freeze theo từng run.
- [x] Control FastOCR sau thay đổi harness + smoke 4 model lượt đầu.
- [x] Chạy đủ cache 4 model lượt đầu và lưu KIE/error/timing artifacts; review visual vẫn pending.
- [ ] Review evidence, kết luận swap-only sơ bộ và chọn pilot theo sampling plan.
- [ ] Xin duyệt annotation budget/schema rồi tạo gold pilot có provenance.
- [ ] Recognition CER theo nhóm, audit detection miss và oracle complementarity.
- [ ] Đề xuất swap/routing/detection/fine-tune với coverage, uncertainty và validation plan riêng.

Mỗi lần cập nhật ghi ngày, run manifest, điều thực sự chạy, blockers và next action. Không tick task chỉ vì đã viết code hoặc khởi chạy job. Không thay policy bằng kết luận của experiment này.

### Nhật ký triển khai 2026-10-15

- Đã tải đủ weights/source từ 4 HF revisions trong `conf/recognizers/catalog.json`, có SHA-256/byte sizes trong mỗi `download_manifest.json`.
- Đã clone reference source VietOCR, PaddleOCR và HTR-ConvText, pin commits trong `conf/recognizers/sources.json`. Link project OcrDoc trong card trả GitHub API 404; không tuyên bố đã clone source đó.
- Đã thêm protocol recognition-only, lazy registry, 4 adapters, opt-in `ocr.recognizer` trong engine và legacy predictor compatibility hook. FastOCR default không đổi. Chưa tuyên bố full production/table/orientation equivalence cho candidates.
- Probe recognition GPU thành công cho cả 4, không phải full KIE benchmark. SenOCR chạy native Transformers 5.0 FP32 trong local worker; parent baseline vẫn Transformers 4.57. HTR optional dependencies cũng tách runtime.
- 11 adapter tests + 9 cache harness tests + 70 VBHC tests pass tại thời điểm trước fresh control.
- Fresh FastOCR integration control đã hoàn tất và đọc kết quả: `ocr-collab/artifacts/recognizer_ab_20261015/fastocr_control/`. Đủ 100 tài liệu, 183 trang, 6.619/6.619 crop khớp text/score; prediction khớp 100/100, không field/bucket đổi. Engine/factory integration không gây hồi quy trong control này.
- Thêm 2 tests cho smoke gate và metadata strata, tổng 92 test trong bốn nhóm liên quan đã pass.
- Đã khởi chạy `scripts/run_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_20261015 --stage all` background, tuần tự GPU. Driver log: `/tmp/opencode/recognizer-ab-runner-20261015.log`; log từng model nằm trong experiment root.
- Đã đọc completed OcrDoc smoke: 5 tài liệu, 11 trang, 369 crop; contract hoàn tất, có 14 field-value thay đổi, 5 regression và 1 improvement; chưa visual review, không kết luận nguyên nhân hoặc model tốt hơn. Các model còn lại và full runs chưa được xác nhận hoàn tất tại thời điểm cập nhật này.
- Next: chờ notification của background runner, đọc log/artifact cuối; chỉ gọi giai đoạn A hoàn tất sau khi xác nhận coverage của từng model hoặc báo blockers. Dùng `scripts/summarize_recognizer_ab.py` để tổng hợp các full runs đã hoàn tất và review evidence. Không sửa code/config/dependencies trong khi job đang chạy; nếu phát hiện adapter bug, tách run mới và revalidate control.

### User bổ sung: timing theo model/file/trang

- **User đính chính:** cần thời gian OCR **trung bình mỗi trang**, không cần đo từng trang riêng. Đính chính này thay thế đề xuất page-call profiling trước đó; **hủy lượt recognition bổ sung**, chưa từng khởi chạy lượt đó.
- Giữ nguyên primary benchmark/batch. Theo file: đo recognition seconds sẵn có và tính mean seconds/page bằng thời gian file / số trang được chọn của file. Theo model: tổng thời gian recognition / tổng số trang được chọn; complete run có mẫu số 183, không phải 2.249, không dùng trung bình không trọng số của các tỷ lệ file.
- Đã thay profiler tạm bằng exporter **không inference** `scripts/summarize_recognizer_timing.py`; không thay shared OCR/harness đang chạy.
- **Việc phải làm sau notification primary runner:** xác minh completed runs và xuất `primary_file_timing.csv`, `model_timing_summary.csv` cho FastOCR + 4 candidates. Báo coverage và blockers trung thực nếu chưa đủ model.
- Command: `uv run python scripts/summarize_recognizer_timing.py ocr-collab/artifacts/recognizer_ab_20261015 ocr-collab/artifacts/recognizer_ab_20261015/timing_summary` (thư mục mới chưa tồn tại).
- Ghi rõ mean từ batch, không phải measured latency của từng trang. Model load báo riêng; adapter recognition wall time bao gồm preprocessing/postprocessing/IPC nếu có, không gồm model load hoặc source page-cache decode. Không gọi đây là native GPU kernel time hoặc tuyên bố có warmup riêng.
- Artifact `timing_export_initial/` trước đính chính chỉ là export thời gian file từ completed control, không có inference/page profiling; giữ nguyên artifact đó và xuất báo cáo mới.

### Hàng đợi bổ sung được user yêu cầu: AkaOCR và VietOCR gốc

**Thứ tự:** để lượt 4 candidates hiện tại hoàn tất trước. Không sửa registry/adapter/harness/runtime đang freeze để chèn thêm model vào job đó. Sau khi đọc kết quả, mở một lượt bổ sung với artifact mới, giữ mọi baseline/candidate cũ.

Hai nguồn user yêu cầu tương ứng **3 cấu hình recognizer** cần thử:

1. **AkaOCR PyPI**, `https://pypi.org/project/akaocr/`, bản đã kiểm tra metadata: `2.1.6`. Chỉ dùng recognition, không gọi `BoxEngine` hoặc `ClsEngine` để thay detection/orientation của thí nghiệm.
2. **VietOCR gốc `vgg_seq2seq`**, source `https://github.com/pbcquoc/vietocr` và checkpoint chính thức của repo.
3. **VietOCR gốc `vgg_transformer`**, cùng upstream, không phải checkpoint handwriting fine-tune đang chạy.

Đã kiểm tra read-only, chưa cài package, chưa tích hợp hoặc chạy inference bổ sung:

- Wheel AkaOCR 2.1.6 công khai, SHA-256 `a7f0fad2bb061ddf455b0519484f959ca3ba9a342c38172c2cd927eb7f641f31`; đã đọc ZIP trong bộ nhớ, không thực thi package. Wheel có sẵn `akaocr/recog/data/model.onnx` (16.517.247 bytes) và `akaocr/recog/data/vocab.txt` (18.383 entries). PyPI khai báo package Apache-2.0; kiểm tra LICENSE và phạm vi weights trước tích hợp.
- **Cảnh báo quan trọng:** default AkaOCR recognition source ghi supported English; vocabulary thiếu nhiều ký tự tiếng Việt như `ơ`, `ư`, `ả`, `ạ`, `ắ`, `ế` và nhiều biến thể khác. Nếu benchmark default bundled checkpoint, ghi rõ là additional/reference baseline với giới hạn vocabulary, không gọi là model chuyên tiếng Việt hay đại diện hệ thống AkaOCR thương mại. Nếu user có checkpoint AkaOCR tiếng Việt khác, cần exact weight/vocab/license và pin riêng; không âm thầm thay checkpoint để làm đẹp kết quả.
- `TextEngine` của AkaOCR catch exception và có thể trả `None`; adapter phải bắt vi phạm contract/fail rõ, không bỏ crop hoặc giả output rỗng thành success. Backend có sort aspect ratio rồi restore indices, cần test đúng order/cardinality và CUDA provider.
- VietOCR reference source đã clone tại `scratch/ocr-recognizers/sources/vietocr`, commit `fe8c3a7fc714aec57ab81cec844eb3adf0c1636c`. Config chính thức ở `config/vgg-seq2seq.yml` và `config/vgg-transformer.yml`.
- URLs từ config chính thức: `https://vocr.vn/data/vietocr/vgg_seq2seq.pth` (HEAD 200, 89.575.371 bytes), `https://vocr.vn/data/vietocr/vgg_transformer.pth` (HEAD 200, 151.815.373 bytes), tại thời điểm kiểm tra. Chưa tải checkpoint từ hai URL này trong lượt bổ sung.
- Phải so hash checkpoint Seq2Seq chính thức với FastOCR weight hiện tại. Không mặc định chúng khác nhau vì tên package; nếu trùng weights, ghi là so sánh upstream implementation/preprocessing/decoding với FastOCR fork, không phải checkpoint huấn luyện mới độc lập.
- FastOCR hiện chỉ có config `vgg_seq2seq` trong `fastocr/tool/config.py`, không hỗ trợ `vgg_transformer` chỉ bằng đổi tên config. Không giả factory FastOCR hiện có đã chạy được Transformer; dùng adapter upstream-compatible và isolated dependencies nếu cần.

Workflow sau lượt hiện tại: pin/download assets và license/source -> adapter theo protocol chung + tests -> fresh FastOCR control sau thay đổi shared code -> smoke các regression documents -> đủ 183 trang/6.619 crop -> KIE, raw text changes và timing theo file/trung bình trang. Confidence policy, GT freeze và các cấm thay detection/extraction/GT vẫn giữ nguyên. Không thêm transcription GT/fine-tune vào scope này.

### Bổ sung tiếp: DungHugging handwriting và thảo luận TrOCR word-level

- **Thứ tự user chốt mới nhất:** hoàn tất lượt 4 model hiện tại, sau đó test AkaOCR, VietOCR gốc `vgg_seq2seq`/`vgg_transformer` và DungHugging handwriting. **TrOCR–Thaito98 cùng word segmentation để cuối cùng**, không triển khai/chạy nhánh này trước các model trên. Thiết kế segmentation bên dưới chỉ là phương án tham khảo cho giai đoạn cuối, chưa phải job được khởi chạy.
- User đã yêu cầu **thêm DungHugging VietOCR handwriting sau lượt hiện tại**, ngoài AkaOCR và hai VietOCR gốc. HF: `https://huggingface.co/DungHugging/vietocr-handwritten-finetune`; checkpoint công khai đã xác minh ở bước shortlist là `transformerocr.pth`, kèm `config.yml`. Model card ghi MIT và CER 4,01% trên validation UIT-HWDB, không coi đó là test CER trên dataset của repo. Pin revision/hash và kiểm tra config/vocab/license trước chạy; không nhầm với vudang449 đã có.
- User hỏi khả năng thêm word segmentation để dùng TrOCR–Thaito98 trên line cache, gợi ý gom thành module/function/util. Đây là **nhánh thiết kế/ablation đang thảo luận**, chưa được chèn vào job hiện tại; chốt giao thức/control trước khi thực thi.
- Đã đọc source công khai của `Thaito98/vietnamese-handwriting-ocr` tại `detectors/easyocr_det.py` và `detectors/paddle_det.py`: app lần lượt gọi `easyocr.Reader(["vi", "en"], recognizer=False).detect(...)` hoặc `PaddleOCR(... lang="en", use_gpu=False).ocr(... det=True, rec=False, cls=False)`, sau đó đổi detected boxes thành rectangles. **Không có bước bảo đảm mỗi box đúng một từ** trong hai wrapper này. Không khẳng định detector mặc định đã word-level; EasyOCR có thể group vùng, Paddle detector thường có thể trả cả dòng. Không sao chép cấu hình CPU-only của demo nếu backend hỗ trợ GPU.
- Thiết kế đề xuất: `WordSegmenter.segment(line_bgr)` trả ordered word crops + local boxes/indices; `WordToLineRecognizer(segmenter, word_recognizer)` nhận nguyên line crops và trả đúng một `(text, score)` cho mỗi line theo protocol hiện có. Đây là image-space splitting theo khoảng trắng/cụm chữ, không phải NLP tokenization từ ghép tiếng Việt.
- Giữ nguyên 6.619 parent line crops, page detector/layout và downstream line geometry. Cache word crops theo `(document_id, physical_page_index, line_detection_index, word_index)`; lưu hash parent/word, segmentation backend/config/version, tọa độ local, thứ tự và trường hợp cắt thiếu/trộn/không detect. Không giả empty/no-detection là success hoặc âm thầm dùng một model fallback.
- Dù đóng gói thành một adapter plug-and-play, thí nghiệm có thêm **segmentation + recognition**, không còn là pure recognizer-only swap. Tên run/report phải thể hiện composite branch.
- Control tối thiểu đề xuất: A = FastOCR đọc nguyên line (đã có); B = cùng word segmentation + FastOCR rồi ghép line; C = **cùng cached word crops** + TrOCR rồi ghép line. A/B chỉ ra ảnh hưởng segmentation/context/assembly; B/C so recognizer khi cố định word inputs. Chốt rule ghép khoảng trắng/punctuation trước chạy, giữ raw words và không dùng GT để sửa text.
- Gate: trước hết visual smoke các dòng in/viết tay/dấu đè/dòng dài để xác nhận word splitting, rồi mới xét full cached ablation và tính KIE/timing gồm cả segmentation. Khi chưa có transcription gold thì vẫn không báo recognition CER/WER. Nếu cần detector khác, dependencies hoặc split policy bổ sung ngoài thiết kế đã chốt, trình bày xin duyệt trước.

### Cập nhật thực thi: lượt đầu xong, supplementary adapters sẵn sàng

- User đã mở scope **chuẩn bị source/adapter/test các model bổ sung song song trong lúc SenOCR chạy**, không chờ rảnh; vẫn giữ TrOCR cuối. Đã làm preparation mà không sửa bất kỳ file runtime nào được primary fingerprint ghi nhận hoặc registry của job đang chạy.
- Primary runner đã notification **completed** và log xác nhận cả 4 full runs xong, mỗi model 100 document / 183 trang / 6.619 crop. Document Success: FastOCR 40/100; OcrDoc 26/100; vudang449 28/100; HTR-ConvText 0/100; SenOCR 47/100. Không kết luận nguyên nhân khi chưa visual review.
- SenOCR so FastOCR: 301 field-value thay đổi, 65 improvements, 54 regressions. F1 tăng ở title/documentDate/officeSender nhưng giảm ở code/recipients/signer; chưa đủ cơ sở promote thành default dù Document Success tăng.
- Timing primary đã xuất: `ocr-collab/artifacts/recognizer_ab_20261015/timing_primary_final/`. Mean recognition seconds/selected page: FastOCR 0,305; OcrDoc 3,270; vudang449 13,803; HTR-ConvText 0,396; SenOCR FP32 43,075. Là adapter wall time theo cấu hình/batching/IPC hiện tại, không phải benchmark kernel đã tối ưu hoặc giao thức tài nguyên độc lập. CPU preparation từng chạy song song đoạn cuối SenOCR nên không tuyên bố điều kiện host exclusive.
- Aggregate report lần đầu `comparison_primary/` bị timeout trong bước tổng hợp metadata strata, chưa complete và được giữ nguyên. Đã tối ưu report để aggregate lại benchmark cells có sẵn thay vì re-score/compare mọi field nhiều lần; test đối chiếu với benchmark chuẩn pass. Lượt `comparison_primary_v2/` đang chạy background postprocessing, không inference; chỉ dùng khi manifest completed.
- Đã tải đủ 4 supplemental assets theo `conf/recognizers/additional_catalog.json` và export pinned source; `scripts/download_additional_recognizers.py` tạo download manifests. AkaOCR default bundled vocabulary có giới hạn tiếng Việt như đã ghi ở trên.
- **Đã xác minh cùng weight:** official VietOCR Seq2Seq và `fastocr/weight/vgg_seq2seq.pth` cùng SHA-256 `0921503a41375a0584268e23ef3d414ea478a8fe8777865c7745d38f2d0bc5db`. Nhánh upstream Seq2Seq là so implementation/preprocessing/decoding với FastOCR, không phải checkpoint khác.
- Adapter mới: `module/ocr/recognizers/akaocr.py`, `vietocr_original.py`, `source_utils.py`. Native upstream VietOCR width-bucket restore, safe state loading và raw confidence/truncation được giữ. AkaOCR dùng Recognitor trực tiếp để không nuốt lỗi qua TextEngine.
- **CPU functional smoke đã pass cả 4**, mỗi model 7 crop thật, không có GT transcription. Artifact: `ocr-collab/artifacts/recognizer_ab_additional_20261015/preparation_cpu_smoke/manifest.json`; CUDA không được initialize trong smoke process. Đây chưa phải KIE hoặc GPU benchmark.
- Sau khi primary runner xong, đã activate thêm 2 backend keys `akaocr`, `vietocr_original` trong registry. Factory integration tests pass. Đã khởi chạy fresh FastOCR control dưới `ocr-collab/artifacts/recognizer_ab_additional_20261015/fastocr_control/`, log `/tmp/opencode/additional-fastocr-control-20261015.log`.
- **Next khi fresh control notification:** xác minh 6.619 crop và 100 prediction khớp baseline, rồi chạy `uv run python scripts/run_additional_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_additional_20261015 --stage all` background. Runner đã chuẩn bị, gate primary completion + registry + fresh control; smoke 5 mandatory docs trước full GPU cho 4 cấu hình bổ sung. Không sửa shared OCR code khi lượt mới đang chạy.

### Đính chính user về FastOCR ONNX, cần giữ rõ hai runtime

- User quan tâm so original checkpoint với **FastOCR ONNX** về output/KIE/timing. Đã trả lời rõ primary FastOCR control hiện là **PyTorch `.pth`**, không phải ONNX recognition; ONNX baseline đang dùng là page text detector. Không gọi kết quả control PyTorch là kết quả FastOCR ONNX.
- Có 3 graph local chưa được benchmark trong lượt này: `fastocr/weight/cnn.onnx`, `encoder.onnx`, `decoder.onnx`. Đã inspect graph bằng ONNX Runtime CPU, chưa chạy inference nhánh này và chưa xác nhận graph weights tương đương checkpoint gốc.
- Graph SHA-256 lần lượt: `c84b9df2244f99f0b54e801ad53ab076471492219c30455633078d12e0ab76dc`, `936ec6d0291f3b3474842d8e75fc9c95c453ea775c70237ec7ce166cb0375854`, `1611c0ddda570e88cab9b9304cc22dec4be58b1e9a761f5a586b396cbd82c05e`.
- CNN input `[1,3,32,dynamic_width]`; encoder/decoder cũng cố định batch 1. Nếu bổ sung nhánh ONNX, phải ghi rõ giới hạn batch và không suy throughput từ batch 128 của PyTorch. Kiểm tra preprocessing, vocab 233, SOS/EOS và autoregressive hidden state, provenance/parity trước scoring. Ba graph này không có custom metadata để tự xác nhận nguồn checkpoint.
- Không âm thầm thay bốn supplemental configs hiện tại bằng ONNX. Trước khi triển khai nhánh mới, chốt đúng graph/version với user và giữ PyTorch control làm mốc riêng; TrOCR vẫn cuối cùng.

### Notification đã xử lý: primary report complete, supplementary GPU jobs khởi chạy

- Đã xác nhận `comparison_primary_v2/manifest.json` completed. Báo cáo dễ đọc: `ocr-collab/artifacts/recognizer_ab_20261015/REPORT.md`; detailed field/bucket/strata và timing CSV đã có. Visual review/root-cause classification vẫn pending, không báo recognition CER/WER.
- Fresh supplemental control đã **completed và verified**: 6.619/6.619 crop results exact, saved-block/reassembly/candidate predictions đều 100/100 exact, `ab_ready=true`. Artifact `ocr-collab/artifacts/recognizer_ab_additional_20261015/fastocr_control/`.
- Đã khởi chạy background `uv run python scripts/run_additional_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_additional_20261015 --stage all`. Shell ID `sh_140085663001KkxvrQFtwVEMOT`; driver log `/tmp/opencode/recognizer-ab-additional-runner-20261015.log`. Đang chạy GPU smoke rồi full theo gate; **chưa gọi supplementary runs đã hoàn tất**.
- Tiếp theo: chờ notification driver, đọc log và coverage từng model; xuất comparison/timing cho completed subset hoặc toàn cohort, không overwrite artifact cũ. Shared OCR/registry/config đã freeze cho lượt mới; không sửa trong lúc job chạy. TrOCR và FastOCR ONNX branch chưa chạy.

### User duyệt chạy hết, bao gồm TrOCR cuối; supplementary completed

- User yêu cầu tiếp tục khi đi ngủ, **cố gắng chạy được TrOCR cuối cùng**, test và báo cáo checkpoint/config/preprocessing/decoding/batching/timing đầy đủ. Phạm vi là benchmark, không promote default, đổi GT hoặc sửa extraction.
- Supplementary driver đã completed. Mỗi model 100 file / 183 trang / 6.619 crop: AkaOCR Document Success 0; VietOCR gốc Seq2Seq 41; VietOCR gốc Transformer 47; DungHugging 0. DungHugging 10 improvements / 578 regressions, mean recognition 5,742 s/selected page. Chưa có causal visual review đầy đủ. Đã xuất `comparison_final/` và `timing_final/` trong supplemental artifact root.
- Đã tải TrOCR từ `Thaito98/vietnamese-handwriting-ocr`, pinned revision `823e8848ef9b676940af8d516f7fbba3041097bf`, checkpoint LFS SHA-256 `2a94382180088ce9e9d433e4f5920ba1a128363e79cbb9fbfeaa591e8b16e290` (1.335.747.032 bytes). Assets và hashes tại `scratch/ocr-recognizers/models/trocr_thaito98/download_manifest.json`; không dùng remote code.
- Composite adapter mới `word_to_line` giữ parent line geometry và neutral score 1.0. Chọn **deterministic Otsu + vertical whitespace projection**, không thêm page detector: gap >= max(2, ceil(0.18 * parent height)), pad ngang 1 px, giữ nguyên chiều cao/diacritics; không xóa mực dấu. Đây là image-space whitespace heuristic, **không đảm bảo box nào cũng đúng 1 từ**. Không dùng label/filename/GT trong splitting. EasyOCR/ninja đã tải isolated target trong bước khảo sát nhưng không dùng trong adapter/runtime.
- Đã visual inspect 7 crop smoke và 32 crop header/footer từ case 155 (có chữ viết tay, dấu đè): sample dài thường split tốt; bold heading cần tránh character split; tight/justified/multi-line/vertical và dấu nối chữ vẫn có undersegmentation. Policy 0.22 và 0.12 được khảo sát **trước scoring**, chỉ theo ảnh; chốt 0.18, artifacts cũ giữ nguyên. Review tại `recognizer_ab_trocr_20261015/segmentation_review_final/review.json`: cho phép **diagnostic**, không gọi segmentation production-ready.
- Protocol: A = fresh FastOCR line control, B = same word splitting + FastOCR PyTorch batch tối đa 128 words, C = same cached word mapping + TrOCR CUDA FP32 batch 8 words. Parent batch 16; C isolated worker IPC 32 parent crops. TrOCR greedy num_beams=1/do_sample=false/max_new_tokens=64, 384x384 resize + normalization từ upstream processor config; join decoded stripped words bằng đúng 1 ASCII space, không sửa dấu câu bằng GT. Raw words/token IDs/boxes/hashes/truncation giữ trong `recognition_details`.
- Đã khắc phục hai blocker của GPU probe: tokenizer chỉ có tokenizer.json nên dùng fast tokenizer (không dùng slow Roberta thiếu vocab/merges); PyTorch 2.13 native bmm gọi Triton cần C compiler nên worker đặt `TORCH_DISABLE_NATIVE_JIT=1`, giống workaround SenOCR, vẫn CUDA không fallback CPU. GPU probe đã chạy được 7 crops; chưa gọi output đúng hoặc full run completed.
- Đã pass **27 recognizer/reporting tests + 70 VBHC tests**, gồm 5 test mới cho segmentation/cache/ordering/blank/neutral score. Word adapter/config runtime đã freeze trước fresh control. Fresh control background shell `sh_14045fdc8001NfL0RqtlqKc1Gi`, log `/tmp/opencode/trocr-fastocr-control-20261015.log`.
- Offline word cache preparation background shell `sh_14046e880001QldeEbY2vkdtNB`, log `/tmp/opencode/trocr-word-cache-20261015.log`, mapping output `recognizer_ab_trocr_20261015/word_crop_cache_manifest.json`. Cả B/C dùng warm cache; báo riêng segmentation compute/preparation cost, không gọi cached inference là full online segmentation latency. Không thêm timing-only inference pass.
- Khi control + cache notification completed: verify exact control 6.619/100; chạy `uv run python scripts/run_trocr_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_trocr_20261015 --stage all` background. Runner gate supplementary completed + visual review, 5-doc smoke trước mỗi full. Không sửa module OCR/config khi job chạy. Sau đó xuất detailed comparison/timing và final config-rich report. FastOCR ONNX vẫn ngoài lượt đã chạy.

### TrOCR final cohort đã khởi chạy sau control notification

- Fresh line control đã verified completed/ab_ready: 6.619 crop exact, 100 document prediction exact, 0 changed cells. Frozen word mapping completed: 6.619 parent crops -> 52.542 segments, 3 blank parents; đây không phải annotation xác nhận 52.542 từ đúng.
- Đã khởi chạy `uv run python scripts/finish_trocr_recognizer_ab.py` background, shell `sh_1404b5468001up1hTvSBPYT8Bc`, log `/tmp/opencode/trocr-final-cohort-20261015.log`. Wrapper chạy gated smoke/full FastOCR-word control + TrOCR, xuất comparison với line control và riêng TrOCR-vs-same-word-FastOCR, timing và report cuối. Không gọi completed trước notification/manifest.
- Report cấu hình tạm: `ocr-collab/artifacts/recognizer_ab_all_20261015/progress_configs/REPORT.md`; wrapper sẽ tạo report cuối mới tại `recognizer_ab_all_20261015/final/REPORT.md`. Report kiểm tra fingerprints GT và metric 2.2 giữa các cohort, giữ checkpoint/source hashes, config, preprocessing/decoding/batching, runtime packages, timing/file và per-field metrics.
- Validation hiện tại: **106 tests pass** (27 recognizer/reporting, 9 cache harness, 70 VBHC), compileall và git diff --check pass. Không sửa OCR runtime/config khi final cohort chạy.
- User hỏi vì sao thêm FastOCR words; đã giải thích bằng ví dụ: baseline cũ đọc nguyên dòng; control mới đọc cùng mảnh từ với TrOCR để phân biệt ảnh hưởng segmentation/context và recognizer. Đây là control B của thiết kế, không chạy lại full page pipeline và không bắt buộc để lấy số TrOCR đơn lẻ. User chưa yêu cầu bỏ control.

### 2026-10-16: phát hiện job không còn chạy, resume từ 98 checkpoints

- User không thấy process/GPU usage và yêu cầu kiểm tra. Kiểm tra trực tiếp `ps` và `nvidia-smi` lúc khoảng 00:37 +07 xác nhận **không còn benchmark/TrOCR worker**. Full log dừng ở 98/100, checkpoint cuối `920+QĐ-NHNN_2020-05-12` lúc 00:13:59 +07. Không có completed manifest hay report cuối. Log không có traceback/nguyên nhân termination; không suy đoán OOM hoặc kill khi chưa có evidence.
- Đã đính chính với user: lần báo trước chỉ dựa vào checkpoint, không xác minh liveness, nên câu "vẫn chạy" không có đủ bằng chứng. Những lần sau phải phân biệt saved progress với active process.
- Đã khởi chạy lại đúng full TrOCR với `uv run python scripts/run_trocr_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_trocr_20261015 --stage full --model trocr_words --resume`, không sửa code/config/model/GT. Shell `sh_140a4607f0019l5IgsXi7euhuL`, log `/tmp/opencode/trocr-resume-20261016.log`. Kiểm tra process ngay sau launch thấy runner PID 703468 và harness PID 703469. Đây là launch/liveness, chưa chứng minh resume fingerprint đã pass hoặc GPU inference đã bắt đầu.
- Wrapper `finish_trocr_recognizer_ab.py` cũ không còn chạy nên sau resume notification phải thực hiện các bước postprocessing còn thiếu thủ công: comparison line-control, timing, TrOCR-vs-same-word-FastOCR và `scripts/build_recognizer_final_report.py .../recognizer_ab_all_20261015/final`. Không khởi động lại wrapper nguyên trạng vì smoke/control/full FastOCR đã tồn tại. Kiểm tra fingerprint error nếu resume fail, không bypass guard.

### 2026-10-16: final inference và postprocessing completed

- Resume runner completed; TrOCR manifest completed, đủ 100 document / 183 selected pages / 6.619 parent crops. 98 checkpoints được tái sử dụng theo fingerprint guard, chỉ inference 2 document còn lại. Đã kiểm tra process sau hoàn thành: không còn benchmark worker, đây là trạng thái hoàn thành chứ không phải inference vẫn chạy.
- Đã chạy thủ công và verify completed manifests: `recognizer_ab_trocr_20261015/comparison_final/`, `trocr_vs_same_word_fastocr/`, `timing_final/`, và báo cáo chung `recognizer_ab_all_20261015/final/REPORT.md`. Final report manifest completed, không còn missing runs.
- Kết quả cohort cuối: FastOCR whole-line 40/100 Document Success, 0,396 s/selected page; same-word FastOCR 8/100, 1,282 s/page; TrOCR composite 0/100, 19,680 s/page. Composite timing dùng cached segmentation mapping như đã mô tả, offline segmentation cost báo riêng. Không suy nguyên nhân toàn bộ từ một summary, không gọi đây là recognition CER/WER hoặc clean word-recognizer ranking.
- User yêu cầu monitoring 30–40 giây và đã thêm rule ngắn trong global AGENTS.md. Đã thừa nhận với user **chưa thực sự duy trì monitoring định kỳ** trong khoảng trao đổi vừa qua; không nói việc sửa rule đồng nghĩa đã có monitor daemon hoạt động. Hiện không còn inference cần theo dõi trong cohort này.
- FastOCR vẫn default; GT/extraction không đổi. Visual root-cause review đầy đủ còn pending. Validation trước final cohort giữ 106 tests pass; không khẳng định đã chạy lại tests ở lần postprocessing cuối này.

### 2026-10-16: approved Nôm Tesseract raw / spell-corrected cohort

- User yêu cầu thử Tesseract qua Nôm, with/without `nrl-ai/vn-spell-correction-base`, giữ cache dòng. Đã báo blocker: documented `nom.doc.ocr.TesseractOCR` absent trong source và PyPI 0.2.37; source hiện có `nom.doc.stages.OCR`. User **explicitly approved** wrapper thật và cài pinned source/runtime riêng, không đổi baseline env.
- Source Nôm pinned `2c99458ff55d7aa6b8c97398e2f0b1282efbcb73`, exported `src/nom/` + LICENSE/pyproject dưới `scratch/ocr-recognizers/models/nom_tesseract/source/`. Source package được worker import trực tiếp, không cài toàn bộ dependency stack Nôm vào baseline. Isolated pytesseract 0.3.13 dưới `scratch/ocr-recognizers/nom-deps/`.
- Rootless Tesseract 5.5.1 từ alex-p/tesseract-ocr5 jammy packages (SHA-256 kiểm tra), libtesseract5 + Ubuntu leptonica/libgif/libwebpmux được extract riêng, không sudo/system install. Binary --version verified. `vie.traineddata` từ tessdata_best revision `e12c65a915945e4c28e237a9b52bc4a8f39a0cec`; spell model revision `ba1e57fc3bacdfb22bfa20b19db7182a6d1b0b6b`. 261 asset hashes trong download_manifest.json.
- Config predeclared: PSM 6/OEM 1/vie, OMP_THREAD_LIMIT=1, no external auto-preprocess/deskew/resize/NFC/fallback (actual upstream stage chỉ text.strip); giữ original crop geometry. Raw full branch CPU OCR tuần tự từng crop, parent batch 16 / worker IPC 32. Corrected branch **không OCR lại**, đọc text raw theo RGB/policy/text hash, gọi upstream HFDiacriticModel.predict_batch CUDA FP32, batch 16, greedy beams1, max input/generation length512, heading_retry=True native. Không thêm field protection/confidence gate/GT rules. No token IDs exposed by upstream: input truncation measured, output truncation unknown.
- `module/ocr/recognizers/nom_tesseract.py`, 2 JSON configs, downloader, supervised runner, report và 7 unit tests mới đã tạo. Tests latest **113 pass**: 34 recognizer/reporting, 9 cache harness, 70 VBHC; compileall + git diff --check pass. Functional probe: cả raw/spell chạy 7 crops thật, sample outputs lưu tại `recognizer_ab_nom_20261016/preparation_probe/`; không dùng probe timing như full benchmark.
- Asset download đã completed dưới supervisor, health events `/tmp/opencode/nom-assets-20261016.log.health.jsonl`. **Monitoring lần này thực sự được triển khai**: `scripts/monitor_recognizer_job.py` kiểm tra child liveness/exit, log/checkpoint progress và GPU mỗi 40 giây; stage failures stop immediately, silence >=300s warns, không suy GPU idle = failure khi CPU/preflight/report.
- Đã khởi chạy final supervised driver background shell `sh_144cd9e64001avoGXoUmFtT6n4`: `uv run python scripts/monitor_recognizer_job.py --log /tmp/opencode/nom-benchmark-20261016.log --progress-root ocr-collab/artifacts/recognizer_ab_nom_20261016 -- uv run python scripts/run_nom_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_nom_20261016`. Driver tự chạy fresh exact FastOCR control, smoke raw/spell, full raw/spell, comparisons vsFastOCR + direct spell-vsraw, timing và REPORT.md. Chưa gọi benchmark complete trước notification/manifests. OCR runtime/config/dependencies freeze trong lúc job chạy.
- Report mới nằm riêng trong `recognizer_ab_nom_20261016/`, không overwrite report cohort trước. Corrected adapter timing chỉ correction/cache/IPC, phải cộng raw stage để mô tả two-stage cost; report exports riêng native OCR, correction, per-file + weighted selected-page means, pairs 6.619 crops và field improve/regress. No recognition CER/WER vì không có transcription GT.

### Nôm cohort completed; all-model F1/NEM charts delivered

- Supervised driver đã notification EXIT 0. Raw và spell manifests completed, mỗi model 100 file / 183 trang / 6.619 parent crops. `paired_report_manifest.json` completed: toàn bộ 6.619 raw inputs giống nhau giữa hai nhánh, corrected không OCR lại, 2.328 crop texts thay đổi, 0 input truncations (output truncation unknown theo wrapper).
- Document Success: Tesseract raw **17/100**, +spell **19/100**. Direct field bucket transitions: **49 improvements / 17 regressions**. Không suy mọi text thay đổi là cải thiện hay promote default. Full paired report `ocr-collab/artifacts/recognizer_ab_nom_20261016/REPORT.md`; detailed comparisons, pairing CSV, per-file timing đã xuất.
- Raw adapter 1.393,104 s total (7,613 s/selected page); correction-only adapter 684,796 s (3,742 s/page); measured two-stage sum 2.077,899 s (11,355 s/page). Includes native wrapper subprocess/cache/IPC overhead; không phải fused online latency. Không chạy timing-only inference.
- User yêu cầu **F1 và NEM từng model theo 12 trường + bar charts**. Đã tạo `scripts/plot_recognizer_field_metrics.py` và chart output riêng `ocr-collab/artifacts/recognizer_ab_all_20261015/field_charts_20261016/`: REPORT.md có 12 bảng, CSV 156 model-field rows, 2 overview charts F1/NEM mỗi chart 12 panels (PNG + SVG), và 12 ảnh riêng mỗi field có F1/NEM side-by-side. 13 configurations gồm 1 fresh FastOCR baseline, 4 primary, 4 supplemental, 2 word composites, 2 Nôm variants; không lặp các FastOCR controls.
- Plot loader verify completed coverage/metric2.2, GT hashes giống nhau và khớp GT hiện tại, cùng baseline predictions/config/cache provenance. Không rescore hoặc inference để vẽ. N/A được giữ khác 0; F1 target85/90%, NEM75%; labels tiếng Việt + API key + field group, common percentage scale. Composite và post-correction được ghi rõ, không clean recognizer-only ranking.
- Đã thực sự xem overview F1 và ảnh title để kiểm tra layout; validation đủ 14 PNG, 2 SVG, 156 unique rows. Latest **38 recognizer/report/chart tests pass**, trước đó 9 cache + 70 VBHC pass; git diff --check pass. 4 chart tests mới kiểm tra null/zero, ratio range/NaN và uniqueness/scope.

### 2026-10-19: TrOCR saved-output error report + executed notebook

- User approved report + notebook with 30 actual visual crop reviews, offline only. Completed artifact: `ocr-collab/artifacts/trocr_error_analysis_20261019/REPORT.md` and `trocr_error_analysis.ipynb`. Notebook has 15 cells / 8 executed code cells, no cell errors; source training notebook is downloaded for reading only and was NOT executed. No inference, training, GT/model/runtime modifications.
- Fine-tuning provenance confirmed from pinned README and training notebook: Microsoft TrOCR base-handwritten -> HANDS-VNOnDB word handwriting, declared 10 epochs. No local VBHC fine-tuning. Author word-accuracy/CER claims are not reproduced or interchangeable with hybrid KIE.
- **Important qualification finding:** root model config decoder_start=0, saved generation_config decoder_start=2; local adapter inherited2. Upstream test notebook explicitly uses cls_token_id=0, beam4, max_new_tokens32, no_repeat_ngram3; measured local run used start2, greedy1, max64, ngram0. All52.542 saved sequences start `[2,0,...]`. This is confirmed decoding drift, NOT proof or measured magnitude of its causal effect. Do not call old TrOCR run a faithful upstream evaluation or 0% word accuracy. Do not silently change defaults/rerun full benchmark; propose controlled same-word smoke first after approval.
- Verified same parent/word boxes, hashes and order between B FastOCR-words and C TrOCR for6.619 parents /52.542 segments. Geometry risks:1.061 parents have a segment aspect>5;1.324 have a narrow segment<0.35;141 tall parents include tiny/nonword fragments;3 blank parents. These are flags, not segmentation-error prevalence. B/C raw word agreement20.984/52.542=39.94%, not accuracy. Saved word outputs have0 empty/0 truncation flags; no transcription GT so no recognition CER/WER.
- Actually viewed all30 final evidence cards via image tool. Reviews include undermerge, digit/punctuation fragmentation, clean-boundary recognition discrepancies, handwritten07 that C reads correctly while B does not, mixed written/printed date, stamped signer and blank/uncertain cases. Initial candidate sampling was refined to actual writing/stamp regions; old selection saved. `visual_reviews.json/csv`, `image_view_ledger.csv` preserve per-case evidence hashes and recorded review time, without inventing exact tool-view timestamps. Labels apply to reviewed observations only, not training GT or dataset prevalence.
- Integrity validation passed:662 protected source/result/GT files unchanged, all6.619 parent RGB hashes rechecked, model files match download hashes. Report has A/B/C per-field F1/NEM, diagnostic plots,30 linked visual cases, reproducible extraction/build scripts and next actions. Model config/start-token effect, beam, segmentation, assembly and domain need distinct future ablations.
- Latest validation: **125 tests pass** (4 new offline error-analysis,42 recognizer/report/chart,9 cache,70 VBHC); git diff --check pass. Supervised offline extraction and notebook builds both EXIT0. No pending jobs for this analysis.
