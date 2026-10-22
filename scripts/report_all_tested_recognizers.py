"""Rescore historical predictions consistently; report handwriting targets and routing evidence.

Never loads OCR models, changes predictions/GT, or implements GT-dependent routing.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ocr-collab/artifacts"
FIRST = ARTIFACTS / "recognizer_ab_candidates_20261021"
SECOND = ARTIFACTS / "recognizer_ab_candidates_extended_20261021"
RETEST = ARTIFACTS / "recognizer_ab_candidates_vudang_retest_20261021"
BASE_CONFIG = ARTIFACTS / "recognizer_ab_candidates_vietdoc_base_20261021"
sys.path[:0] = [str(ROOT), str(ROOT / "ocr-collab")]
import benchmark as b
from scripts.summarize_recognizer_ab import metrics_from_scored_cells
from scripts.build_recognizer_final_report import PROCESSING

LABELS = {
    "fastocr_control": "FastOCR PyTorch control",
    "ocrdoc": "OcrDoc Run 6 ONNX",
    "vietocr_handwriting": "Vudang handwriting ONNX",
    "htr_convtext": "HTR-ConvText HANDS-VNOnDB",
    "senocr": "SenOCR-Vi FP32",
    "akaocr": "AkaOCR 2.1.6 bundled reference",
    "vietocr_original_seq2seq": "Original VietOCR Seq2Seq",
    "vietocr_original_transformer": "Original VietOCR Transformer",
    "vietocr_dunghugging": "DungHugging handwriting",
    "trocr_words": "Thaito98 TrOCR + whitespace word segmentation",
    "fastocr_words": "FastOCR + matched whitespace word segmentation control",
    "nom_tesseract_raw": "Nôm Tesseract raw",
    "nom_tesseract_spell": "Nôm Tesseract + Vietnamese spell correction",
    "trocr_duyle": "Duyle TrOCR",
    "vnhtr_vgg": "VNHTR VietOCR/VGG fine-tuned + Rethinking Head",
    "vnhtr_trocr": "VNHTR TrOCR fine-tuned + Rethinking Head",
    "vnhtr_vgg_base": "VNHTR VietOCR/VGG fine-tuned, no Rethinking Head",
    "vnhtr_trocr_base": "VNHTR TrOCR fine-tuned, no Rethinking Head",
    "vietdoc_vudang_pth": "VietDoc-downloaded Vudang handwriting PyTorch",
    "easyocr_latin_pretrained": "EasyOCR Latin Gen2 pretrained, NOT fine-tuned",
    "vudang_pytorch_retest": "Vudang PyTorch FP32, matched-input retest",
    "vudang_onnx_retest": "Vudang ONNX FP16, matched-input retest",
    "vietdoc_base_pth": "Original VietOCR Transformer weights + VietDoc width/decode config",
    "fastocr_selected": "FastOCR selected-pages-only replay",
    "nom_raw_selected": "Nôm raw selected-pages-only replay",
    "pytesseract_psm6": "Pytesseract vie, PSM6, selected-pages-only",
    "pytesseract_psm7": "Pytesseract vie, PSM7, selected-pages-only",
    "pytesseract_psm13": "Pytesseract vie, PSM13, selected-pages-only",
}
SCOPES = ("all", "field_handwritten", "field_not_handwritten", "handwritten_and_stamp", "handwritten_without_stamp")
FIELD_LABELS = {
    "type": "Loại văn bản", "title": "Trích yếu/tiêu đề", "code": "Số, ký hiệu văn bản",
    "documentDate": "Ngày ban hành", "officeSender": "Cơ quan ban hành", "recipients": "Nơi nhận cuối văn bản",
    "signer": "Họ tên người ký", "priority_level": "Độ khẩn", "security_level": "Độ mật",
    "first_recipients": "Kính gửi đầu văn bản", "signer_title": "Chức danh/thẩm quyền người ký", "province": "Địa danh",
}


def read(path):
    return json.loads(path.read_text())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def csv_bool(value):
    if value in ("True", "true", "1"):
        return True
    if value in ("False", "false", "0"):
        return False
    raise ValueError(f"Unexpected benchmark CSV boolean: {value!r}")


def read_scored_evaluation(folder):
    """Aggregate official scored cells, without recomputing normalization/distances."""
    summary = read(folder / "summary.json")
    cells = []
    with (folder / "field_errors.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            cell = {key: row[key] for key in ("document_id", "field_name", "error_bucket")}
            cell.update({key: int(row[key]) for key in ("tp", "fp", "fn", "tn")})
            cell.update({key: csv_bool(row[key]) for key in ("gt_present", "exact_match")})
            cell["vai_acc"] = float(row["vai_acc"]) if row["vai_acc"] else None
            cells.append(cell)
    with (folder / "document_success.csv").open(encoding="utf-8-sig") as handle:
        documents = [dict(document_id=row["document_id"], document_success_at_5=csv_bool(row["document_success_at_5"])) for row in csv.DictReader(handle)]
    return cells, summary["fields"], documents, summary["document_success_at_5"]


def field_list(metadata, name):
    value = metadata.get(name)
    value = value.get("value") if isinstance(value, dict) else value
    return value if isinstance(value, list) else None


def in_scope(metadata, field, scope):
    if scope == "all":
        return True
    handwritten, stamped = field_list(metadata, "handwritten_fields"), field_list(metadata, "stamp_affected_fields")
    if handwritten is None:
        return False
    if scope == "field_handwritten":
        return field in handwritten
    if scope == "field_not_handwritten":
        return field not in handwritten
    if stamped is None:
        return False
    return (field in handwritten and field in stamped) if scope == "handwritten_and_stamp" else (field in handwritten and field not in stamped)


def discover():
    runs, exclusions = [], []
    canonical_control = FIRST / "fastocr_control"
    for config_path in sorted(ARTIFACTS.rglob("recognizer_config.json")):
        folder = config_path.parent
        manifest = folder / "manifest.json"
        if not manifest.exists():
            continue
        saved = read(manifest)
        if saved.get("status") != "completed" or len(saved.get("documents", [])) != 100:
            exclusions.append(dict(artifact=str(folder), reason="not a completed 100-document run"))
            continue
        if folder.name == "fastocr_control" and folder != canonical_control:
            exclusions.append(dict(artifact=str(folder), reason="duplicate exact FastOCR integration control; retain canonical current control"))
            continue
        config = read(config_path)
        predictions = folder / "candidate_predictions.jsonl"
        if not predictions.exists():
            predictions = folder / "predictions.jsonl"
        if not predictions.exists():
            raise ValueError(f"Completed run lacks predictions: {folder}")
        protocol = "selected_pages_only" if folder.parent.name == "pytesseract_selected_pages_20261020" else "hybrid_cached_recognizer"
        runs.append(dict(id=str(folder.relative_to(ARTIFACTS)).replace("/", "__"), folder=folder,
            name=folder.name, label=LABELS.get(folder.name, folder.name), config=config,
            protocol=protocol, predictions=predictions, is_trocr="trocr" in folder.name.lower()))
    vai = ARTIFACTS / "vai_ocr_fullpdf_all100_20260927_212945"
    if (vai / "predictions.jsonl").exists():
        runs.append(dict(id=vai.name, folder=vai, name="viettel_ai_fullpdf_api", label="Viettel AI OCR full-PDF API, external reference",
                         config=None, protocol="external_full_pdf_api", predictions=vai / "predictions.jsonl", is_trocr=False))
    return runs, exclusions


def number(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def measured_timing(run):
    files = sorted((run["folder"] / "cache").glob("*/diagnostic.json"))
    summary_file = run["folder"] / "summary.json"
    summary = read(summary_file) if summary_file.exists() else {}
    pages = summary.get("selected_pages")
    if len(files) != 100 or not isinstance(pages, int) or pages < 1:
        return dict(adapter_seconds_per_selected_page=None, timing_note="No comparable 100-document cached-adapter timing; consult original protocol-specific timing artifacts")
    seconds = sum(read(path)["recognition_seconds"] for path in files)
    note = "sum recorded document adapter seconds / selected pages; includes IPC where configured, excludes model load and crop generation; not exclusive kernel or full PDF latency"
    config = run["config"] or {}
    if config.get("backend") == "nom_tesseract" and config.get("post_correct"):
        raw_files = sorted((run["folder"].parent / "nom_tesseract_raw/cache").glob("*/diagnostic.json"))
        if len(raw_files) != 100:
            return dict(adapter_seconds_per_selected_page=None, timing_note="Correction-only timing cannot stand for OCR+correction without the matching raw stage")
        seconds += sum(read(path)["recognition_seconds"] for path in raw_files)
        note = "sum separately recorded raw Tesseract and cached-text correction stages / selected pages; not a jointly measured online pipeline; model loads excluded"
    if config.get("backend") == "word_to_line":
        note += "; warm cached word segmentation, offline segmentation preparation cost excluded and retained in original cohort report"
    return dict(adapter_seconds_per_selected_page=seconds / pages, timing_note=note)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for cohort in (FIRST, SECOND, RETEST, BASE_CONFIG):
        status = read(cohort / "cohort_status.json")
        if status.get("status") != "finished" or any(value != "completed" for value in status["outcomes"].values()):
            raise ValueError("Finish all approved new runs before final all-model report")
    cases = {case.document_id: case for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    if len(cases) != 100:
        raise ValueError("Expected the fixed 100-document benchmark")
    labels = {doc: sha256(case.json_path) for doc, case in cases.items()}
    metadata = {doc: read(case.json_path).get("metadata", {}) for doc, case in cases.items()}
    printed_docs = {doc for doc, value in metadata.items() if field_list(value, "handwritten_fields") == []}
    runs, exclusions = discover()
    canonical_cache = read(FIRST / "fastocr_control/run_fingerprint.json")["cache_manifest_sha256"]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "manifest.json", dict(status="in_progress", mode="read_only_prediction_rescore", metric_version=b.METRIC_VERSION))
    dump(output / "gt_file_hashes.json", labels)
    all_fields, targets, summaries, scored = [], [], [], {}
    inventory = []
    for run in runs:
        if run["protocol"] == "hybrid_cached_recognizer":
            fingerprint = read(run["folder"] / "run_fingerprint.json")
            if fingerprint.get("cache_manifest_sha256") != canonical_cache:
                raise ValueError(f"Hybrid model does not use the identical parent-crop cache: {run['id']}")
        records = [json.loads(line) for line in run["predictions"].read_text().splitlines() if line.strip()]
        if len(records) != 100 or {record["document_id"] for record in records} != set(cases):
            raise ValueError(f"Wrong/duplicate document coverage: {run['folder']}")
        records = [{**record, "ground_truth": cases[record["document_id"]].ground_truth,
                    "metadata": metadata[record["document_id"]],
                    "document_format": cases[record["document_id"]].document_format,
                    "has_handwriting": cases[record["document_id"]].has_handwriting} for record in records]
        folder = output / "rescored" / run["id"]
        folder.mkdir(parents=True)
        b.write_evaluation(folder, records, dict(mode="rescore", full_inference=False,
                           source_artifact=str(run["folder"]), source_predictions_sha256=sha256(run["predictions"]), protocol=run["protocol"]))
        cells, fields, docs, success = read_scored_evaluation(folder)
        row = dict(model_id=run["id"], label=run["label"], protocol=run["protocol"],
            passed_documents=success["passed_documents"], documents=100, document_success_at_5=success["rate"],
            printed_labeled_documents=len(printed_docs), printed_labeled_passed=sum(d["document_success_at_5"] for d in docs if d["document_id"] in printed_docs),
            artifact=str(run["folder"]), rescored_artifact=str(folder), is_trocr=run["is_trocr"])
        row.update(measured_timing(run))
        row["included_in_primary_report"] = row["passed_documents"] > 0 or run["is_trocr"]
        summaries.append(row)
        all_fields.extend(dict(model_id=run["id"], **field) for field in fields)
        scored[run["id"]] = dict(run=run, records={r["document_id"]: r for r in records}, cells={(c["document_id"], c["field_name"]): c for c in cells})
        for field in ("code", "documentDate"):
            for scope in SCOPES:
                selected = [cell for cell in cells if cell["field_name"] == field and in_scope(metadata[cell["document_id"]], field, scope)]
                metrics = metrics_from_scored_cells(selected)
                targets.append(dict(model_id=run["id"], field=field, scope=scope, documents=len(selected),
                    correct=sum(cell["tp"] for cell in selected), **metrics,
                    coverage_note="GT field handwriting/stamp annotations; not a deployed classifier or OCR transcription accuracy"))
        inventory.append(dict(model_id=run["id"], name=run["name"], label=run["label"], protocol=run["protocol"],
                              source_artifact=str(run["folder"]), config=run["config"], source_predictions_sha256=sha256(run["predictions"])))
        print(f"RESCORED {run['id']}: {row['passed_documents']}/100", flush=True)
    canonical = str((FIRST / "fastocr_control").relative_to(ARTIFACTS)).replace("/", "__")
    local = [row for row in summaries if row["protocol"] == "hybrid_cached_recognizer"]
    best = max(row["passed_documents"] for row in local)
    best_ids = [row["model_id"] for row in local if row["passed_documents"] == best]
    focused_pairs = {}
    for before_name, after_name in (("vnhtr_vgg_base", "vnhtr_vgg"), ("vnhtr_trocr_base", "vnhtr_trocr"),
                                    ("vudang_pytorch_retest", "vudang_onnx_retest"),
                                    ("vietocr_original_transformer", "vietdoc_base_pth")):
        before_id = next(model_id for model_id, value in scored.items() if value["run"]["name"] == before_name)
        after_id = next(model_id for model_id, value in scored.items() if value["run"]["name"] == after_name)
        focused_pairs[before_id] = after_id
    global_baselines = [canonical, *best_ids]
    baselines = list(dict.fromkeys([*global_baselines, *focused_pairs]))
    paired, transitions = [], []
    for baseline in baselines:
        old = scored[baseline]
        for model_id, data in scored.items():
            if baseline in focused_pairs and baseline not in global_baselines and model_id != focused_pairs[baseline]:
                continue
            if data["run"]["protocol"] != "hybrid_cached_recognizer" or model_id == baseline:
                continue
            for field in ("code", "documentDate"):
                for scope in SCOPES:
                    ids = [doc for doc in cases if in_scope(metadata[doc], field, scope)]
                    before = {doc: old["cells"][doc, field]["tp"] == 1 for doc in ids}
                    after = {doc: data["cells"][doc, field]["tp"] == 1 for doc in ids}
                    paired.append(dict(baseline_model_id=baseline, candidate_model_id=model_id, field=field, scope=scope,
                        documents=len(ids), baseline_correct=sum(before.values()), candidate_correct=sum(after.values()),
                        corrected_baseline_errors=sum(not before[doc] and after[doc] for doc in ids),
                        broke_baseline_correct=sum(before[doc] and not after[doc] for doc in ids),
                        both_correct=sum(before[doc] and after[doc] for doc in ids),
                        both_wrong=sum(not before[doc] and not after[doc] for doc in ids)))
                    if scope == "field_handwritten":
                        for doc in ids:
                            if before[doc] == after[doc]:
                                continue
                            transitions.append(dict(baseline_model_id=baseline, candidate_model_id=model_id, document_id=doc,
                                field=field, transition="corrected" if after[doc] else "regressed",
                                baseline_prediction=old["records"][doc]["prediction"].get(field, ""),
                                candidate_prediction=data["records"][doc]["prediction"].get(field, ""),
                                ground_truth=cases[doc].ground_truth[field], visual_review="pending; do not infer visual error cause from these strings"))
    for doc, case in cases.items():
        if sha256(case.json_path) != labels[doc]:
            raise ValueError("GT changed during report generation")
    strategy_candidates = {}
    for model_id, data in scored.items():
        if data["run"]["protocol"] != "hybrid_cached_recognizer" or model_id == canonical:
            continue
        hand = [r for r in paired if r["baseline_model_id"] == canonical and r["candidate_model_id"] == model_id and r["scope"] == "field_handwritten"]
        printed = [r for r in paired if r["baseline_model_id"] == canonical and r["candidate_model_id"] == model_id and r["scope"] == "field_not_handwritten"]
        fixed = sum(r["corrected_baseline_errors"] for r in hand)
        broken = sum(r["broke_baseline_correct"] for r in hand)
        candidate = dict(model_id=model_id, label=next(r["label"] for r in summaries if r["model_id"] == model_id),
            handwritten_field_cells_fixed=fixed, handwritten_field_cells_broken=broken, handwritten_field_cell_net=fixed-broken,
            nonhandwritten_field_cells_fixed=sum(r["corrected_baseline_errors"] for r in printed),
            nonhandwritten_field_cells_broken=sum(r["broke_baseline_correct"] for r in printed),
            interpretation="code+documentDate field-cell counts, NOT unique documents or a deployed routing score")
        key = json.dumps(data["run"]["config"], sort_keys=True)
        if key not in strategy_candidates or data["run"]["name"].endswith("_retest"):
            strategy_candidates[key] = candidate
    strategy_ranked = sorted(strategy_candidates.values(), key=lambda r: (-r["handwritten_field_cell_net"], r["handwritten_field_cells_broken"]))
    write_csv(output / "all_model_scores.csv", summaries)
    write_csv(output / "all_fields.csv", all_fields)
    write_csv(output / "code_documentDate_strata.csv", targets)
    write_csv(output / "paired_target_field_changes.csv", paired)
    write_csv(output / "handwritten_target_transitions.csv", transitions)
    write_csv(output / "strategy_screening.csv", strategy_ranked)
    dump(output / "source_inventory.json", dict(runs=inventory, exclusions=exclusions,
         scope_note="Named recognizer configurations with completed 100-document artifacts, plus Viettel full-PDF API reference. Historical extraction-only versions of the same FastOCR model and opaque third-party pipelines are not treated as new recognizer models."))
    lines = ["# Báo cáo các model OCR đã test", "",
        "## Mục tiêu và điều kiện so sánh", "",
        "Ưu tiên cải thiện số/ký hiệu (`code`) và ngày ban hành (`documentDate`) có chữ viết tay, xác định bằng chứng cho fallback/routing/classifier/confidence/fine-tune; đồng thời tìm model tốt hơn cho chữ in và Document Success@5%.", "",
        f"Toàn bộ prediction đã lưu được **rescore mới** trên cùng 100 tài liệu, GT hiện tại và metric {b.METRIC_VERSION}. Không sửa prediction, GT, extraction hoặc artifacts cũ. Đây không phải chạy inference lại hay cải thiện model.", "",
        "Bảng chính gồm các cấu hình có Document Success@5% > 0 và tất cả TrOCR có điểm 0. Bốn case VNHTR được trình bày đầy đủ ở mục riêng, kể cả VietOCR đạt 0. Không gộp các giao thức khác nhau để xếp hạng.", ""]
    for protocol, title in (("hybrid_cached_recognizer", "Recognizer trên crop cache, hybrid KIE"),
                            ("selected_pages_only", "Chỉ selected pages, không giữ OCR các trang còn lại"),
                            ("external_full_pdf_api", "API full-PDF, tham chiếu khác giao thức")):
        lines.extend([f"## {title}", "", "| Model/cấu hình | Document Success@5% | Pass nhóm GT không có field viết tay | Adapter s/trang chọn |", "| --- | ---: | ---: | ---: |"])
        for row in sorted((r for r in summaries if r["protocol"] == protocol and r["included_in_primary_report"]), key=lambda r: -r["passed_documents"]):
            elapsed = "N/A" if row['adapter_seconds_per_selected_page'] is None else f"{row['adapter_seconds_per_selected_page']:.3f}"
            lines.append(f"| {row['label']} | {row['passed_documents']}/100 | {row['printed_labeled_passed']}/{row['printed_labeled_documents']} | {elapsed} |")
        lines.append("")
    lines.extend(["## Bốn case VNHTR", "", "| Checkpoint fine-tuned của tác giả | Document Success@5% |", "| --- | ---: |"])
    for row in summaries:
        if "__vnhtr_" in row["model_id"]:
            lines.append(f"| {row['label']} | {row['passed_documents']}/100 |")
    head_output_path = FIRST / "vnhtr_head_comparison/comparison.json"
    if head_output_path.exists():
        head_outputs = read(head_output_path)
        dump(output / "vnhtr_head_output_comparison.json", head_outputs)
        lines.append("")
        for family in head_outputs["families"]:
            lines.append(f"- `{family['family']}` không head/có head khác **{family['changed_raw_crop_texts']}/6619 crop text** và **{family['changed_api_values']} giá trị API**. Tổng số field đúng bằng nhau không có nghĩa các đầu ra giống nhau.")
    lines.extend(["", "Không head là checkpoint đã train/fine-tune của tác giả VNHTR, không phải weights upstream nguyên gốc. Bốn graph/decoder khác nhau đã kiểm tra; nguồn tokenizer/preprocessing tương ứng khớp trong từng họ. So sánh các checkpoint này không phải phép bật/tắt head trên cùng weights. Dataset fine-tune cụ thể chưa có provenance đầy đủ công khai.", "",
        "## Hai field viết tay ưu tiên", "", "Mỗi ô: **số field đúng / số field được gắn nhãn viết tay (F1)**. Đây là KIE trên field có metadata GT, không phải CER/WER riêng của crop viết tay.", "",
        "| Model/cấu hình hybrid | Số, ký hiệu (`code`) viết tay | Ngày ban hành (`documentDate`) viết tay |", "| --- | ---: | ---: |"])
    for row in sorted(local, key=lambda r: -r["passed_documents"]):
        cells = {t["field"]: t for t in targets if t["model_id"] == row["model_id"] and t["scope"] == "field_handwritten"}
        values = [f"{cells[field]['correct']}/{cells[field]['documents']} ({number(cells[field]['f1'])})" for field in ("code", "documentDate")]
        lines.append(f"| {row['label']} | {values[0]} | {values[1]} |")
    lines.extend(["", "## Ưu tiên thí nghiệm tiếp theo từ bằng chứng hiện có", "",
        "Bảng screening cộng các **field-cell** của số/ký hiệu và ngày ban hành, KHÔNG phải số PDF duy nhất hoặc mức tăng Document Success của một router. Chỉ so với FastOCR cùng crop cache. Cấu hình trùng nhau được ưu tiên lượt retest; đây là lựa chọn sau khi xem benchmark, chưa phải kết quả holdout độc lập.", "",
        "| Cấu hình có net gain viết tay dương | Lỗi baseline được cứu | Ca baseline đúng bị làm hỏng | Net field-cell viết tay | Ca không gắn nhãn viết tay bị làm hỏng |", "| --- | ---: | ---: | ---: | ---: |"])
    for candidate in [r for r in strategy_ranked if r["handwritten_field_cell_net"] > 0][:5]:
        lines.append(f"| {candidate['label']} | {candidate['handwritten_field_cells_fixed']} | {candidate['handwritten_field_cells_broken']} | +{candidate['handwritten_field_cell_net']} | {candidate['nonhandwritten_field_cells_broken']} |")
    lines.extend(["", "Ưu tiên bước tiếp theo là kiểm tra ROI/crop đích và giữ nguyên context/anchor FastOCR cho các cấu hình cứu lỗi nhưng có nguy cơ làm hỏng chữ in. Sau đó mới thiết kế policy chọn model, classifier viết tay hoặc gate confidence trên validation/holdout riêng; không dùng metadata GT như router triển khai. Nếu lỗi còn nằm ở glyph/domain sau khi xác minh crop và preprocessing, mới cân nhắc fine-tune với transcription gold độc lập. Model có Document Success cao hơn là ứng viên toàn cục riêng, không mặc nhiên là specialist tốt nhất cho hai field.", ""])
    lines.extend(["", "## Bằng chứng và giới hạn chiến lược", "",
        f"- Mốc tốt nhất trong nhóm hybrid local trên GT hiện tại: **{best}/100**. So sánh riêng số pass trong nhóm không có field viết tay; nhãn này chỉ nói về 12 field được chấm, không chứng minh toàn bộ trang/PDF không có ghi chú viết tay.",
        "- `paired_target_field_changes.csv` đếm số lỗi sửa được và số ca đúng bị làm hỏng, riêng viết tay/chữ không gắn nhãn viết tay/dấu đè; so với FastOCR, các model đồng hạng tốt nhất local, từng cặp VNHTR không head/có head, Vudang PyTorch/ONNX retest, và Transformer gốc/config VietDoc. Tổng số đúng bằng nhau vẫn có thể là các tài liệu đúng khác nhau; không chỉ dùng tổng F1 để quyết định routing.",
        "- `handwritten_target_transitions.csv` chứa các chuyển đúng/sai ở hai field ưu tiên để review ảnh/crop tiếp theo. Chưa suy nguyên nhân lỗi từ chuỗi OCR hoặc tên file.",
        "- Chưa triển khai routing, classifier, chọn đáp án bằng GT, threshold confidence, hoặc fine-tune. Metadata viết tay trong báo cáo là nhãn đánh giá GT, không phải classifier khả dụng khi inference.",
        "- Chỉ số hai field hiện vẫn đến từ KIE sau khi thay OCR trên toàn bộ crop được chọn. Lỗi nhận dạng anchor/header/context có thể làm extraction chọn sai hoặc bỏ sót field; đây CHƯA phải phép thử giữ nguyên FastOCR rồi chỉ thay nhận dạng crop đích của `code`/`documentDate`. Điểm thấp/Document Success 0 chưa đủ tự nó loại model khỏi mọi chiến lược specialist fallback; thử ROI/crop đích với context cố định là bước tiếp theo cần thiết kế riêng.",
        "- Confidence giữa các backend không đồng thang; nhiều model không có confidence native. Muốn gate confidence cần xác định score theo field, calibration và validation/holdout độc lập; không tối ưu ngưỡng trên cùng benchmark rồi coi đó là kết quả tổng quát.",
        "- Nếu model cứu được lỗi của baseline nhưng làm hỏng chữ in, cân nhắc nhánh chỉ nhận dạng vùng/field phù hợp. Cần kiểm tra bbox, loại crop và lỗi extraction trước khi quy kết model nhận dạng kém hoặc yêu cầu fine-tune.",
        "- Fine-tune cần dữ liệu crop + transcription đúng và split độc lập; field GT của 100 tài liệu không tự động là transcription của từng crop. Không train trên benchmark này rồi dùng chính nó để tuyên bố cải thiện.",
        "- `all_fields.csv` giữ F1/precision/recall/NEM, VAI-style ACC tham chiếu, coverage, hallucination và targets cho đủ 12 field. `receiverDate` ngoài scope; không lấy Document Success thay chất lượng từng field.",
        "- Thời gian, batch, precision, preprocessing, decoder và hashes nằm trong source artifact và config ở `source_inventory.json`. Không so thời gian rescore với inference; GPU/host exclusivity không được xác lập.",
        "- Cột thời gian lấy lại adapter wall time đã đo, không bao gồm model load, đọc PDF/detection hay crop generation. Nôm + spell dùng tổng hai stage đã đo riêng, không phải latency online đo chung. Word-to-line dùng warm segmentation cache, chi phí chuẩn bị segmentation offline nằm ở report gốc. API/replay/selected-only không có timing tương đương thì ghi N/A; không phát minh số 0 hoặc xếp hạng tốc độ lẫn giao thức.",
        "- VietDoc downloader cung cấp external Vudang checkpoint và upstream VietOCR Transformer; base Transformer trùng weights đã test. Bản Vudang PyTorch ở đây dùng pinned upstream adapter, không phải native VietDoc decoder; EasyOCR Latin Gen2 là pretrained, không phải package fine-tuned `viet_handwriting` chưa tìm thấy.",
        "- VietHandOCR chưa tìm thấy checkpoint fine-tuned riêng công khai; không tự train hoặc thay bằng model gốc rồi gọi là kết quả dự án.",
        "- Các model 0 không phải TrOCR vẫn có trong `all_model_scores.csv` và inventory, không bị xóa khỏi lịch sử. Các pipeline bên ngoài không xác định rõ model và lịch sử sửa extraction của cùng model không được gán thành model recognizer mới.", ""])
    parity_path = BASE_CONFIG / "checkpoint_config_parity/parity.json"
    if not parity_path.exists():
        parity_path = RETEST / "runtime_parity/parity.json"
    if not parity_path.exists():
        parity_path = FIRST / "vietdoc_checkpoint_parity/parity.json"
    if parity_path.exists():
        parity = read(parity_path)
        dump(output / "vietdoc_checkpoint_parity.json", parity)
        hand = parity["handwriting"]
        lines.extend(["## VietDoc: checkpoint có khác bản gốc không?", "",
            "- Cả base và handwriting `.pth` tải bằng script VietDoc đều trùng SHA-256 với checkpoint nguồn tương ứng; không phải weights fine-tuned mới do VietDoc phân phối.",
            f"- So sánh Vudang PyTorch/ONNX trong lượt retest matched-input: **{hand['changed_raw_crop_texts']}/6619 crop text khác**, **{hand['changed_api_values']} giá trị API khác** trên **{hand['documents_with_changed_api_values']} tài liệu**. Trong đó `code` khác ở {hand['changed_values_by_field'].get('code', 0)} tài liệu, `documentDate` khác ở {hand['changed_values_by_field'].get('documentDate', 0)} tài liệu. Số khác biệt không đồng nghĩa số cải thiện; xem paired field metrics trên GT hiện tại.",
            "- Không quy chênh lệch trên thành thay đổi weights: resize/interpolation/width policy, FP16 ONNX versus FP32 PyTorch, decoding và batching khác nhau. Chưa chứng minh numerical parity giữa export ONNX và `.pth`; đây không phải native VietDoc decoder.",
            f"- Base trùng weights upstream Transformer nhưng config VietDoc khác width/decode limit. Trạng thái kiểm tra config riêng: **{parity['base']['separate_vietdoc_config_inference']}**; {parity['base'].get('changed_raw_crop_texts', 'N/A')} crop text khác và {parity['base'].get('changed_api_values', 'N/A')} giá trị API khác. Không kết luận đầu ra giống chỉ từ weights giống.",
            f"- Bảng diff từng crop/field: `{parity_path.parent}`.", ""])
        for runtime, repeated in parity.get("repeat_consistency", {}).items():
            if repeated.get("status") == "independent_retest_compared":
                lines.append(f"- Tính lặp lại `{runtime}`: retest trùng **{repeated['exact_crop_texts']}/{repeated['compared_crops']} crop text** và **{repeated['exact_document_predictions']}/{repeated['compared_documents']} prediction tài liệu** với lượt trước của chính runtime đó.")
        lines.append("")
    lines.extend(["## Phụ lục: cấu hình, checkpoint và đủ 12 field", "",
        "Mỗi field hiển thị F1 (precision, recall) / NEM / VAI-style ACC tham chiếu. Target PoC tương ứng 85% (85%, 85%) / 75% / không áp dụng; stretch 90% (90%, 90%) / 75% / không áp dụng. Hallucination <=1%, riêng địa danh <=2%; thiếu mẫu số hoặc lớp enum không được coi là đạt đầy đủ. Trạng thái và coverage chính thức nằm trong CSV rescore. ACC không phải cam kết nghiệm thu và chưa xác minh điều kiện đầu vào datasheet.", ""])
    for row in summaries:
        if not row["included_in_primary_report"] and "__vnhtr_" not in row["model_id"]:
            continue
        entry = scored[row["model_id"]]["run"]
        config = entry["config"]
        lines.extend([f"### {row['label']}", "", f"Giao thức: `{row['protocol']}`. Source: `{row['artifact']}`. Rescore: `{row['rescored_artifact']}`.", ""])
        if config is not None:
            lines.extend(["Config chính xác đã dùng:", "```json", json.dumps(config, ensure_ascii=False, indent=2), "```", ""])
            backend = config.get("backend", "fastocr")
            if backend == "vietocr_original":
                description = f"Pinned upstream VietOCR PyTorch CUDA FP32; resize theo config.yml, identical-width buckets, upstream greedy decoder, max_seq_length={config.get('max_seq_length', 128)}. Không phải native VietDoc app decoder."
            else:
                description = PROCESSING.get(backend, {
                    "vnhtr_jit": "PyTorch JIT FP32; VGG height32/pad-or-right-crop768, char vocabulary and greedy limit128; TrOCR native384x384/BartPho and greedy limit35. Four checkpoint prefixes vt/vta/tr/tra, not a runtime-only head toggle.",
                    "trocr_duyle": "PyTorch FP32 ViT-large + PhoBERT, RGB384x384/normalization from pinned processor; saved generation beam4/max_length64/length_penalty2/no_repeat_ngram3. No segmentation.",
                    "easyocr_latin": "EasyOCR1.7.2 official Latin Gen2, detector/download disabled, native grayscale/CTC greedy recognition, one complete cached crop per call, contrast thresholds0.1/0.5, quantize=False. Not fine-tuned VietDoc weights.",
                    "nom_tesseract": "Pinned Nôm wrapper + Tesseract5.5.1 tessdata_best vie, CPU PSM6/OEM1. If post_correct=true, identical raw texts feed pinned nrl-ai/vn-spell-correction-base CUDA FP32; no OCR rerun or custom confidence gate.",
                    "pytesseract_direct": "Direct pytesseract/Tesseract5.5.1 vie, OEM1, PSM specified in config, RGB plus10px white border; four CPU processes with OMP_THREAD_LIMIT1, pixels/config memoization. Selected pages only; no spell correction.",
                    "saved_blocks_replay": "Extraction replay of saved selected-page blocks only; no new OCR inference or new recognizer weights in this row.",
                }.get(backend, "Chi tiết preprocessing/decoder trong source artifact và runtime.json; không suy thông số chưa ghi nhận."))
            lines.extend([description, ""])
            model_dir = config.get("model_dir")
            model_manifest = ROOT / model_dir / "download_manifest.json" if model_dir else None
            runtime_file = entry["folder"] / "runtime.json"
            runtime = read(runtime_file) if runtime_file.exists() else {}
            provenance = read(model_manifest) if model_manifest and model_manifest.exists() else runtime.get("model_provenance") or {}
            concise = {key: value for key, value in provenance.items() if key in ("backend", "repo", "repo_id", "revision", "source_revision", "weights_revision", "kind", "license", "variant", "protocol")}
            concise["weight_files"] = {name: info for name, info in provenance.get("artifacts", {}).items() if name.endswith((".pth", ".pt", ".onnx", ".safetensors", ".traineddata"))}
            if runtime.get("fastocr_weight_sha256"):
                concise["fastocr_weight_sha256"] = runtime["fastocr_weight_sha256"]
            lines.extend(["Checkpoint/source provenance:", "```json", json.dumps(concise, ensure_ascii=False, indent=2), "```", "",
                          "Runtime package versions, batch protocols, per-document timing và raw token/confidence/trace: xem `runtime.json`, `recognizer_config.json`, `run_fingerprint.json` và `cache/*/diagnostic.json` trong source artifact. Không dùng neutral pipeline confidence1.0 làm confidence calibrated.", ""])
        else:
            lines.extend(["API full-PDF tham chiếu; model/version/weights nội bộ không được xác minh từ artifact. Không gán kiến trúc hoặc checkpoint cụ thể và không ghép thứ hạng/timing với recognizer local trên crop cache.", ""])
        lines.extend(["| Trường (API) | Nhóm | F1 (precision, recall) | NEM | ACC tham chiếu | GT có giá trị | Trạng thái |", "| --- | --- | ---: | ---: | ---: | ---: | --- |"])
        for field in (field for field in all_fields if field["model_id"] == row["model_id"]):
            key = field["field_name"]
            lines.append(f"| {FIELD_LABELS[key]} (`{key}`) | {field['group']} | {number(field['f1'])} ({number(field['precision'])}, {number(field['recall'])}) | {number(field['nem'])} | {number(field['vai_acc'])} | {field['gt_present_count']} | {field['status']} |")
        lines.append("")
    (output / "REPORT.md").write_text("\n".join(lines))
    dump(output / "manifest.json", dict(status="completed", mode="rescore_and_analysis_only", metric_version=b.METRIC_VERSION,
         runs_rescored=len(runs), documents_per_run=100, gt_sha256=labels, current_gt_preserved=True,
         primary_inclusion="Document Success@5% > 0 OR TrOCR; four VNHTR cases additionally shown in full",
         best_hybrid_local_passed=best, best_hybrid_local_models=best_ids,
         new_routing_or_training_performed=False, benchmark_source_sha256=sha256(ROOT / "ocr-collab/benchmark.py")))
    print(output / "REPORT.md")


if __name__ == "__main__":
    main()
