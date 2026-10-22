"""Compare completed hybrid recognizer runs, without inventing line transcription GT."""
import argparse
import json
import statistics
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_cached_ocr_equivalence import compare, dump, write_csv, sha256


def records(path):
    return [json.loads(line) for line in (path / "candidate_predictions.jsonl").read_text().splitlines() if line.strip()]


def metadata_value(record, key, default):
    return record.get("metadata", {}).get(key, {}).get("value", default)


def in_field_scope(record, field, scope):
    if not all(isinstance(metadata_value(record, key, None), list)
               for key in ("handwritten_fields", "stamp_affected_fields")):
        return False  # Unknown metadata is not a visual negative label.
    handwritten = field in metadata_value(record, "handwritten_fields", [])
    stamped = field in metadata_value(record, "stamp_affected_fields", [])
    return {
        "handwritten_fields": handwritten,
        "stamp_affected_fields": stamped,
        "handwriting_and_stamp": handwritten and stamped,
        "handwriting_without_stamp": handwritten and not stamped,
        "stamp_without_handwriting": stamped and not handwritten,
        "neither_labeled_flag": not handwritten and not stamped,
    }[scope]


def metrics_from_scored_cells(rows):
    """Aggregate existing benchmark cells, never re-normalize or re-score text."""
    import benchmark as b
    tp, fp, fn, tn = (sum(row[key] for row in rows) for key in ("tp", "fp", "fn", "tn"))
    gt_present = [row for row in rows if row["gt_present"]]
    acc = [row["vai_acc"] for row in rows if row["vai_acc"] is not None]
    hallucinations = sum(row["error_bucket"] == "Hallucination" for row in rows)
    return dict(f1=b._safe_div(2 * tp, 2 * tp + fp + fn), precision=b._safe_div(tp, tp + fp),
        recall=b._safe_div(tp, tp + fn),
        nem=b._safe_div(sum(bool(row["exact_match"]) for row in gt_present), len(gt_present)),
        vai_acc=statistics.fmean(acc) if acc else None,
        hallucination_rate=b._safe_div(hallucinations, hallucinations + tn))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    args = parser.parse_args()
    import benchmark as b
    control = args.control.resolve()
    baseline = records(control)
    baseline_labels = json.loads((control / "run_fingerprint.json").read_text())["labels"]
    current_cases = {case.document_id: case for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    if any(sha256(current_cases[name].json_path) != digest for name, digest in baseline_labels.items()):
        raise ValueError("Current GT differs from frozen experiment; use an explicit new rescore protocol, not mixed summaries")
    baseline = [{**r, "ground_truth": current_cases[r["document_id"]].ground_truth} for r in baseline]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metrics, samples, resources, strata = [], [], [], []
    baseline_cells = b.evaluate_records(baseline)[0]
    for candidate_path in args.candidate:
        folder = candidate_path.resolve()
        manifest = json.loads((folder / "manifest.json").read_text())
        if manifest["status"] != "completed":
            raise ValueError(f"Run not completed: {folder}")
        fingerprint = json.loads((folder / "run_fingerprint.json").read_text())
        if fingerprint["labels"] != baseline_labels:
            raise ValueError("Candidate/control GT fingerprint mismatch")
        if fingerprint["dependencies"] != json.loads((control / "run_fingerprint.json").read_text())["dependencies"]:
            raise ValueError("Candidate/control code fingerprint mismatch")
        candidate = [{**r, "ground_truth": current_cases[r["document_id"]].ground_truth} for r in records(folder)]
        report = compare(baseline, candidate)
        candidate_cells = b.evaluate_records(candidate)[0]
        name = folder.name
        dump(output / f"{name}_vs_fastocr.json", report)
        improved = {(r["document_id"], r["field"]) for r in report["improvements"]}
        regressed = {(r["document_id"], r["field"]) for r in report["regressions"]}
        for row in report["changed_cells"]:
            cell = row["document_id"], row["field"]
            samples.append({**row, "model": name,
                "transition_kind": "improvement" if cell in improved else "regression" if cell in regressed else "other_change",
                "baseline_diagnostic": str(control / "cache" / cell[0] / "diagnostic.json"),
                "candidate_diagnostic": str(folder / "cache" / cell[0] / "diagnostic.json"),
                "review_status": "pending_visual_review"})
        for row in report["metrics"]:
            field = row["field"]
            metrics.append(dict(model=name, **row, targets=json.dumps(b.field_targets(field), ensure_ascii=False),
                improvements=sum(r["field"] == field for r in report["improvements"]),
                regressions=sum(r["field"] == field for r in report["regressions"]), decision="pending_visual_review"))
        for old in baseline:
            doc = old["document_id"]
            old_diag = json.loads((control / "cache" / doc / "diagnostic.json").read_text())
            new_diag = json.loads((folder / "cache" / doc / "diagnostic.json").read_text())
            resources.append(dict(model=name, document_id=doc, baseline_adapter_wall_seconds=old_diag["recognition_seconds"],
                candidate_adapter_wall_seconds=new_diag["recognition_seconds"], crop_count=new_diag["crop_count"],
                resource_delta_comparable=False, reason="No matched NVML/shared-GPU resource protocol; times include adapter/IPC"))
        model_resources = [row for row in resources if row["model"] == name]
        resources.append(dict(model=name, document_id="__all__",
            baseline_adapter_wall_seconds=sum(row["baseline_adapter_wall_seconds"] for row in model_resources),
            candidate_adapter_wall_seconds=sum(row["candidate_adapter_wall_seconds"] for row in model_resources),
            crop_count=sum(row["crop_count"] for row in model_resources), resource_delta_comparable=False,
            reason="Sum of per-document adapter wall time; not full inference or isolated GPU kernel time"))
        # Metadata flags concern labeled KIE field values, not every crop on a flagged page.
        for field in b.FIELDS:
            for scope in ("handwritten_fields", "stamp_affected_fields", "handwriting_and_stamp",
                          "handwriting_without_stamp", "stamp_without_handwriting", "neither_labeled_flag"):
                selected = [r for r in candidate if in_field_scope(r, field, scope)]
                selected_ids = {r["document_id"] for r in selected}
                if not selected:
                    strata.append(dict(model=name, field=field, scope=scope, documents=0,
                                       note="No labeled cases; not fully evaluated"))
                    continue
                old = metrics_from_scored_cells([r for r in baseline_cells if r["field_name"] == field and r["document_id"] in selected_ids])
                new = metrics_from_scored_cells([r for r in candidate_cells if r["field_name"] == field and r["document_id"] in selected_ids])
                field_metric = {}
                for key in old:
                    field_metric.update({key + "_before": old[key], key + "_after": new[key],
                        key + "_delta": new[key] - old[key] if new[key] is not None and old[key] is not None else None})
                strata.append(dict(model=name, field=field, scope=scope, documents=len(selected),
                    **{k: v for k, v in field_metric.items() if k != "field"},
                    note="KIE field metadata stratification, NOT line-level recognition CER"))
    if metrics:
        write_csv(output / "experiment_log.csv", metrics, list(metrics[0]))
    if resources:
        write_csv(output / "resource_comparison.csv", resources, list(resources[0]))
    sample_columns = ["model", "document_id", "field", "before", "after", "gt", "old_bucket", "new_bucket", "transition_kind",
                      "baseline_diagnostic", "candidate_diagnostic", "review_status"]
    write_csv(output / "all_changes.csv", samples, sample_columns)
    for kind in ("regression", "improvement"):
        write_csv(output / f"sample_{kind}s.csv", [r for r in samples if r["transition_kind"] == kind], sample_columns)
    dump(output / "field_metadata_strata.json", strata)
    dump(output / "manifest.json", dict(status="completed", mode="hybrid_recognizer_comparison", control=str(control),
        candidates=[str(p.resolve()) for p in args.candidate], metric_version=b.METRIC_VERSION,
        review_note="All changed fields pending visual review. No transcription gold, so no recognition CER/WER."))


if __name__ == "__main__":
    main()
