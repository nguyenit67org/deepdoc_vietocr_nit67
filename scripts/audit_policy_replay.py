"""Diagnostic extraction replay, not full inference or a new evidence bundle.

First checks exact reproduction with the source's saved rules, then reports
candidate changes using the same OCR and current GT. Original traces remain
source evidence, never falsely relabelled as candidate extraction traces.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ocr-collab"))
sys.path.insert(0, str(ROOT / "ocr-collab" / "experiments"))
import benchmark as b
from replay_all_v3 import load_rules, _original_page_sizes, _trace_pages_for_extractor
from compute_comparisons import transition_rows, CHANGE_COLUMNS
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    saved = load_rules(args.source / "source_snapshot/module__extract__vbhc_rules.py")
    current = load_rules(ROOT / "module/extract/vbhc_rules.py")
    gt = {c.document_id: c.ground_truth for c in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    before, after, changes = [], [], []
    for line in (args.source / "predictions.jsonl").read_text().splitlines():
        record = json.loads(line)
        trace = json.loads(Path(record["trace_path"]).read_text())
        raw = json.loads((args.source / "pipeline_outputs" / record["document_id"] / "output.json").read_text())
        pages = _trace_pages_for_extractor(trace)
        sizes = _original_page_sizes(Path(record["pdf_path"]), len(pages))
        processed = [(p["width"], p["height"]) for p in trace["pages"]]
        offsets = [p["crop_offset"] for p in raw["pages"]]
        results = []
        for rules in (saved, current):
            result, debug = rules.extract_vbhc(pages, sizes, processed, offsets,
                geometry_reliable=trace["extraction"]["geometry_reliable"])
            results.append(({f: d["value"] for f, d in result["information"][0].items()
                             if f in record["prediction"]}, debug))
        if results[0][0] != record["prediction"]:
            raise ValueError(f"Source replay not equivalent: {record['document_id']}")
        record["ground_truth"] = gt[record["document_id"]]
        before.append(record)
        candidate = copy.deepcopy(record)
        candidate["prediction"] = results[1][0]
        candidate["field_evidence"] = results[1][1]["evidence"]
        after.append(candidate)
        for f, value in candidate["prediction"].items():
            if value != record["prediction"][f]:
                changes.append(dict(document_id=record["document_id"], field=f,
                    before=record["prediction"][f], after=value, gt=gt[record["document_id"]][f],
                    source_trace=record["trace_path"], proposed_evidence=results[1][1]["evidence"][f]))
    merged, old, new, regressions, improvements, unresolved = transition_rows(before, after, "all", "diagnostic_replay")
    old.merge(new, on="field_name", suffixes=("_before", "_after")).to_csv(args.output / "metrics.csv", index=False)
    for name, rows in (("regressions", regressions), ("improvements", improvements), ("other_changes", unresolved)):
        pd.DataFrame(rows, columns=CHANGE_COLUMNS).to_csv(args.output / (name + ".csv"), index=False)
    (args.output / "changes.json").write_text(json.dumps(changes, ensure_ascii=False, indent=2) + "\n")
    for old_row, new_row in zip(old.to_dict("records"), new.to_dict("records")):
        print(old_row["field_name"], "F1", old_row["f1"], "->", new_row["f1"], "NEM", old_row["nem"], "->", new_row["nem"])
    metric_drops = []
    for old_row, new_row in zip(old.to_dict("records"), new.to_dict("records")):
        for metric in ("f1", "precision", "recall", "nem", "vai_acc", "hallucination_rate"):
            a, z = old_row.get(metric), new_row.get(metric)
            if isinstance(a, (int, float)) and isinstance(z, (int, float)):
                worse = z > a if metric == "hallucination_rate" else z < a
                if worse:
                    metric_drops.append(dict(field=old_row["field_name"], metric=metric, before=a, after=z))
    document_success = {}
    for label, records in (("before", before), ("after", after)):
        errors, _ = b.evaluate_records(records)
        _, document_success[label] = b.summarize_document_success(errors)
    (args.output / "summary.json").write_text(json.dumps({
        "mode": "diagnostic_extraction_replay", "source": str(args.source.resolve()),
        "source_replay_equivalent": True, "documents": len(before), "metric_version": b.METRIC_VERSION,
        "ground_truth": "Both sides evaluated with the same current GT loaded at replay start",
        "regressions": len(regressions), "improvements": len(improvements),
        "other_error_changes": len(unresolved), "metric_decreases": metric_drops,
        "document_success": document_success,
        "full_inference": False,
        "note": "Proposed evidence is in changes.json; source_trace links refer to unchanged source extraction, not new traces.",
    }, ensure_ascii=False, indent=2) + "\n")
    print("Regression cells:", len(regressions), "improvements:", len(improvements), "other:", len(unresolved))
    print("Equivalent source replay verified for", len(before), "documents.")
    if regressions or metric_drops:
        raise SystemExit("Replay regression gate failed; review before full inference")


if __name__ == "__main__":
    main()
