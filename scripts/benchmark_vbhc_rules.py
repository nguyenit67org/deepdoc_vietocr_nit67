#!/usr/bin/env python3
"""Run the rule-based VBHC pipeline on the short-document baseline set.

The report follows the repository benchmark contract: NFKC/case/whitespace
normalization, CER<=5% for text correctness, and exact canonical matching for
dates/enums.  Raw GT/prediction values are retained per file for audit.
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module.extract import extract_vbhc
from module.pipeline import build_pipeline, load_pipeline_conf


FIELDS = (
    "type", "title", "code", "documentDate", "officeSender", "recipients",
    "signer", "priority_level", "security_level", "first_recipients",
    "signer_title", "province", "receiverDate",
)
DATE_ENUM_FIELDS = {"documentDate", "receiverDate", "priority_level", "security_level"}


def information(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("information", {})
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return value if isinstance(value, dict) else {}


def field_value(info: dict[str, Any], field: str) -> str:
    value = info.get(field, {})
    if isinstance(value, dict):
        value = value.get("value", "")
    return value if isinstance(value, str) else ""


def normalize(field: str, value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"\s+", " ", value).strip()
    if field != "code":
        value = re.sub(r"[,.:\"']", "", value)
    return value


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        for column, right_char in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def evaluate_field(field: str, gt_raw: str, pred_raw: str) -> dict[str, Any]:
    gt = normalize(field, gt_raw)
    pred = normalize(field, pred_raw)
    gt_present, pred_present = bool(gt), bool(pred)
    cer = None
    if field in DATE_ENUM_FIELDS:
        correct = gt_present and pred_present and gt == pred
    elif gt_present and pred_present:
        cer = edit_distance(gt, pred) / len(gt)
        correct = cer <= 0.05
    else:
        correct = False
    return {
        "gt_raw": gt_raw,
        "pred_raw": pred_raw,
        "gt_normalized": gt,
        "pred_normalized": pred,
        "normalized_exact": gt_present and pred_present and gt == pred,
        "correct": correct,
        "cer": cer,
        "gt_present": gt_present,
        "pred_present": pred_present,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for field, result in row.get("fields", {}).items():
            by_field[field].append(result)

    summary = {}
    for field in FIELDS:
        results = by_field[field]
        tp = sum(r["correct"] for r in results)
        fp = sum(r["pred_present"] and not r["correct"] for r in results)
        fn = sum(r["gt_present"] and not r["correct"] for r in results)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        present = sum(r["gt_present"] for r in results)
        nem = sum(r["normalized_exact"] for r in results) / present if present else 0.0
        summary[field] = {
            "samples": len(results),
            "gt_present": present,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "normalized_exact_match": nem,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-dir", type=Path, default=Path("data/benchmark_demo/clean"))
    parser.add_argument("--max-pages-exclusive", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("pipeline_outputs/vbhc_rule_baseline_lt10.json"))
    parser.add_argument("--disable-corrector", action="store_true")
    parser.add_argument(
        "--reuse-artifacts",
        action="store_true",
        help="Re-run only extraction/metrics from existing output.json and page PNG artifacts.",
    )
    parser.add_argument("--artifacts-dir", type=Path, default=Path("pipeline_outputs"))
    args = parser.parse_args()

    labels = []
    for path in sorted(args.clean_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        page_count = payload.get("page_count")
        pdf_file = payload.get("pdf_file")
        if isinstance(page_count, int) and page_count < args.max_pages_exclusive and isinstance(pdf_file, str):
            pdf_path = Path("data") / pdf_file
            if pdf_path.exists():
                labels.append((path, pdf_path, payload))

    pipeline = None
    if not args.reuse_artifacts:
        conf = load_pipeline_conf()
        if args.disable_corrector:
            conf.setdefault("corrector", {})["enabled"] = False
        pipeline = build_pipeline(conf)

    rows = []
    for index, (label_path, pdf_path, ground_truth) in enumerate(labels, 1):
        print(f"[{index}/{len(labels)}] {pdf_path.name}", flush=True)
        try:
            if args.reuse_artifacts:
                artifact_dir = args.artifacts_dir / pdf_path.stem
                raw = json.loads((artifact_dir / "output.json").read_text(encoding="utf-8"))
                pages = raw.get("pages", [])
                pages_blocks = [page.get("blocks", []) for page in pages]
                crop_offsets = [tuple(page.get("crop_offset", (0.0, 0.0))) for page in pages]
                processed_sizes = []
                for page_number in range(1, len(pages) + 1):
                    with Image.open(artifact_dir / "pages" / f"page_{page_number}.png") as image:
                        processed_sizes.append(image.size)
                # The raw artifact stores the top-left crop translation, not
                # the discarded right/bottom extents.  Reconstructing with a
                # symmetric-margin approximation is sufficient for the soft
                # normalized geometry rules and avoids rendering/OCR again.
                original_sizes = [
                    (
                        round(width + 2 * offset_x),
                        round(height + 2 * offset_y),
                    )
                    for (width, height), (offset_x, offset_y) in zip(processed_sizes, crop_offsets)
                ]
                prediction, _ = extract_vbhc(
                    pages_blocks,
                    original_sizes,
                    processed_sizes,
                    crop_offsets,
                )
                saved_prediction = artifact_dir / "prediction.json"
                if saved_prediction.exists():
                    prediction["processing_time"] = json.loads(
                        saved_prediction.read_text(encoding="utf-8")
                    ).get("processing_time", 0.0)
            else:
                assert pipeline is not None
                prediction = pipeline.process_pdf(str(pdf_path), source_filename=pdf_path.name)
            gt_info = information(ground_truth)
            pred_info = information(prediction)
            fields = {
                field: evaluate_field(field, field_value(gt_info, field), field_value(pred_info, field))
                for field in FIELDS
            }
            rows.append({
                "document": label_path.stem,
                "pdf": str(pdf_path),
                "page_count": ground_truth["page_count"],
                "processing_time": prediction["processing_time"],
                "status": "success",
                "fields": fields,
            })
        except Exception as exc:
            rows.append({
                "document": label_path.stem,
                "pdf": str(pdf_path),
                "page_count": ground_truth["page_count"],
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "fields": {},
            })
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    report = {
        "selection": {
            "clean_dir": str(args.clean_dir),
            "max_pages_exclusive": args.max_pages_exclusive,
            "documents": len(labels),
            "corrector_disabled": args.disable_corrector,
            "reused_artifacts": args.reuse_artifacts,
        },
        "successful": sum(row["status"] == "success" for row in rows),
        "errors": sum(row["status"] == "error" for row in rows),
        "average_processing_time": (
            sum(row.get("processing_time", 0.0) for row in rows if row["status"] == "success")
            / max(1, sum(row["status"] == "success" for row in rows))
        ),
        "fields": summarize(rows),
        "documents": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("selection", "successful", "errors", "average_processing_time", "fields")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
