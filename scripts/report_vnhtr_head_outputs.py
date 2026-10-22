"""Saved output differences for four separately trained VNHTR checkpoint cases."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.report_vietdoc_checkpoint_parity import crop_texts, predictions, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    artifacts = ROOT / "ocr-collab/artifacts"
    rows, crop_changes, field_changes = [], [], []
    for family in ("vgg", "trocr"):
        head = artifacts / "recognizer_ab_candidates_20261021" / f"vnhtr_{family}"
        base = artifacts / "recognizer_ab_candidates_extended_20261021" / f"vnhtr_{family}_base"
        for folder in (head, base):
            manifest = read(folder / "manifest.json")
            if manifest.get("status") != "completed" or len(manifest["documents"]) != 100:
                raise ValueError("Both checkpoint cases must be completed")
        if read(head / "run_fingerprint.json")["cache_manifest_sha256"] != read(base / "run_fingerprint.json")["cache_manifest_sha256"]:
            raise ValueError("Parent inputs differ")
        a, z = crop_texts(base), crop_texts(head)
        if set(a) != set(z):
            raise ValueError("Crop identities differ")
        changes = [dict(family=family, document_id=doc, physical_page=page, crop_index=index,
                        no_head_text=a[doc, page, index], with_head_text=z[doc, page, index])
                   for doc, page, index in a if a[doc, page, index] != z[doc, page, index]]
        crop_changes.extend(changes)
        before, after = predictions(base), predictions(head)
        fields = [dict(family=family, document_id=doc, field=field, no_head=before[doc][field], with_head=after[doc].get(field))
                  for doc in before for field in before[doc] if field != "receiverDate" and before[doc][field] != after[doc].get(field)]
        field_changes.extend(fields)
        rows.append(dict(family=family, documents=100, parent_crops=6619, changed_raw_crop_texts=len(changes),
                         exact_raw_crop_texts=6619-len(changes), changed_api_values=len(fields),
                         documents_with_changed_api_values=len({row["document_id"] for row in fields}),
                         changed_api_values_by_field={field: sum(row["field"] == field for row in fields) for field in {row["field"] for row in fields}}))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "comparison.json").write_text(json.dumps(dict(status="completed", families=rows,
        scope="Different trained checkpoint variants, not a causal head toggle on identical weights; changed strings are not necessarily improvements"), indent=2) + "\n")
    for name, values, columns in (("changed_crop_texts.csv", crop_changes, ["family", "document_id", "physical_page", "crop_index", "no_head_text", "with_head_text"]),
                                   ("changed_api_values.csv", field_changes, ["family", "document_id", "field", "no_head", "with_head"])):
        with (args.output / name).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(values)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
