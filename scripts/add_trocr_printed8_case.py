"""Append the agy-reviewed printed tháng8 example, using saved outputs only."""
import argparse
import csv
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_trocr_saved_errors import read,write
from scripts.build_trocr_error_notebook import make_notebook,verify_inputs
from scripts.check_cached_ocr_equivalence import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agy_run",type=Path)
    args=parser.parse_args()
    output=ROOT/"ocr-collab/artifacts/trocr_error_analysis_20261019"
    run=args.agy_run.resolve()
    with (run/"findings.csv").open() as handle:
        row=next(r for r in csv.DictReader(handle) if r["document_id"]=="4977+BVHTTDL-VP_2026-08-07")
    evidence=output/"evidence/printed_thang8_4977.png"
    if evidence.exists() and sha256(evidence)!=sha256(row["evidence_crop_path"]):
        raise ValueError("Existing supplementary image differs; preserve it")
    shutil.copyfile(row["evidence_crop_path"],evidence)
    case=dict(case_id="printed_thang8_4977",document_id=row["document_id"],physical_page_0based=0,crop_index=3,
        visual_review_source="agy image inspection",agy_run=str(run),
        evidence_path="evidence/printed_thang8_4977.png",evidence_sha256=sha256(evidence),
        source_crop_path=row["source_crop_path"],source_crop_sha256=sha256(row["source_crop_path"]),
        fastocr_line_text=row["A_fastocr_line_text"],fastocr_word_text=row["B_fastocr_word_text"],trocr_text=row["C_trocr_text"],
        saved_documentDate=dict(A=row["kie_A_fastocr_control"],B=row["kie_B_fastocr_words"],C=row["kie_C_trocr_words"]),
        visual_note="Printed upright tháng followed immediately by italic printed single digit 8. Horizontal projections overlap, but a 1px 2D white gap remains. Not confirmed ink contact.",
        scope="Supplemental qualitative example, not part of original 30-case selection or prevalence estimates.")
    write(output/"supplemental_printed8_case.json",case)
    fragment="""## Bổ sung: số 8 in nghiêng sát chữ `tháng` tại `documentDate`

**File `4977+BVHTTDL-VP_2026-08-07`, trang vật lý 1, crop 3.** Đây là ví dụ bổ sung do agy trực tiếp kiểm tra ảnh, không thay thế hay cộng vào thống kê 30 mẫu ban đầu.

![Ảnh phóng đại và output từng mảnh](evidence/printed_thang8_4977.png)

Chữ `tháng` in đứng, số **8 là chữ in nghiêng**, nằm sát ngay sau chữ `g`, nhìn thành **`tháng8`**. Hai hình chiếu ngang chồng lấn, không có cột trắng dọc để bộ tách whitespace chia đôi; box mảnh là `[270, 0, 380, 55]`. Phóng lớn theo kiểm tra của agy vẫn còn **khe trắng 2D khoảng 1 pixel**, nên không gọi đây là hai nét mực chạm/nối hẳn. Không nhầm chữ in nghiêng với số viết tay.

| Nhánh | OCR nguyên dòng đã lưu | Output KIE `documentDate` |
|---|---|---|
| A FastOCR line | Hà Nội, ngày 07 tháng 1 năm 2026 | `07/01/2026` |
| B FastOCR cùng mảnh | Hà Nội, ngày 77 tháng8 năm 2026 | rỗng |
| C TrOCR cùng mảnh | Hả Nội ngày tháng năm 2020 | rỗng |

- **A:** nhầm tháng `8 → 1`, làm sai ngày trích xuất.
- **B:** giữ được `tháng8`, nhưng đọc cụm `ngày07` thành `ngày 77`; không đúng toàn dòng.
- **C:** mảnh `tháng8` chỉ còn `tháng`, mất số 8; cụm `ngày07` cũng mất số và năm bị đọc thành 2020.
- FastOCR **line và split đều Seq2Seq**, cùng weights baseline `vgg_seq2seq.pth`, không phải original VietOCR Transformer.

Đây là quan sát trên output đã lưu, không phải ablation chứng minh lỗi do dính chữ; lệch decoding TrOCR so với upstream vẫn chưa được đo tác động riêng. Không inference lại, sửa GT hay extraction. [Dữ liệu và provenance bổ sung](supplemental_printed8_case.json).
"""
    (output/"supplemental_printed8_case.md").write_text(fragment)
    report=output/"REPORT.md"
    original=report.read_text()
    title="## Bổ sung: số 8 in nghiêng sát chữ `tháng` tại `documentDate`"
    if title in original:
        start=original.index(title)
        end=original.index("## Next actions",start)
        original=original[:start]+fragment+"\n"+original[end:]
    else:
        original=original.replace("## Next actions, chưa thực thi",fragment+"\n## Next actions, chưa thực thi",1)
    report.write_text(original)
    cells=make_notebook(output)
    validation=verify_inputs(output)
    manifest=read(output/"manifest.json")
    manifest.update(notebook_cells=cells,notebook_executed=True,supplemental_visual_cases=1,
        supplemental_case_ids=[case["case_id"]],validation=validation)
    write(output/"manifest.json",manifest)
    print(f"Updated report + executed notebook ({cells} cells), supplemental image and provenance")


if __name__=="__main__":
    main()
