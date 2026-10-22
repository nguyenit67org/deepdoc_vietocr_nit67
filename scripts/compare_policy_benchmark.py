"""Compare full inference bundles with one current GT snapshot, never stored GT."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ocr-collab"))
sys.path.insert(0, str(ROOT / "ocr-collab" / "experiments"))

import benchmark as b
import compute_comparisons as comparisons
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    gt = {case.document_id: case.ground_truth for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    records = []
    for bundle in (args.baseline, args.candidate):
        rows = comparisons.load_records(bundle)
        comparisons.validate_candidate_artifacts(rows, bundle)
        refreshed, _ = comparisons.rescore_current_gt(rows, gt)
        records.append(refreshed)
    manifests = [json.loads((p / "manifest.json").read_text()) for p in (args.baseline, args.candidate)]
    pdfs = [{row["document_id"]: row["pdf_sha256"] for row in m["documents"]} for m in manifests]
    if pdfs[0] != pdfs[1]:
        raise ValueError("PDF sets/hashes differ; refusing direct comparison")
    merged, before, after, regressions, improvements, unresolved = comparisons.transition_rows(
        *records, "all", "latest_full_vs_policy"
    )
    metrics = before.merge(after, on="field_name", suffixes=("_baseline", "_candidate"), validate="one_to_one")
    for key in ("f1", "precision", "recall", "nem", "hallucination_rate", "vai_acc"):
        if key + "_candidate" in metrics:
            metrics[key + "_delta"] = metrics[key + "_candidate"] - metrics[key + "_baseline"]
    metrics.to_csv(args.output / "field_metrics_comparison.csv", index=False)
    for name, rows in (("sample_regressions", regressions), ("sample_improvements", improvements), ("error_bucket_changes", unresolved)):
        pd.DataFrame(rows, columns=comparisons.CHANGE_COLUMNS).to_csv(args.output / (name + ".csv"), index=False)
    matrix = pd.crosstab(
        [merged.field_name_baseline, merged.error_bucket_baseline], merged.error_bucket_candidate
    ).reindex(
        index=pd.MultiIndex.from_product(
            [before.field_name, comparisons.BUCKETS], names=["field_name", "baseline_bucket"]
        ), columns=comparisons.BUCKETS, fill_value=0,
    )
    matrix.to_csv(args.output / "bucket_transitions.csv")
    success = {}
    for name, rows in zip(("baseline", "candidate"), records):
        errors, _ = b.evaluate_records(rows)
        documents, summary = b.summarize_document_success(errors)
        pd.DataFrame(documents).to_csv(args.output / f"document_success_{name}.csv", index=False)
        success[name] = summary
    (args.output / "comparison_summary.json").write_text(json.dumps({
        "baseline": str(args.baseline.resolve()), "candidate": str(args.candidate.resolve()),
        "document_count": len(records[0]), "metric_version": b.METRIC_VERSION,
        "ground_truth": "Both sides rescored against the same current GT loaded for this comparison",
        "pdf_hashes_verified": True, "document_success": success,
        "regressions": len(regressions), "improvements": len(improvements),
        "other_error_bucket_changes": len(unresolved),
        "visual_review": "Sample causes require separate visual review",
    }, ensure_ascii=False, indent=2) + "\n")
    print(metrics[["field_name", "f1_baseline", "f1_candidate", "f1_delta", "nem_delta"]].to_string(index=False))
    print(f"Regressions: {len(regressions)}; improvements: {len(improvements)}; other error changes: {len(unresolved)}")
    print("Sample causes require visual review; no cause is inferred from buckets.")


if __name__ == "__main__":
    main()
