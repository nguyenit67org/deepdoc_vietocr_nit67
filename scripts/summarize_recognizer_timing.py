"""Export measured file timings and average seconds per selected page.

Read-only with respect to inference artifacts. No model loading, inference or
individual-page profiling: averages preserve the original cross-page batching.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import dump, write_csv

MODELS = ("fastocr_control", "ocrdoc", "vietocr_handwriting", "htr_convtext", "senocr",
          "akaocr", "vietocr_original_seq2seq", "vietocr_original_transformer", "vietocr_dunghugging")


def read(path):
    return json.loads(path.read_text())


def primary_file_timings(experiment, models):
    rows = []
    for name in models:
        folder = experiment / name
        if not (folder / "manifest.json").is_file():
            continue
        manifest = read(folder / "manifest.json")
        if manifest["status"] != "completed":
            continue
        selected = {doc["document_id"]: len(doc["selected_pages_0based"])
                    for doc in read(folder / "preflight.json")["documents"]}
        has_ipc = bool((read(folder / "recognizer_config.json") or {}).get("runtime"))
        for index, document_id in enumerate(manifest["documents"]):
            diagnostic = read(folder / "cache" / document_id / "diagnostic.json")
            seconds, pages = diagnostic["recognition_seconds"], selected[document_id]
            if pages < 1 or seconds < 0:
                raise ValueError(f"Invalid timing denominator/value: {name}/{document_id}")
            rows.append(dict(model=name, document_id=document_id, selected_pages=pages,
                crop_count=diagnostic["crop_count"], recognition_adapter_wall_seconds=seconds,
                mean_recognition_seconds_per_selected_page=seconds / pages,
                first_document_in_dataset_order=index == 0,
                protocol="primary KIE run: selected pages batched per document",
                includes_model_load=False, includes_page_cache_decode=False, includes_adapter_ipc=has_ipc))
    return rows


def summarize_models(rows):
    summaries = []
    for name in dict.fromkeys(row["model"] for row in rows):
        selected = [row for row in rows if row["model"] == name]
        seconds = sum(row["recognition_adapter_wall_seconds"] for row in selected)
        pages = sum(row["selected_pages"] for row in selected)
        crops = sum(row["crop_count"] for row in selected)
        summaries.append(dict(model=name, documents=len(selected), selected_pages=pages, crop_count=crops,
            total_recognition_adapter_wall_seconds=seconds,
            mean_recognition_seconds_per_file=seconds / len(selected),
            mean_recognition_seconds_per_selected_page=seconds / pages,
            recognition_crops_per_second=crops / seconds if seconds else None,
            aggregation="sum document recognition seconds / sum selected pages; NOT mean of file ratios or individual-page latency"))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", choices=MODELS, action="append")
    args = parser.parse_args()
    experiment, output = args.experiment.resolve(), args.output.resolve()
    rows = primary_file_timings(experiment, args.model or MODELS)
    if not rows:
        raise ValueError("No completed primary runs available; no timing figures invented")
    summaries = summarize_models(rows)
    for row in summaries:
        summary = read(experiment / row["model"] / "summary.json")
        row.update(model_load_seconds=summary["model_load_seconds"],
                   diagnostic_wall_seconds_current_invocation=summary["experiment_seconds"],
                   resumed=summary.get("resumed", False))
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "primary_file_timing.csv", rows, list(rows[0]))
    write_csv(output / "model_timing_summary.csv", summaries, list(summaries[0]))
    dump(output / "manifest.json", dict(status="completed", mode="primary_batch_timing_summary", inference_run=False,
        completed_models=[row["model"] for row in summaries],
        individual_page_latency_measured=False,
        note="Per-page values are batch-derived means over selected physical pages only; no extra recognition pass."))


if __name__ == "__main__":
    main()
