"""Compare downloaded weight bytes and saved OCR/KIE outputs; no new inference."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ocr-collab/artifacts"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def crop_texts(folder):
    results = {}
    for path in sorted((folder / "cache").glob("*/page_*/results.json")):
        doc, page = path.parent.parent.name, path.parent.name
        for row in read(path)["recognition"]:
            key = doc, page, row["crop_index"]
            if key in results:
                raise ValueError("Duplicate crop identity")
            results[key] = row["text"]
    if len(results) != 6619:
        raise ValueError(f"Incomplete crop coverage: {folder}")
    return results


def predictions(folder):
    rows = [json.loads(line) for line in (folder / "candidate_predictions.jsonl").read_text().splitlines() if line.strip()]
    if len(rows) != 100 or len({row["document_id"] for row in rows}) != 100:
        raise ValueError("Incomplete/duplicate document coverage")
    return {row["document_id"]: row["prediction"] for row in rows}


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--before", type=Path, default=ARTIFACTS / "recognizer_ab_20261015/vietocr_handwriting")
    parser.add_argument("--after", type=Path, default=ARTIFACTS / "recognizer_ab_candidates_20261021/vietdoc_vudang_pth")
    args = parser.parse_args()
    models = ROOT / "scratch/ocr-recognizers/models"
    probe = ROOT / "scratch/ocr-recognizers/sources/vietdoc_download_probe_26f9cfa/models"
    base_original, base_vietdoc = digest(models / "vietocr_original_transformer/weights.pth"), digest(probe / "base/model.pth")
    hand_original, hand_vietdoc = digest(models / "vietocr_handwriting/best_ep11.pth"), digest(probe / "handwriting/model.pth")
    if base_original != base_vietdoc or hand_original != hand_vietdoc:
        raise ValueError("VietDoc downloaded weights do not match the original checkpoints")
    old, new = args.before.resolve(), args.after.resolve()
    fingerprints = [read(folder / "run_fingerprint.json") for folder in (old, new)]
    if fingerprints[0]["cache_manifest_sha256"] != fingerprints[1]["cache_manifest_sha256"]:
        raise ValueError("Raw output parity requires the identical parent-crop cache")
    texts_before, texts_after = crop_texts(old), crop_texts(new)
    if set(texts_before) != set(texts_after):
        raise ValueError("Different crop identities")
    crop_changes = [dict(document_id=doc, physical_page=page, crop_index=index,
                         original_onnx_text=texts_before[doc, page, index], vietdoc_checkpoint_pytorch_text=texts_after[doc, page, index])
                    for doc, page, index in texts_before if texts_before[doc, page, index] != texts_after[doc, page, index]]
    before, after = predictions(old), predictions(new)
    if set(before) != set(after):
        raise ValueError("Different document identities")
    field_changes = []
    counts = {}
    for doc in before:
        for field in before[doc]:
            if field == "receiverDate":
                continue
            if before[doc].get(field) != after[doc].get(field):
                field_changes.append(dict(document_id=doc, field=field, original_onnx=before[doc].get(field),
                                          vietdoc_checkpoint_pytorch=after[doc].get(field)))
                counts[field] = counts.get(field, 0) + 1
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    base_details = dict(weight_bytes_identical=True, sha256=base_original,
        original_artifact="recognizer_ab_additional_20261015/vietocr_original_transformer",
        separate_vietdoc_config_inference="approved_not_yet_completed", result_parity="not established by weight equality",
        config_difference="VietDoc max width 1024 and upstream max_seq_length 256 versus original width 512 and limit 128")
    base_before = ARTIFACTS / "recognizer_ab_additional_20261015/vietocr_original_transformer"
    base_after = ARTIFACTS / "recognizer_ab_candidates_vietdoc_base_20261021/vietdoc_base_pth"
    if (base_after / "manifest.json").exists() and read(base_after / "manifest.json").get("status") == "completed":
        if read(base_before / "run_fingerprint.json")["cache_manifest_sha256"] != read(base_after / "run_fingerprint.json")["cache_manifest_sha256"]:
            raise ValueError("Base config comparison needs identical parent crops")
        base_text_before, base_text_after = crop_texts(base_before), crop_texts(base_after)
        if set(base_text_before) != set(base_text_after):
            raise ValueError("Different base crop identities")
        base_crop_changes = [dict(document_id=doc, physical_page=page, crop_index=index,
                                 upstream_config_text=base_text_before[doc, page, index], vietdoc_config_text=base_text_after[doc, page, index])
                             for doc, page, index in base_text_before if base_text_before[doc, page, index] != base_text_after[doc, page, index]]
        a, z = predictions(base_before), predictions(base_after)
        base_fields = [dict(document_id=doc, field=field, upstream_config=a[doc].get(field), vietdoc_config=z[doc].get(field))
                       for doc in a for field in a[doc] if field != "receiverDate" and a[doc].get(field) != z[doc].get(field)]
        base_details.update(separate_vietdoc_config_inference="completed", result_parity="measured_saved_outputs",
            compared_crops=6619, exact_raw_crop_texts=6619-len(base_crop_changes), changed_raw_crop_texts=len(base_crop_changes),
            changed_api_values=len(base_fields), documents_with_changed_api_values=len({row["document_id"] for row in base_fields}),
            changed_values_by_field={field: sum(row["field"] == field for row in base_fields) for field in {row["field"] for row in base_fields}},
            compared_vietdoc_config_artifact=str(base_after), note="Same pinned upstream decoder implementation; supplied resize/limit config differs, not newly trained weights")
        write_csv(output / "base_changed_crop_texts.csv", base_crop_changes, ["document_id", "physical_page", "crop_index", "upstream_config_text", "vietdoc_config_text"])
        write_csv(output / "base_changed_api_values.csv", base_fields, ["document_id", "field", "upstream_config", "vietdoc_config"])
    summary = dict(status="completed", mode="read_only_saved_output_and_weight_parity", no_inference_performed=True,
        base=base_details,
        handwriting=dict(weight_pth_bytes_identical=True, sha256=hand_original,
            compared_onnx_artifact=str(old), compared_pytorch_artifact=str(new),
            original_source_pth="vudang449/vietocr-vietnamese-handwriting@f1973b930f907c378f6e3152ce9d8658724b228a/best_ep11.pth",
            original_test_runtime="published ONNX encoder/decoder FP16", new_test_runtime="pinned upstream VietOCR PyTorch FP32, supplied VietDoc config",
            compared_crops=6619, exact_raw_crop_texts=6619 - len(crop_changes), changed_raw_crop_texts=len(crop_changes),
            documents_with_changed_api_values=len({row["document_id"] for row in field_changes}),
            changed_api_values=len(field_changes), changed_values_by_field=counts,
            numerical_pth_to_onnx_weight_parity_proven=False,
            attribution_limit="Resize/interpolation/width policy, precision, decoding and batching differ. Different outputs do not prove differently fine-tuned weights. This is not the native VietDoc decoder."))
    repeats = {}
    for runtime, historical, current, current_texts, current_predictions in (
        ("onnx", ARTIFACTS / "recognizer_ab_20261015/vietocr_handwriting", old, texts_before, before),
        ("pytorch", ARTIFACTS / "recognizer_ab_candidates_20261021/vietdoc_vudang_pth", new, texts_after, after),
    ):
        if historical.resolve() == current.resolve():
            repeats[runtime] = dict(status="no_independent_retest_supplied")
            continue
        previous_texts, previous_predictions = crop_texts(historical), predictions(historical)
        if set(previous_texts) != set(current_texts) or set(previous_predictions) != set(current_predictions):
            raise ValueError("Repeat comparison identities differ")
        repeats[runtime] = dict(status="independent_retest_compared", historical_artifact=str(historical), current_artifact=str(current),
            exact_crop_texts=sum(previous_texts[key] == current_texts[key] for key in previous_texts), compared_crops=6619,
            exact_document_predictions=sum(previous_predictions[key] == current_predictions[key] for key in previous_predictions), compared_documents=100)
    summary["repeat_consistency"] = repeats
    (output / "parity.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    write_csv(output / "changed_crop_texts.csv", crop_changes, ["document_id", "physical_page", "crop_index", "original_onnx_text", "vietdoc_checkpoint_pytorch_text"])
    write_csv(output / "changed_api_values.csv", field_changes, ["document_id", "field", "original_onnx", "vietdoc_checkpoint_pytorch"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
