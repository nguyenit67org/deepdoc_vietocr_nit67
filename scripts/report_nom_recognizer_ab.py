"""Report paired raw/corrected Nôm outputs and separate OCR/correction timings."""
import csv
import json
from pathlib import Path
import sys


def read(path):
    return json.loads(path.read_text())


def details(folder):
    output = {}
    for page in sorted((folder / "cache").glob("*/page_*/results.json")):
        data = read(page)
        if len(data["recognition_details"]) != len(data["recognition"]):
            raise ValueError("Missing recognizer details")
        for recognition, detail in zip(data["recognition"], data["recognition_details"]):
            key = page.parent.parent.name, page.parent.name, recognition["crop_index"]
            if key in output:
                raise ValueError("Duplicate crop identity")
            output[key] = detail
    return output


def main():
    root = Path(sys.argv[1]).resolve()
    raw_dir, spell_dir = root / "nom_tesseract_raw", root / "nom_tesseract_spell"
    for folder in (root / "fastocr_control", raw_dir, spell_dir):
        if read(folder / "manifest.json")["status"] != "completed":
            raise ValueError(f"Incomplete inference: {folder}")
    raw, spell = details(raw_dir), details(spell_dir)
    if raw.keys() != spell.keys() or len(raw) != 6619:
        raise ValueError("Raw/corrected crop coverage differs")
    rows, documents = [], {}
    for key in raw:
        before, after = raw[key], spell[key]
        old, new = before["metadata"], after["metadata"]
        if before["raw_text"] != new["raw_ocr_text"] or old["raw_cache_key"] != new["raw_cache_key"] or not new["no_ocr_rerun"]:
            raise ValueError(f"Corrected branch did not use identical raw OCR: {key}")
        rows.append(dict(document_id=key[0], page=key[1], crop_index=key[2], raw_text=before["raw_text"],
            corrected_text=after["raw_text"], changed=before["raw_text"] != after["raw_text"],
            original_ocr_seconds=old["raw_ocr_seconds"], correction_seconds_amortized=new["correction_seconds_amortized"],
            input_tokens=new["correction_input_tokens"], input_truncated=new["input_truncated"], raw_cache_key=new["raw_cache_key"]))
        doc = documents.setdefault(key[0], dict(pages=set(), crops=0, raw_ocr_compute_seconds=0.0, correction_compute_seconds=0.0))
        doc["pages"].add(key[1])
        doc["crops"] += 1
        doc["raw_ocr_compute_seconds"] += old["raw_ocr_seconds"]
        doc["correction_compute_seconds"] += new["correction_seconds_amortized"]
    file_rows = []
    for name, stats in documents.items():
        pages = len(stats.pop("pages"))
        raw_wall = read(raw_dir / "cache" / name / "diagnostic.json")["recognition_seconds"]
        spell_wall = read(spell_dir / "cache" / name / "diagnostic.json")["recognition_seconds"]
        file_rows.append(dict(document_id=name, selected_pages=pages, **stats,
            raw_adapter_seconds=raw_wall, correction_adapter_seconds=spell_wall,
            summed_two_stage_seconds=raw_wall+spell_wall,
            raw_seconds_per_selected_page=raw_wall/pages,
            summed_two_stage_seconds_per_selected_page=(raw_wall+spell_wall)/pages))
    pages = sum(row["selected_pages"] for row in file_rows)
    if len(file_rows) != 100 or pages != 183:
        raise ValueError("Unexpected complete run coverage")
    for name, data in (("paired_crop_text.csv", rows), ("timing_per_file.csv", file_rows)):
        with (root / name).open("x") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    direct = read(root / "spell_vs_raw/nom_tesseract_spell_vs_fastocr.json")
    raw_report = read(raw_dir / "cached_recognize_vs_full.json")
    control_report = read(root / "fastocr_control/cached_recognize_vs_full.json")
    raw_seconds = sum(row["raw_adapter_seconds"] for row in file_rows)
    correction_seconds = sum(row["correction_adapter_seconds"] for row in file_rows)
    raw_compute = sum(row["raw_ocr_compute_seconds"] for row in file_rows)
    spell_compute = sum(row["correction_compute_seconds"] for row in file_rows)
    provenance = read(raw_dir / "runtime.json")["model_provenance"]
    lines = ["# Nôm Tesseract: without / with Vietnamese spell correction", "",
        "Completed hybrid cached-crop diagnostic: 100 documents, 183 selected physical pages, 6,619 identical line crops. Unselected pages keep baseline OCR. No word splitting, GT edits or extraction changes. Metric 2.2 and matching GT/code fingerprints are enforced by the comparison exporter.", "",
        "## Results", "",
        "| Branch | Document Success@5% | Adapter seconds / selected page |", "|---|---:|---:|",
        f"| FastOCR fresh control | {control_report['document_success_after']['passed_documents']}/100 | see timing_final/ |",
        f"| Nôm Tesseract raw | {raw_report['document_success_after']['passed_documents']}/100 | {raw_seconds/pages:.3f} |",
        f"| Same raw + correction | {direct['document_success_after']['passed_documents']}/100 | {(raw_seconds+correction_seconds)/pages:.3f} (sum of two stages) |", "",
        f"Correction changed {sum(row['changed'] for row in rows)}/6,619 crop texts, {len(direct['changed_cells'])} KIE field values; {len(direct['improvements'])} improved bucket transitions and {len(direct['regressions'])} regressed vs raw. Other changes are not automatically improvements. Visual root-cause review remains pending.", "",
        "## Configuration", "",
        "- Actual approved wrapper: nom.doc.stages.OCR.run(Context(...)), not the absent documented nom.doc.ocr.TesseractOCR. Pytesseract 0.3.13 -> isolated Tesseract 5.5.1, CPU, OMP_THREAD_LIMIT=1, vie from pinned tessdata_best, --psm 6 --oem 1. One crop per Tesseract subprocess; parent batch cap 16, IPC 32 are not native GPU OCR batches.",
        "- Unchanged RGB PNG encoding of fixed BGR crops. No external resize/deskew/contrast preprocessing. The actual upstream stage only strips output edges; it does not implement the docs' claimed NFC preprocessing or fallback. Internal Tesseract processing remains native.",
        "- Raw full run performs OCR; corrected full run is forbidden to re-run OCR and reads the exact cached raw strings. Paired equality and crop/policy hashes were checked for all inputs.",
        "- Upstream HFDiacriticModel.predict_batch, nrl-ai/vn-spell-correction-base, CUDA FP32, greedy num_beams=1, input/generation max length 512, dynamic padding, batch cap 16. Default heading_retry=True retains upstream conditional lowercase retry/tone-only merge. Empty strings pass through. No added confidence gate, field protection or GT-dependent rules.",
        f"- Input truncation: {sum(row['input_truncated'] for row in rows)} crops. Upstream does not expose generated EOS/token IDs; output truncation is not independently observable, not claimed absent.",
        "- Baseline environment unchanged; worker adds isolated pytesseract and pinned Nôm source. Local offline model loading and worker-only TORCH_DISABLE_NATIVE_JIT=1 (still CUDA). No sudo/system-wide engine install.", ""]
    for name, folder in (("Raw", raw_dir), ("Corrected", spell_dir)):
        lines += [name + " config:", "```json", json.dumps(read(folder / "recognizer_config.json"), indent=2), "```", ""]
    lines += ["Source/model provenance:", "```json", json.dumps({k: v for k, v in provenance.items() if k != "artifacts"}, indent=2), "```", "",
        "Asset SHA-256 hashes are in runtime.json -> model_provenance.artifacts and download_manifest.json; runtime/package/source fingerprints are recorded per run.", "",
        "## Timing", "",
        f"Raw adapter: {raw_seconds:.3f} s total; {raw_seconds/100:.3f} s/file; {raw_seconds/pages:.3f} s/selected page. Correction-only adapter: {correction_seconds:.3f} s total; {correction_seconds/100:.3f} s/file; {correction_seconds/pages:.3f} s/page. Sum: {raw_seconds+correction_seconds:.3f} s; {(raw_seconds+correction_seconds)/pages:.3f} s/page.", "",
        f"Within stages: native OCR/encoding {raw_compute:.3f} s; correction/tokenization/retry {spell_compute:.3f} s. Correction batch time is amortized equally per input for accounting, not individual-crop latency. Adapter wall also includes cache IO/validation/IPC. Model load is separate. The two-stage sum is not a measured fused online pipeline or pure GPU time. No timing-only inference pass.", "",
        "## Per-field correction effect", "",
        "| Field | Raw F1 (precision, recall) | Corrected F1 (precision, recall) | NEM raw -> corrected | VAI-style ACC raw -> corrected |",
        "|---|---:|---:|---:|---:|"]
    def n(value):
        return "N/A" if value is None else f"{value:.4f}"
    for m in direct["metrics"]:
        lines.append(f"| {m['field']} | {n(m['f1_before'])} ({n(m['precision_before'])}, {n(m['recall_before'])}) | {n(m['f1_after'])} ({n(m['precision_after'])}, {n(m['recall_after'])}) | {n(m['nem_before'])} -> {n(m['nem_after'])} | {n(m['vai_acc_before'])} -> {n(m['vai_acc_after'])} |")
    lines += ["", "PoC per-field target: F1/precision/recall >=0.85, NEM >=0.75; stretch F1/precision/recall >=0.90. Hallucination <=0.01 (province <=0.02). Missing denominators/classes mean not fully evaluated. VAI-style ACC is internally normalized, reference-only; datasheet input conditions unverified. No transcription GT, so no recognition CER/WER.", "",
        "## Artifacts", "",
        "- comparison_vs_fastocr/: both branches vs fresh control; per-field/bucket/target/metadata strata.",
        "- spell_vs_raw/: paired correction effect. Legacy JSON name ends _vs_fastocr.json but manifest identifies raw Tesseract as actual control.",
        "- paired_crop_text.csv: raw/corrected strings, change flags, hashes and truncation.",
        "- timing_per_file.csv: raw/correction/summed document times and selected-page means.",
        "- timing_final/: adapter-only exports; spell entry alone excludes prior raw OCR time.",
        "- Each run: cache/*/page_*/results.json, diagnostics, model/code/GT fingerprints, evaluation tables, checkpoints.",
        "- *.log.health.jsonl: 40-second process/progress/GPU monitoring snapshots; inactivity warnings are not proof of failure.", "",
        "FastOCR remains default. Existing results and GT were preserved. Tests and smoke validation are recorded in docs/ai-sessions/2026-10-15-ocr-recognizer-ab-plan.md.", ""]
    (root / "REPORT.md").write_text("\n".join(lines))
    (root / "paired_report_manifest.json").write_text(json.dumps(dict(status="completed", documents=100,
        selected_pages=183, paired_crops=6619, raw_input_equal=True, no_ocr_rerun_in_corrected=True,
        changed_crop_texts=sum(row["changed"] for row in rows), input_truncations=sum(row["input_truncated"] for row in rows),
        raw_adapter_seconds=raw_seconds, correction_adapter_seconds=correction_seconds,
        summed_two_stage_seconds=raw_seconds+correction_seconds, visual_review="pending"), indent=2) + "\n")
    print(root / "REPORT.md")


if __name__ == "__main__":
    main()
