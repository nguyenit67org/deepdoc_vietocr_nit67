"""Validate both completed cohorts and export a self-contained final comparison."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021"
SECOND = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_extended_20261021"
RUNS = (
    (FIRST, "fastocr_control", "FastOCR control"),
    (FIRST, "trocr_duyle", "Duyle TrOCR"),
    (SECOND, "vnhtr_vgg_base", "VNHTR VietOCR/VGG Transformer fine-tuned, no head"),
    (FIRST, "vnhtr_vgg", "VNHTR VietOCR/VGG Transformer fine-tuned + Rethinking Head"),
    (SECOND, "vnhtr_trocr_base", "VNHTR TrOCR fine-tuned, no head"),
    (FIRST, "vnhtr_trocr", "VNHTR TrOCR fine-tuned + Rethinking Head"),
    (FIRST, "vietdoc_vudang_pth", "VietDoc-downloaded Vudang PyTorch checkpoint"),
    (SECOND, "easyocr_latin_pretrained", "EasyOCR Latin Gen2 pretrained, NOT fine-tuned"),
)


def read(path):
    return json.loads(path.read_text())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def predictions(folder):
    rows = [json.loads(line) for line in (folder / "candidate_predictions.jsonl").read_text().splitlines() if line.strip()]
    if len(rows) != 100 or len({row["document_id"] for row in rows}) != 100:
        raise ValueError(f"Incomplete/duplicate prediction coverage: {folder}")
    return {row["document_id"]: row["prediction"] for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for cohort in (FIRST, SECOND):
        status = read(cohort / "cohort_status.json")
        if status["status"] != "finished" or any(value != "completed" for value in status["outcomes"].values()):
            raise ValueError(f"Not all requested runs completed: {cohort}")
    labels = read(FIRST / "fastocr_control/run_fingerprint.json")["labels"]
    if labels != read(SECOND / "fastocr_control/run_fingerprint.json")["labels"]:
        raise ValueError("Cross-cohort GT fingerprints differ")
    if predictions(FIRST / "fastocr_control") != predictions(SECOND / "fastocr_control"):
        raise ValueError("Cross-cohort control predictions differ")
    graph_audit = read(FIRST / "source_audit/vnhtr/case_assets.json")
    if len(graph_audit["cases"]) != 4 or any(row["status"] != "verified" for row in graph_audit["cases"]):
        raise ValueError("All four serialized VNHTR case identities must be verified")
    for doc, expected in labels.items():
        if sha256(ROOT / "data/benchmark_demo/clean" / f"{doc}.json") != expected:
            raise ValueError(f"GT changed since the experiment: {doc}")
    models, fields, timings, provenance = [], [], [], []
    for cohort, name, label in RUNS:
        folder = cohort / name
        manifest, summary = read(folder / "manifest.json"), read(folder / "summary.json")
        fingerprint = read(folder / "run_fingerprint.json")
        evaluation = read(folder / "evaluation/candidate/summary.json")
        if manifest["status"] != "completed" or len(manifest["documents"]) != 100:
            raise ValueError(f"Run incomplete: {name}")
        if fingerprint["labels"] != labels or summary["metric_version"] != "2.2":
            raise ValueError(f"Run has incompatible GT or metric version: {name}")
        if summary["total_crops"] != 6619 or summary["selected_pages"] != 183:
            raise ValueError(f"Run has incompatible crop/page coverage: {name}")
        if set(predictions(folder)) != set(labels):
            raise ValueError(f"Wrong document IDs: {name}")
        seconds = 0.0
        selected = {row["document_id"]: len(row["selected_pages_0based"]) for row in read(folder / "preflight.json")["documents"]}
        for doc in manifest["documents"]:
            diagnostic = read(folder / "cache" / doc / "diagnostic.json")
            elapsed = diagnostic["recognition_seconds"]
            if elapsed < 0:
                raise ValueError("Negative timing")
            seconds += elapsed
            timings.append(dict(model=name, document_id=doc, selected_pages=selected[doc], crops=diagnostic["crop_count"], adapter_wall_seconds=elapsed))
        success = evaluation["document_success_at_5"]
        models.append(dict(model=name, label=label, documents=100, selected_pages=183, crops=6619,
            document_success_passed=success["passed_documents"], document_success_rate=success["rate"],
            total_adapter_wall_seconds=seconds, mean_adapter_wall_seconds_per_selected_page=seconds / 183,
            artifact=str(folder), full_inference=False))
        with (folder / "evaluation/candidate/metrics.csv").open(encoding="utf-8-sig") as handle:
            scored = list(csv.DictReader(handle))
        if len(scored) != 12 or any(row["field_name"] == "receiverDate" for row in scored):
            raise ValueError(f"Expected the canonical 12 evaluated fields: {name}")
        fields.extend(dict(model=name, **row) for row in scored)
        config = manifest.get("recognizer_config")
        provenance.append(dict(model=name, config=config, download_manifest=read(ROOT / config["model_dir"] / "download_manifest.json") if config else None))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "models.csv", models)
    write_csv(output / "fields.csv", fields)
    write_csv(output / "per_document_timing.csv", timings)
    (output / "configs_and_provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    (output / "validation.json").write_text(json.dumps(dict(status="validated", models=len(models),
        documents_per_model=100, selected_pages_per_model=183, crops_per_model=6619, metric_version="2.2",
        identical_gt_fingerprints=True, current_gt_unchanged=True, cross_cohort_fastocr_predictions_exact=True,
        vnhtr_head_identity_audit=str(FIRST / "source_audit/vnhtr/case_assets.json")), indent=2) + "\n")
    text = ["# Candidate OCR recognizer results, 2026-10-21", "",
        "Completed: all four requested VNHTR fine-tuned cases, Duyle TrOCR, VietDoc-downloaded Vudang PyTorch checkpoint, and the additionally approved EasyOCR pretrained baseline.", "",
        "Each run: 100 documents / 183 GT-selected pages / 6,619 fixed cached crops. Metric 2.2; identical current GT; both FastOCR integration controls produce exactly the same 100 predictions. This is a hybrid cached recognizer ablation, NOT full-page end-to-end OCR or recognition CER/WER.", "",
        "| Model/checkpoint case | Document Success@5% | Adapter seconds / selected page |", "| --- | ---: | ---: |"]
    text.extend(f"| {row['label']} | {row['document_success_passed']}/100 | {row['mean_adapter_wall_seconds_per_selected_page']:.3f} |" for row in models)
    text.extend(["", "## Metrics and evidence", "",
        "- `fields.csv`: all 12 evaluated fields, with F1, precision, recall, NEM, reference VAI-style ACC, coverage, hallucination and target status. `receiverDate` is retained by the API but not evaluated.",
        "- `models.csv`, `per_document_timing.csv`: measured adapter wall time, including IPC where configured; excludes model load, page detection and crop generation. Shared GPU/local API and CPU preparation mean host/device-exclusive timing is NOT established.",
        "- `configs_and_provenance.json`: checkpoint/source revisions and hashes, native configs and inference limits. Full token/crop diagnostics remain in each source run listed in `models.csv`.",
        "- Detailed changes and labeled handwriting/stamp field strata are in each cohort's `comparison_final/`; these are KIE metadata strata, not line-level transcription evaluation.", "",
        "## Interpretation and blockers", "",
        "- VNHTR no-head cases are the author's trained/fine-tuned weights, not the unmodified upstream models. Four serialized decoder graphs and checksums were audited independently; head/no-head tokenizer/preprocessing sources match within each model family. Distinct trained checkpoints do not establish a causal head-toggle effect.",
        "- Exact VNHTR training dataset names and checkpoint-to-data manifests are not public in the inspected source. Do not assert UIT-HWDB or VNOnDB; see `source_audit/vnhtr/training_dataset_notes.md` in the first cohort.",
        "- VietDoc native download scripts succeeded. Its base checkpoint exactly duplicates previously tested upstream VietOCR Transformer weights. Its handwriting download is Vudang `best_ep11.pth`; this run is a checkpoint-only upstream VietOCR ablation, not the native VietDoc app decoder or its unavailable fine-tuned EasyOCR model.",
        "- EasyOCR is official Latin Gen2 pretrained. Only recognition ran; downloaded CRAFT detection weights were not used. It is NOT the project's fine-tuned `viet_handwriting` package.",
        "- VietHandOCR: no project-specific fine-tuned weights found in pinned source or public releases; no training or pretrained substitution was performed. Its training notebook starts from upstream VietOCR, which was already tested separately.",
        "- Scores do not establish error causes without detailed visual review. No model was promoted to default; GT, extraction and metric policy were not changed.", ""])
    (output / "REPORT.md").write_text("\n".join(text))
    print(output / "REPORT.md")


if __name__ == "__main__":
    main()
