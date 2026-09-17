# OCR/KIE Pipeline Benchmark Metrics

## 1. Context

This benchmark evaluates an end-to-end OCR/KIE pipeline that extracts structured metadata from Vietnamese administrative documents (VBHC).

The pipeline may use OCR, layout analysis, rules, NLP/KIE, VLMs, or a hybrid approach. The benchmark is intended for demo/baseline comparison first, while remaining simple enough to reuse for later R&D.

Typical extracted fields include:

- `type`
- `title`
- `code`
- `documentDate`
- `officeSender`
- `recipients`
- `signer`
- `priority_level`
- `security_level`
- `first_recipients`
- `signer_title`
- `province`
- `receiverDate`

### 1.1 Field Specification / Mô tả trường

| Field              | Evaluation type | Mô tả / format                                                                                                                                                                        |
| ------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`             | Text            | Hình thức/thể loại văn bản.                                                                                                                                                           |
| `title`            | Text            | Trích yếu nội dung văn bản.                                                                                                                                                           |
| `code`             | Text            | Số ký hiệu văn bản; so sánh không phân biệt hoa/thường và giữ `/`, `-`.                                                                                                               |
| `documentDate`     | Date            | Ngày văn bản; parse và chuẩn hóa về `dd/mm/yyyy`.                                                                                                                                     |
| `officeSender`     | Text            | Cơ quan gửi/ban hành; giữ thứ tự hiển thị/đọc từ trên xuống dưới, trái sang phải; không sắp xếp lại thành `[cơ quan con]/[cơ quan cha]`.                                              |
| `recipients`       | Text            | Nơi nhận — tên cơ quan, tổ chức, cá nhân trong phần `Nơi nhận`; nhiều giá trị theo thứ tự trên xuống dưới, trái sang phải, phân cách bằng `;` và đánh giá toàn bộ text sau chuẩn hóa. |
| `signer`           | Text            | Họ tên người ký; nhiều giá trị theo thứ tự trên xuống dưới, trái sang phải, phân cách bằng `;` và đánh giá toàn bộ text sau chuẩn hóa.                                                |
| `priority_level`   | Enum            | Độ khẩn: `0_BÌNH THƯỜNG`, `1_HỎA TỐC`, `2_KHẨN`, `3_THƯỢNG KHẨN`.                                                                                                                     |
| `security_level`   | Enum            | Độ mật: `0_BÌNH THƯỜNG`, `1_MẬT`, `2_TỐI MẬT`, `3_TUYỆT MẬT`.                                                                                                                         |
| `first_recipients` | Text            | Người/nơi nhận ở đầu văn bản, thường sau `Kính gửi`; cùng format với `recipients`.                                                                                                    |
| `signer_title`     | Text            | Nội dung `KT./TM./chức vụ/quyền hạn ký`; cùng format nhiều giá trị với `signer`.                                                                                                      |
| `province`         | Text            | Tỉnh/thành phố của cơ quan ban hành.                                                                                                                                                  |
| `receiverDate`     | Date            | Ngày nhận văn bản; parse và chuẩn hóa về `dd/mm/yyyy`.                                                                                                                                |

Important: a field may be logically required by business or document conventions but still be absent from the actual PDF input. Evaluation ground truth must therefore reflect **what is observable in the PDF being evaluated**, not metadata available only from an external source page.

### 1.2 Empty and default output contract

- Text and date fields always use a JSON string. If the field is absent, not
  detected, or not recognized, return the empty string `""`; do not return
  `null`.
- `receiverDate` is read from a visible receipt/arrival stamp such as a
  `ĐẾN ... Ngày:` block. Do not substitute `documentDate`, posting time,
  download time, or OCR execution time. If the stamp/date is not recognized,
  return `""`.
- `priority_level` and `security_level` always use their canonical enum. If
  the corresponding urgency/security stamp is absent or unreadable, return
  `0_BÌNH THƯỜNG`.

In the metric definitions below, **empty** means exactly the empty string
`""` after reading the prediction contract.

---

## 2. Business Objective

The system should:

1. Extract field values as accurately as possible.
2. Treat a text prediction as business-acceptable when character error is at most 5%.
3. Avoid both:
    - returning incorrect/hallucinated values;
    - missing values that actually exist.
4. Preserve a simple and explainable benchmark that BA, engineering, and management can understand.
5. Support error analysis that helps identify whether failures come from:
    - wrong text;
    - missing fields;
    - hallucinated fields;
    - substitution, deletion, or insertion errors.
6. Measure practical deployment cost through processing time, RAM, and VRAM.

Precision and Recall are considered equally important.

---

## 3. Text Normalization

**Context:** This benchmark evaluates semantic VBHC metadata extraction, not glyph-perfect OCR transcription.

**Objective:** Compare values in a practical, canonical form used by the business while preserving `raw_value` for audit/debug.

**Unicode normalization:** Apply **NFKC** to canonicalize compatibility-equivalent Unicode characters into a common form before evaluation.

Default evaluation normalization:

1. `unicodedata.normalize("NFKC", text)`
2. Trim + collapse whitespace.
3. Case-insensitive comparison.
4. Apply field-specific punctuation rules.

Notes:

- Always preserve the original `raw_value`; normalize only the value used for evaluation/business matching.
- Do not strip Vietnamese diacritics.
- Preserve `/` and `-` in all text fields because embedded document codes are structurally meaningful.
- Except for the canonical `;` separator in multi-value fields, ordinary text may ignore `, . : '"` when punctuation is non-semantic.
- `code` keeps structural punctuation such as `/`, `-`.
- Multi-value fields preserve reading order from top to bottom, left to right, use `;` as the separator, and are compared as whole text after normalization.
- Dates are parsed and normalized to canonical `dd/mm/yyyy`; enums are mapped to canonical classes.

---

## 4. Core Text Error Metric

For non-empty text GT, use traditional Character Error Rate (CER):

$$
CER = \frac{S + D + I}{|GT|}
$$

Where:

- `S`: substitutions
- `D`: deletions
- `I`: insertions
- `|GT|`: normalized ground-truth character length

Traditional CER is intentionally kept unbounded because large insertions/hallucinations should receive a large penalty.

A prediction is **acceptable at 5%** when:

$$
CER \le 0.05
$$

`@5%` means that the metric uses the 5% CER tolerance as the correctness threshold.

---

## 5. End-to-End Metrics by Field Type

### 5.1 Text fields

Examples:

- Single-value: `type`, `title`, `code`, `officeSender`, `province`
- Multi-value serialized as whole text: `recipients`, `signer`, `first_recipients`, `signer_title`

For multi-value fields, preserve reading order from top to bottom, left to right, then serialize using `;` before whole-text comparison.

#### NEM — Normalized Exact Match

Measures perfect normalized text equality.

$$
NEM =
\frac{\#\text{GT-present samples with normalized Pred = normalized GT}}
{\#\text{GT-present samples}}
$$

Use NEM to answer:

> How often is the extracted value completely correct?

For fields that may be absent, NEM is calculated only on GT-present samples so that `GT empty + Pred empty` does not inflate the score.

#### Precision@5%, Recall@5%, F1@5%

A text prediction is considered correct only when `CER <= 0.05`.

Classification:

| Case                                    | Count   |
| --------------------------------------- | ------- |
| GT present, Pred present, `CER <= 0.05` | TP      |
| GT present, Pred present, `CER > 0.05`  | FP + FN |
| GT present, Pred empty                  | FN      |
| GT empty, Pred present                  | FP      |
| GT empty, Pred empty                    | TN      |

$$
Precision@5\% = \frac{TP}{TP+FP}
$$

$$
Recall@5\% = \frac{TP}{TP+FN}
$$

$$
F1@5\% =
2 \times
\frac{Precision@5\% \times Recall@5\%}
{Precision@5\% + Recall@5\%}
$$

**Primary text KPI:** `F1@5%`

**Secondary text KPI:** `NEM`

Precision and Recall are retained as drill-down metrics.

---

### 5.2 Date fields

Examples:

- `documentDate`
- `receiverDate`

Parse equivalent formats such as:

- `9/9/2026`
- `03/7/2026`
- `6/07/2026`

into the canonical representation `dd/mm/yyyy`, e.g. `02/03/2026`.

Do not use CER for dates. A date is an atomic structured value: changing one
digit can change the day, month, or year and must count as a semantic error.
Conversely, surface variants such as `9/9/2026` and `09/09/2026` should be
treated as equal after parsing rather than penalized by character distance.

For a canonical date of roughly 10 characters, one wrong character also gives
about 10% CER, so `CER <= 5%` mostly degenerates into exact matching while
still failing to express date validity. NEM after date parsing would agree
with exact match on GT-present samples, but it would not by itself capture
missing and hallucinated values. Therefore use field-level F1 Exact as the
primary metric.

Use exact field-level matching:

| Case                                 | Count   |
| ------------------------------------ | ------- |
| GT present, parsed Pred = parsed GT  | TP      |
| GT present, parsed Pred != parsed GT | FP + FN |
| GT present, Pred empty/unparseable   | FN      |
| GT empty, Pred present               | FP      |
| GT empty, Pred empty                 | TN      |

Metrics:

- `Precision Exact`
- `Recall Exact`
- `F1 Exact`

**Primary date KPI:** `F1 Exact`

Parsed exact accuracy/NEM may be reported as a secondary diagnostic, but it is
redundant with exact equality on GT-present canonical dates and must not
replace Precision/Recall/F1 Exact.

---

### 5.3 Enum / categorical fields

Examples:

- `priority_level`
- `security_level`

Map output to a canonical class before evaluation.

Examples:

- `KHẨN` -> canonical enum value
- `khẩn` -> same canonical enum value
- absent or unreadable urgency/security stamp -> `0_BÌNH THƯỜNG`

Do not use CER because a class mismatch is a semantic error, not a character-distance problem.

Use:

- `Precision Exact`
- `Recall Exact`
- `F1 Exact`

**Primary categorical KPI:** `F1 Exact`

---

## 6. Debug / Error Analysis Buckets

Each sample-field should belong to exactly one debug bucket.

### Text fields

| Bucket           | Condition                                   |
| ---------------- | ------------------------------------------- |
| `Exact`          | GT present, Pred present, `CER = 0`         |
| `Acceptable`     | GT present, Pred present, `0 < CER <= 0.05` |
| `Wrong`          | GT present, Pred present, `CER > 0.05`      |
| `Missing`        | GT present, Pred empty                      |
| `Hallucination`  | GT empty, Pred present                      |
| `Correct Absent` | GT empty, Pred empty                        |

Derived counts:

$$
TP = Exact + Acceptable
$$

$$
FP = Wrong + Hallucination
$$

$$
FN = Wrong + Missing
$$

### Date / enum fields

Use the same buckets except there is no `Acceptable` bucket:

- `Exact`
- `Wrong`
- `Missing`
- `Hallucination`
- `Correct Absent`

---

## 7. Character-Level Error Analysis

For text fields with non-empty GT, log:

$$
CER = \frac{S+D+I}{|GT|}
$$

$$
S_{rate} = \frac{S}{|GT|}
$$

$$
D_{rate} = \frac{D}{|GT|}
$$

$$
I_{rate} = \frac{I}{|GT|}
$$

Recommended visualizations:

- Raw CER histogram
- Substitution-rate histogram
- Deletion-rate histogram
- Insertion-rate histogram

Raw CER must not be clipped. Large CER values are useful for identifying severe insertion/hallucination failures.

A custom correction-effort metric such as:

$$
\frac{2S + D + I}{|GT|}
$$

is intentionally **not part of benchmark v1**. It may be added later if real user correction effort becomes a business KPI.

---

## 8. Performance / Resource Utilization

Benchmark the following five headline metrics:

| Metric                       | Meaning                                               |
| ---------------------------- | ----------------------------------------------------- |
| `Avg Processing Time / File` | Average end-to-end processing time for one input file |
| `Avg RAM / File`             | Average RAM usage while processing a file             |
| `Peak RAM / File`            | Maximum RAM usage while processing a file             |
| `Avg VRAM / File`            | Average GPU memory usage while processing a file      |
| `Peak VRAM / File`           | Maximum GPU memory usage while processing a file      |

GPU utilization percentage is not required for the current baseline.

Processing time must also be logged per file so it can be analyzed against document characteristics.

Recommended per-file metadata:

- `document_id`
- `num_pages`
- `document_format` — digital / scanned / image / mixed
- `has_handwriting`
- `layout_type`
- `processing_time_s`
- `avg_ram_mb`
- `peak_ram_mb`
- `avg_vram_mb`
- `peak_vram_mb`

This enables analysis such as:

- processing time vs. page count;
- digital vs. scanned documents;
- printed vs. handwriting-containing documents;
- simple vs. complex layouts.

---

## 9. Recommended Per-Sample Evaluation Log

```json
{
    "document_id": "...",
    "field_name": "title",
    "field_type": "text",

    "gt_raw": "...",
    "pred_raw": "...",
    "gt_normalized": "...",
    "pred_normalized": "...",

    "gt_present": true,
    "pred_present": true,

    "substitutions": 0,
    "deletions": 1,
    "insertions": 0,
    "cer": 0.02,

    "exact_match": false,
    "acceptable_at_5": true,
    "error_bucket": "Acceptable"
}
```

Date and enum fields do not need `CER`, `S`, `D`, or `I`.

---

## 10. Benchmark Report Structure

### Business / overall quality

Per field:

- `NEM`
- `F1@5%` for text
- `F1 Exact` for date / categorical fields

### Technical drill-down

- `Precision@5%`, `Recall@5%` for text
- `Precision Exact`, `Recall Exact` for date / enum
- Error-bucket counts/rates

### Error analysis

- Raw CER distribution
- `S_rate`, `D_rate`, `I_rate` distributions
- Inspect `Wrong`, `Missing`, and `Hallucination` samples

### Performance

- Avg Processing Time / File
- Avg RAM / File
- Peak RAM / File
- Avg VRAM / File
- Peak VRAM / File

---

## 11. Benchmark v1 Design Principle

Keep the benchmark focused on three questions:

1. **How correct is the final extracted information?**
2. **When it fails, what kind of failure occurred?**
3. **How much time and compute resource does the pipeline require?**

Any additional metric should only be added when it answers a concrete business or engineering decision that the current benchmark cannot answer.
