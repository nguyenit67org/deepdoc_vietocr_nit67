"""Configuration-rich report from completed artifacts, without inference or rescoring."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = (
    ("recognizer_ab_20261015", ("fastocr_control", "ocrdoc", "vietocr_handwriting", "htr_convtext", "senocr")),
    ("recognizer_ab_additional_20261015", ("fastocr_control", "akaocr", "vietocr_original_seq2seq", "vietocr_original_transformer", "vietocr_dunghugging")),
    ("recognizer_ab_trocr_20261015", ("fastocr_control", "fastocr_words", "trocr_words")),
)
PROCESSING = {
    "fastocr": "PyTorch FP32 VGG Seq2Seq, native FastOCR process_input_batch/greedy decoder; proportional height-32 resize with configured min/max width and mixed-width padding, true sequence lengths in encoder. See fastocr/tool/translate.py and fastocr/config/*.yml. Baseline max forward batch 128.",
    "ocrdoc_onnx": "ONNX CUDA, FP32 preprocessing RGB height 48, proportional width capped 640, bilinear resize, (x/255-0.5)/0.5, zero right-padding to 640. Greedy CTC, published charset plus blank/space. Max batch 16.",
    "vietocr_onnx": "ONNX CUDA encoder_fp16/decoder_fp16, per-crop batch 1, RGB height 32 and native proportional width (minimum 32), bicubic resize, x/255. Autoregressive greedy decoding starts SOS=1, stops EOS=2 or 256 generated tokens; native token confidences are retained.",
    "htr_convtext": "PyTorch CUDA FP32, pinned upstream EMA state_dict, grayscale height 64, proportional width capped 512, pixel/255 and white right-padding, greedy CTC. Max batch 16, isolated worker IPC 32 parents. Internal benchmark approval does not clear conflicting upstream licenses for commercial redistribution.",
    "senocr": "PyTorch CUDA FP32 in Transformers 5 worker, parent and generation batch 1, IPC 32 parents. Native multimodal processor/chat template with OCR: prompt; greedy do_sample=false/num_beams=1, cache enabled, max_new_tokens=256. No page parser or detector used.",
    "akaocr": "AkaOCR 2.1.6 bundled ONNX CUDA reference. PIL RGB -> OpenCV BGR, upstream Recognitor proportional height-48 / model-shape [3,48,320] preprocessing and upstream CTC decoder; actual width policy is upstream helper with max_wh_ratio from config. Limited Vietnamese vocabulary. Batch cap from config.",
    "vietocr_original": "PyTorch CUDA FP32, pinned upstream process_input and greedy translate unchanged, height/min/max width from checkpoint config.yml. Outer batch capped 16, then subdivided into identical-resized-width buckets without mixed-width padding; restores input order. max_seq_length=128. DungHugging uses its own supplied architecture/config/weights, not original Transformer weights.",
    "word_to_line": "Composite projection whitespace cache + recognition. Parent batch cap 16. FastOCR word control: PyTorch CUDA FP32, word batch cap 128, native mixed-width padding. TrOCR: PyTorch CUDA FP32, word batch cap 8, eager attention, RGB 384x384 upstream mean/std 0.5, rescale 1/255, greedy num_beams=1/do_sample=false/use_cache=true/max_new_tokens=64, fast tokenizer. TrOCR isolated worker IPC 32 parent crops, TORCH_DISABLE_NATIVE_JIT=1. Empty segmentation remains empty without fallback.",
}


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lines = ["# Recognizer benchmark: configurations and results", "",
        "Hybrid cached-crop KIE diagnostic: 100 PDFs, 183 selected physical pages, 6,619 parent line crops per completed full run. Unselected pages keep baseline OCR. Detection/layout/extraction/GT are not changed to improve scores. This is not full inference over all 2,249 physical pages.", "",
        "FastOCR baseline recognition is PyTorch `vgg_seq2seq.pth`, not ONNX. Local FastOCR recognition ONNX graphs were not benchmarked. Official original Seq2Seq and FastOCR weights are byte-identical; implementation/preprocessing/batching differ.", "",
        "## Coverage and measured timing", "",
        "Timing is document recognition-adapter wall time summed / selected-page count. It includes preprocessing/decoding and worker IPC where present; model load is separate. No separate timing-only inference was run. Different batch sizes, model architectures and precision make this a comparison of tested configurations, not optimized/hardware-exclusive model speed. Supplemental CPU preparation overlapped some primary SenOCR inference. NVML resource exclusivity was not established.", "",
        "| Cohort / model | Status | Documents/pages/parent crops | Document Success@5% | Improvements/regressions | Recognition s/file | Recognition s/selected page | Model load s |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    records, per_file, missing = [], [], []
    reference_labels = None
    for cohort, models in EXPERIMENTS:
        for model in models:
            folder = ROOT / "ocr-collab/artifacts" / cohort / model
            manifest = folder / "manifest.json"
            if not manifest.is_file() or read(manifest).get("status") != "completed":
                missing.append(f"{cohort}/{model}")
                lines.append(f"| {cohort}/{model} | incomplete/not started | | | | | | |")
                continue
            summary = read(folder / "summary.json")
            labels = read(folder / "run_fingerprint.json")["labels"]
            if reference_labels is None:
                reference_labels = labels
            if labels != reference_labels or summary["metric_version"] != "2.2":
                raise ValueError("Cohort GT fingerprint or metric version differs; do not compare summaries")
            comparison = read(folder / "cached_recognize_vs_full.json")
            diagnostics = [read(p) for p in sorted((folder / "cache").glob("*/diagnostic.json"))]
            seconds = sum(row["recognition_seconds"] for row in diagnostics)
            pages = summary["selected_pages"]
            for row in diagnostics:
                per_file.append(dict(cohort=cohort, model=model, document_id=row["document_id"],
                                     recognition_seconds=row["recognition_seconds"], parent_crop_count=row["crop_count"]))
            record = dict(cohort=cohort, model=model, artifact=str(folder.relative_to(ROOT)),
                summary=summary, seconds=seconds, config=read(folder / "recognizer_config.json"),
                runtime=read(folder / "runtime.json"),
                model_provenance=read(folder / "runtime.json").get("model_provenance"),
                metrics=comparison["metrics"], changes=len(comparison["changed_cells"]),
                improvements=len(comparison["improvements"]), regressions=len(comparison["regressions"]),
                document_success=comparison["document_success_after"])
            records.append(record)
            passed = record["document_success"]["passed_documents"]
            lines.append(f"| {cohort}/{model} | completed | {summary['documents']}/{pages}/{summary['total_crops']} | {passed}/{summary['documents']} | {record['improvements']}/{record['regressions']} | {seconds/summary['documents']:.3f} | {seconds/pages:.3f} | {summary['model_load_seconds']:.3f} |")
    lines += ["", "## Interpretation and limitations", "",
        "- FastOCR remains the default. A higher Document Success does not imply all critical fields improved or met per-field targets. Primary SenOCR and original Transformer both reached 47/100, not the 80% PoC target. Visual review of all field transitions remains pending.",
        "- AkaOCR is the public 2.1.6 bundled reference, with limited Vietnamese vocabulary. Its result is not a measurement of a commercial AkaOCR service. Poor HTR/DungHugging results have not been causally attributed without image/preprocessing review.",
        "- No line/word transcription GT exists; no recognition CER/WER is claimed. KIE field metrics are not recognizer-only transcription metrics.",
        "- TrOCR composite is a best-effort whitespace segmentation ablation, not a clean recognizer-only swap. Tight/justified/multiline/vertical crops and ink bridges can remain multi-word; punctuation can become standalone segments. See `recognizer_ab_trocr_20261015/segmentation_review_final/review.json` and visual sheets.",
        "- A = FastOCR whole line; B = fixed whitespace segments + FastOCR; C = the same segments + TrOCR. A/B measures the combined segmentation/context/assembly effect. B/C fixes word inputs but still compares differing recognition implementations. All retain original parent line geometry.",
        "- Segmentation uses Otsu foreground, all-row column projection, gap >= max(2, ceil(0.18 * parent height)), horizontal pad 1 pixel, full parent height. No stamp removal, rotation, filename rules, GT corrections or model fallback. Assembly strips decoded segment edges, drops empty segment text and joins with one ASCII space. Native words/boxes/hashes/truncation remain available.", ""]
    cache = ROOT / "ocr-collab/artifacts/recognizer_ab_trocr_20261015/word_crop_cache_manifest.json"
    if cache.is_file():
        mapping = read(cache)
        lines += ["## Word cache preparation and timing", "",
            f"Frozen mapping: {mapping['parent_count']} parent crops -> {mapping['word_count']} segments; {mapping['blank_parents']} blank parents. Offline preparation wall time {mapping['preparation_wall_seconds']:.3f} s; summed segmentation compute {mapping['segmentation_compute_seconds']:.3f} s ({mapping['segmentation_compute_seconds']/183:.4f} s/selected page). Preparation wall includes loading/writing/hashing, not just segmentation.", "",
            "Both composite branches use warm word mappings. Their table timing includes cache lookup, crop/hash validation, word inference, assembly and IPC. Offline segmentation computation is reported separately, not silently omitted or claimed as measured online end-to-end latency. Do not sum per-line `batch_word_recognition_seconds`: that value repeats for every parent in a batch.", ""]
    lines += ["## Exact configs and per-field metrics", "",
        "For text, F1 follows its field-specific 5% policy; exact/date/enum fields remain exact as specified by metric 2.2. VAI-style ACC is normalized internally, reference-only; datasheet input conditions have not been verified. `receiverDate` is out of scope. See the comparison CSV for precision/recall, hallucination, coverage and target states. PoC per-field target: F1/precision/recall >=0.85; stretch >=0.90; NEM >=0.75. Missing denominators/classes mean not fully evaluated.", ""]
    for record in records:
        artifact = record["artifact"]
        lines += [f"### {record['cohort']}/{record['model']}", "", f"Artifact: `{artifact}/`", "",
            "```json", json.dumps(record["config"], ensure_ascii=False, indent=2), "```", "",
            PROCESSING[record["config"]["backend"]], "",
            "Runtime/precision/preprocessing evidence: `runtime.json` (including model_provenance), `run_fingerprint.json`, `recognizer_config.json`, and per-page `cache/*/page_*/results.json`. Configured batch size is an upper bound, not proof every forward pass had that size. All candidates use neutral line assembly confidence 1.0; native scores remain diagnostic.", ""]
        provenance = record["model_provenance"] or {}
        concise_provenance = {k: v for k, v in provenance.items() if k != "artifacts"}
        if record["config"]["backend"] == "fastocr":
            concise_provenance["baseline_weight_sha256"] = record["runtime"]["fastocr_weight_sha256"]
        concise_provenance["weights_and_configs"] = {k: v for k, v in provenance.get("artifacts", {}).items()
            if k.endswith((".pth", ".onnx", ".safetensors", "config.json", "config.yml", "processor_config.json"))}
        lines += ["Checkpoint/source provenance:", "", "```json", json.dumps(concise_provenance, ensure_ascii=False, indent=2), "```", "",
            "Runtime package versions:", "", "```json", json.dumps({k: record["runtime"].get(k) for k in ("packages", "worker_runtime", "recognition_batch_protocol")}, indent=2), "```", "",
            "| Field | F1 (precision, recall) | NEM | VAI-style ACC, reference | F1 delta vs cohort control |",
            "|---|---:|---:|---:|---:|"]
        def number(value):
            return "N/A" if value is None else f"{value:.4f}"
        for m in record["metrics"]:
            lines.append(f"| {m['field']} | {number(m['f1_after'])} ({number(m['precision_after'])}, {number(m['recall_after'])}) | {number(m['nem_after'])} | {number(m['vai_acc_after'])} | {number(m['f1_delta'])} |")
        lines.append("")
    lines += ["## Reproducibility and tests", "",
        "Every completed run has source/config/model/GT hashes, exact crop mapping, checkpoints and its own predictions/evaluations. Prior artifacts and GT were preserved. No commits or deployment/default switch were performed. See `docs/ai-sessions/2026-10-15-ocr-recognizer-ab-plan.md` for timeline, approvals, download revisions and known runtime blockers.", "",
        "TrOCR blockers resolved: missing slow-tokenizer vocab/merges avoided by using the supplied tokenizer.json with the fast tokenizer; unified image processor settings read explicitly. PyTorch native bmm attempted Triton compilation without a host C compiler; isolated worker uses TORCH_DISABLE_NATIVE_JIT=1, still CUDA. No model weight edits or CPU fallback.", "",
        "Validation before final cohort: 27 recognizer/reporting tests, 70 VBHC tests passed. Segmentation tests cover order, full-height diacritics, stable hashes/cache, blank input, invalid policy and neutral scores. Test logs and final validation status are recorded in the persistent plan.", "",
        "Status: " + ("partial; missing " + ", ".join(missing) if missing else "all planned full runs completed; visual root-cause review remains pending"), ""]
    (args.output / "REPORT.md").write_text("\n".join(lines))
    (args.output / "manifest.json").write_text(json.dumps(dict(status="partial" if missing else "completed", missing=missing,
        mode="configuration_rich_hybrid_recognizer_report", completed_runs=len(records), visual_review="pending except segmentation smoke"), indent=2) + "\n")
    (args.output / "runs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    with (args.output / "recognition_per_file.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_file[0]))
        writer.writeheader()
        writer.writerows(per_file)
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
