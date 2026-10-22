"""Common-GT 12-field and paired target-field analysis, never inference or GT routing."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ocr-collab")]
import benchmark as b
from scripts.report_all_tested_recognizers import (
    FIELD_LABELS, SCOPES, field_list, in_scope, read_scored_evaluation, write_csv,
)
from scripts.summarize_recognizer_ab import metrics_from_scored_cells
from scripts.check_cached_ocr_equivalence import sha256, dump

ART = ROOT / "ocr-collab/artifacts"
REFERENCES = {
    "fastocr": ("FastOCR", ART / "recognizer_ab_candidates_extended_20261021/fastocr_control"),
    "transformer": ("Transformer gốc", ART / "recognizer_ab_additional_20261015/vietocr_original_transformer"),
    "seq2seq": ("Seq2Seq gốc", ART / "recognizer_ab_additional_20261015/vietocr_original_seq2seq"),
    "vudang_onnx": ("Vudang ONNX", ART / "recognizer_ab_candidates_vudang_retest_20261021/vudang_onnx_retest"),
    "vudang_pytorch": ("Vudang PyTorch", ART / "recognizer_ab_candidates_vudang_retest_20261021/vudang_pytorch_retest"),
    "senocr": ("SenOCR", ART / "recognizer_ab_20261015/senocr"),
}
LABELS = {
    "vietocr_nhay_seq2seq": "nhay103 handwriting Seq2Seq",
    "vietocr_hocba_transformer": "SaitoHoujou học bạ Transformer",
    "vietocr_khoi_handwritten": "Khoi2k4, config upstream giả định",
}


def paired_counts(before, after):
    if set(before) != set(after):
        raise ValueError("Paired identities differ")
    both = sum(before[key] and after[key] for key in before)
    fixed = sum(not before[key] and after[key] for key in before)
    broken = sum(before[key] and not after[key] for key in before)
    wrong = sum(not before[key] and not after[key] for key in before)
    return dict(documents=len(before), baseline_correct=both + broken, candidate_correct=both + fixed,
                corrected_baseline_errors=fixed, broke_baseline_correct=broken, both_correct=both, both_wrong=wrong)


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    args = parser.parse_args()
    cohort = args.cohort.resolve()
    status = json.loads((cohort / "cohort_status.json").read_text())
    out = cohort / "report"
    out.mkdir(exist_ok=False)
    cases = {case.document_id: case for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    if len(cases) != 100:
        raise ValueError("Expected fixed 100 documents")
    gt_hashes = {doc: sha256(case.json_path) for doc, case in cases.items()}
    metadata = {doc: json.loads(case.json_path.read_text())["metadata"] for doc, case in cases.items()}
    expected_cache = json.loads((REFERENCES["fastocr"][1] / "run_fingerprint.json").read_text())["cache_manifest_sha256"]
    runs = dict(REFERENCES)
    for name, outcome in status["outcomes"].items():
        if outcome == "completed":
            runs[name] = LABELS[name], cohort / name
    all_fields, strata, summaries, pairs, changes = [], [], [], [], []
    scored = {}
    for name, (label, folder) in runs.items():
        manifest = json.loads((folder / "manifest.json").read_text())
        fingerprint = json.loads((folder / "run_fingerprint.json").read_text())
        if manifest.get("status") != "completed" or fingerprint["labels"] != gt_hashes or fingerprint["cache_manifest_sha256"] != expected_cache:
            raise ValueError(f"Incomplete/incomparable model: {name}")
        source = folder / "candidate_predictions.jsonl"
        records = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
        if len(records) != 100 or {r["document_id"] for r in records} != set(cases):
            raise ValueError(f"Missing or duplicate prediction IDs: {name}")
        records = [{**r, "ground_truth": cases[r["document_id"]].ground_truth,
                    "metadata": metadata[r["document_id"]]} for r in records]
        destination = out / "rescored" / name
        destination.mkdir(parents=True)
        b.write_evaluation(destination, records, dict(mode="rescore", full_inference=False,
            source_artifact=str(folder), source_predictions_sha256=sha256(source), protocol="hybrid_cached_recognizer"))
        cells, fields, documents, success = read_scored_evaluation(destination)
        scored[name] = dict(cells={(r["document_id"], r["field_name"]): r for r in cells}, fields=fields,
                            records={r["document_id"]: r for r in records})
        printed = {doc for doc, meta in metadata.items() if field_list(meta, "handwritten_fields") == []}
        summaries.append(dict(model_id=name, label=label, passed_documents=success["passed_documents"], documents=100,
            nonhandwritten_document_passed=sum(d["document_success_at_5"] for d in documents if d["document_id"] in printed),
            nonhandwritten_documents=len(printed), source_artifact=str(folder), predictions_sha256=sha256(source)))
        all_fields.extend(dict(model_id=name, label=label, **f) for f in fields)
        for field in ("code", "documentDate"):
            for scope in SCOPES:
                selected = [c for c in cells if c["field_name"] == field and in_scope(metadata[c["document_id"]], field, scope)]
                strata.append(dict(model_id=name, field=field, scope=scope, documents=len(selected),
                                   correct=sum(c["tp"] for c in selected), **metrics_from_scored_cells(selected)))
        print(f"RESCORED {name}: {success['passed_documents']}/100", flush=True)
    for name in LABELS:
        if name not in scored:
            continue
        new = scored[name]
        for baseline in ("fastocr", "transformer", "seq2seq", "vudang_onnx", "vudang_pytorch"):
            old = scored[baseline]
            for field in b.FIELDS:
                for scope in (("all", "field_handwritten", "field_not_handwritten") if field in ("code", "documentDate") else ("all",)):
                    ids = [doc for doc in cases if in_scope(metadata[doc], field, scope)]
                    before = {doc: bool(old["cells"][doc, field]["tp"]) for doc in ids}
                    after = {doc: bool(new["cells"][doc, field]["tp"]) for doc in ids}
                    pairs.append(dict(baseline_model_id=baseline, candidate_model_id=name, field=field, scope=scope,
                                      **paired_counts(before, after)))
                    if scope != "all":
                        for doc in ids:
                            if before[doc] == after[doc]:
                                continue
                            changes.append(dict(baseline_model_id=baseline, candidate_model_id=name, document_id=doc,
                                field=field, scope=scope, transition="fixed" if after[doc] else "broken",
                                gt=cases[doc].ground_truth[field], before=old["records"][doc]["prediction"].get(field),
                                after=new["records"][doc]["prediction"].get(field), visual_review="not_performed"))
    for filename, values in (("all_fields.csv", all_fields), ("all_model_scores.csv", summaries),
                             ("code_documentDate_strata.csv", strata), ("paired_field_changes.csv", pairs),
                             ("target_fixed_broken_examples.csv", changes)):
        write_csv(out / filename, values)
    table = [r["model_id"] for r in summaries]
    lines = ["# Ba checkpoint VietOCR mới: benchmark 100 tài liệu", "",
        "Giao thức hybrid recognizer-swap: cùng 6.619 parent crops trên 183 trang GT chọn, giữ baseline OCR trên trang khác, giữ nguyên extraction. Không phải full-PDF inference mới, không phải test transcription hay router đã triển khai.", "",
        f"Metric {b.METRIC_VERSION}, cùng 100 GT hiện tại. Reference được rescore mới, không rerun inference hoặc sửa artifact cũ. Tất cả kết quả, kể cả 0, được trình bày.", "",
        "## Hoàn tất và giới hạn checkpoint", ""]
    for name, label in LABELS.items():
        lines.append(f"- **{label}**: `{status['outcomes'].get(name, 'not_run')}`.")
        model_root = ROOT / "scratch/ocr-recognizers/models" / name
        m = json.loads((model_root / "download_manifest.json").read_text())
        lines.append(f"  Source `{m['repo_id']}@{m['revision']}`; SHA256 `{m['weight_sha256']}`. {m['provenance_limit']} License: {m['license']}.")
        if name == "vietocr_nhay_seq2seq":
            lines.append("  Native/upstream CPU qualification trên 3 crop kiểm tra input tensors và token IDs; không chứng minh parity toàn corpus. CUDA FP32/greedy và source/config có hash. Native initialization được chặn tải ImageNet, toàn bộ state được nạp strict.")
    lines.extend(["", "## Document Success và hai field viết tay", "",
        "Số đúng là field-cell sau KIE, không phải unique PDF hoặc CER/WER. Nhãn GT không phải classifier khả dụng khi inference.", "",
        "| Model | Document Success | Pass nhóm không có field viết tay | Code viết tay | Ngày viết tay | Code không gắn nhãn viết tay | Ngày không gắn nhãn viết tay |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for r in summaries:
        cells = []
        for scope in ("field_handwritten", "field_not_handwritten"):
            for field in ("code", "documentDate"):
                value = next(x for x in strata if x["model_id"] == r["model_id"] and x["scope"] == scope and x["field"] == field)
                cells.append(f"{value['correct']}/{value['documents']}")
        lines.append(f"| {r['label']} | {r['passed_documents']}/100 | {r['nonhandwritten_document_passed']}/{r['nonhandwritten_documents']} | " + " | ".join(cells) + " |")
    lines.extend(["", "## F1 đủ 12 field, toàn bộ 100 tài liệu", "", "| Field | " + " | ".join(r["label"] for r in summaries) + " |",
                  "| --- | " + " | ".join("---:" for _ in table) + " |"])
    for field in b.FIELDS:
        values = [pct(next(x["f1"] for x in scored[name]["fields"] if x["field_name"] == field)) for name in table]
        lines.append(f"| {FIELD_LABELS[field]} (`{field}`) | " + " | ".join(values) + " |")
    lines.extend(["", "F1/precision/recall/NEM/ACC và coverage chi tiết nằm trong all_fields.csv và từng rescored/*/summary.json. F1 không phải tỷ lệ số tài liệu đúng; prediction rỗng chỉ đóng góp FN, sai không rỗng đóng góp FP+FN. Không coi metadata không gắn nhãn viết tay là bằng chứng mọi pixel của PDF đều là chữ in.", "",
        "## Ca sửa đúng và làm hỏng so với Transformer gốc", "",
        "| Model | Field | Nhóm | Gốc đúng | Candidate đúng | Cứu lỗi | Làm hỏng ca đúng |", "| --- | --- | --- | ---: | ---: | ---: | ---: |"])
    for r in pairs:
        if r["baseline_model_id"] == "transformer" and r["field"] in ("code", "documentDate") and r["scope"] != "all":
            lines.append(f"| {LABELS[r['candidate_model_id']]} | {r['field']} | {r['scope']} | {r['baseline_correct']} | {r['candidate_correct']} | {r['corrected_baseline_errors']} | {r['broke_baseline_correct']} |")
    lines.extend(["", "Các transition là kết quả metric, chưa review ảnh để gán nguyên nhân. Không tuyên bố tăng có ý nghĩa thống kê hoặc triển khai routing/fallback. Khoi2k4 vẫn là phép thử config giả định dù strict tensor load thành công; không suy dataset/vocab semantics từ kích thước weights.", "",
        "Timing GPU/IPC chi tiết trong log.health.jsonl, runtime.json và cache/*/diagnostic.json của từng run. Không coi wall time recognizer là latency full-PDF hoặc đo GPU độc quyền.", ""])
    (out / "REPORT.md").write_text("\n".join(lines))
    snapshot = out / "source_snapshot"
    snapshot.mkdir()
    for path in [Path(__file__), ROOT / "scripts/run_public_vietocr_ab.py", ROOT / "scripts/qualify_public_vietocr.py",
                 ROOT / "scripts/prepare_public_vietocr.py", ROOT / "docs/ocr_pipeline_benchmark_metrics.md"]:
        shutil.copyfile(path, snapshot / str(path.relative_to(ROOT)).replace("/", "__"))
    for name in LABELS:
        for filename in ("download_manifest.json", "config.yml"):
            shutil.copyfile(ROOT / "scratch/ocr-recognizers/models" / name / filename, snapshot / f"{name}__{filename}")
    if any(sha256(case.json_path) != gt_hashes[doc] for doc, case in cases.items()):
        raise ValueError("GT changed during reporting")
    dump(out / "manifest.json", dict(status="completed", models_rescored=len(scored), candidate_outcomes=status["outcomes"],
        all_requested_completed=all(status["outcomes"].get(name) == "completed" for name in LABELS),
        documents_per_run=100, gt_sha256=gt_hashes, metric_version=b.METRIC_VERSION, no_routing_or_training=True,
        field_summary_rows=len(all_fields), paired_rows=len(pairs)))


if __name__ == "__main__":
    main()
