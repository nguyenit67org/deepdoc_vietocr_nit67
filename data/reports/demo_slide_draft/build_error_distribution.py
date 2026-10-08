"""Auditably group 229 full-inference field errors for the presentation.

The existing classifier is preliminary, not human ground truth. Reviewed
sample overrides and direct page-1 visual checks of the five HỎA TỐC stamps
are explicit here; no GT, prediction or benchmark artifact is modified.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ARTIFACT = REPO / "ocr-collab/artifacts/evidence_full_inference_all_v3"
OUT = HERE / "error_cause_full_inference_v3.csv"
sys.path.insert(0, str(REPO / "ocr-collab"))

from benchmark_review import build_cause_analysis_table  # noqa: E402


GROUPS = {
    "OCR/chính tả": "OCR/chính tả",
    "Dấu mộc": "Dấu mộc",
    "Vùng layout trộn nội dung": "Trích xuất",
    "Crop/bbox sai": "Trích xuất",
    "Extraction / Heuristics": "Trích xuất",
    "Nghi vấn GT": "Khác",
    "Chưa xác định": "Khác",
}

# An override changes only the reporting label, never the underlying error.
# Each key is (document_id, field_name). Keep both old and reviewed labels in CSV.
OVERRIDES = {
    ("8931+VPCP-PL_2026-08-29", "documentDate"):
        ("OCR/chính tả", "OCR source reads 19 instead of GT 29; extraction follows source."),
    ("8931+VPCP-PL_2026-08-29", "officeSender"):
        ("OCR/chính tả", "OCR source joins PHỦNH PHỦ; field follows OCR."),
    ("2125+TB-ĐLTKV_2020-12-21", "first_recipients"):
        ("Trích xuất", "OCR source includes number stub 1.772; output did not filter stub."),
    ("240+TB-PVIRe_2020-10-30", "officeSender"):
        ("Trích xuất", "Extraction selects 'Số:' as organization; evidence bbox confirms selected region."),
    ("03+BC.HĐQT_2020-02-20", "code"):
        ("Khác", "Suspected GT/policy separator mismatch: source '03/BC HĐQT'; review pending."),
    ("27+2026+VBHN-ND-BTC_2026-08-27", "code"):
        ("Khác", "Suspected GT accent mismatch: source 'NĐ', GT 'ND'; review pending."),
    ("8948+VPCP-CN_2026-09-01", "documentDate"):
        ("Khác", "Missing evidence; has_handwriting flag alone cannot establish OCR cause."),
    ("29+2026+QĐ-UBND_2026-05-15", "signer"):
        ("Khác", "Heuristic stamp label has no field-local stamp evidence; cause needs review."),
}

STAMP_PAGES = {
    "27+CT-TTg_2026-06-25",
    "29+CT-TTg_2026-07-16",
    "32+CĐ-UBND_2024-08-28",
    "5963+BCT-TTTN_2026-07-30",
    "8931+VPCP-PL_2026-08-29",
}


def main():
    errors = pd.read_csv(ARTIFACT / "field_errors.csv")
    errors = errors[errors.field_name != "receiverDate"]
    predictions = pd.read_json(ARTIFACT / "predictions.jsonl", lines=True)
    causes = build_cause_analysis_table(errors, predictions)
    records = {record["document_id"]: record for record in predictions.to_dict("records")}
    assert len(causes) == 229, f"The 35/100 full-inference bundle changed: {len(causes)} errors"
    output = []
    for row in causes.to_dict("records"):
        doc, field = row["document_id"], row["field_name"]
        source = row["primary_cause"]
        group = GROUPS[source]
        method = "heuristic"
        note = row["evidence_notes"]
        review_image = ""
        if (doc, field) in OVERRIDES:
            group, note = OVERRIDES[(doc, field)]
            method = "sample_evidence_review"
        if doc in STAMP_PAGES and field == "priority_level":
            image = ARTIFACT / "evidence" / doc / "page_1.png"
            assert image.is_file()
            review_image = str(image.relative_to(REPO))
            group = "Dấu mộc"
            method = "page_1_visual_review"
            note = "HỎA TỐC stamp visible on page 1; priority extraction has no evidence."
        output.append({
            "document_id": doc,
            "field_name": field,
            "error_bucket": row["error_bucket"],
            "gt_raw": "" if pd.isna(row["gt_raw"]) else row["gt_raw"],
            "pred_raw": "" if pd.isna(row["pred_raw"]) else row["pred_raw"],
            "heuristic_cause": source,
            "report_group": group,
            "assignment_method": method,
            "evidence_notes": note,
            "trace_path": records[doc]["trace_path"],
            "review_image": review_image,
        })
    output.sort(key=lambda x: (x["document_id"], x["field_name"]))
    assert len({(r["document_id"], r["field_name"]) for r in output}) == 229
    with OUT.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print("Saved", OUT)
    print(Counter(row["report_group"] for row in output))


if __name__ == "__main__":
    main()
