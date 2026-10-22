"""Offline TrOCR segmentation/recognition audit; never loads or runs an OCR model."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import sha256

EXPERIMENT = ROOT / "ocr-collab/artifacts/recognizer_ab_trocr_20261015"
CACHE = ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015/cache"
RUNS = ("fastocr_control", "fastocr_words", "trocr_words")


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def csv_write(path, rows):
    with Path(path).open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_page_records(run):
    rows = {}
    for page in sorted((EXPERIMENT / run / "cache").glob("*/page_*/results.json")):
        data = read(page)
        details = data["recognition_details"]
        if details and len(details) != len(data["recognition"]):
            raise ValueError("Detail/recognition cardinality mismatch")
        for index, recognition in enumerate(data["recognition"]):
            key = (page.parent.parent.name, int(page.parent.name[5:])-1, recognition["crop_index"])
            if key in rows:
                raise ValueError("Duplicate crop identity")
            rows[key] = dict(recognition=recognition, detail=details[index] if details else None)
    return rows


def geometry_flags(shape, boxes):
    height, width = shape[:2]
    ratios = [(box[2]-box[0]) / (box[3]-box[1]) for box in boxes]
    return dict(parent_aspect_ratio=width/height, segments=len(boxes),
        vertical_parent=height > width, max_segment_aspect=max(ratios, default=0),
        wide_segments=sum(ratio > 5 for ratio in ratios),
        narrow_segments=sum(ratio < .35 for ratio in ratios),
        single_wide_segment=len(boxes) == 1 and width/height > 5)


def select_cases(parents):
    """Deterministic risk-stratified examples, NOT an unbiased error-rate sample."""
    selected, seen = [], set()
    def take(label, candidates, count):
        docs = Counter(case["document_id"] for case in selected)
        for row in candidates:
            key = row["document_id"], row["page_index_0based"], row["crop_index"]
            if key in seen or docs[row["document_id"]] >= 3:
                continue
            selected.append({**row, "selection_stratum": label})
            seen.add(key)
            docs[row["document_id"]] += 1
            count -= 1
            if count == 0:
                break
    take("single_wide_risk", sorted([r for r in parents if r["single_wide_segment"]], key=lambda r: -r["parent_aspect_ratio"]), 4)
    take("wide_segment_risk", sorted([r for r in parents if r["segments"] >= 2 and r["wide_segments"]], key=lambda r: -r["max_segment_aspect"]), 4)
    take("narrow_fragment_risk", sorted([r for r in parents if r["narrow_segments"] >= 2], key=lambda r: -r["narrow_segments"]), 4)
    take("regular_geometry_disagreement", [r for r in parents if 3 <= r["segments"] <= 12 and r["max_segment_aspect"] < 4
        and not r["vertical_parent"] and r["trocr_text"] != r["fastocr_word_text"]], 6)
    take("vertical_input", [r for r in parents if r["vertical_parent"]], 3)
    take("empty_output_or_blank", [r for r in parents if not r["trocr_text"].strip() or r["blank"]], 2)
    # Explicit visual-review examples only; these identities never affect inference.
    for document, page, index, label in (
        ("07+QĐ-NHNN_2025-01-03", 0, 7, "handwritten_code_candidate"),
        ("07+QĐ-NHNN_2025-01-03", 0, 3, "printed_header_control"),
        ("07+QĐ-NHNN_2025-01-03", 0, 8, "handwritten_date_candidate"),
        ("155+2020+NĐ-CP_2020-12-31", 0, 3, "handwritten_code_candidate"),
        ("155+2020+NĐ-CP_2020-12-31", 253, 19, "stamped_signer_candidate"),
        ("155+2020+NĐ-CP_2020-12-31", 253, 6, "printed_signature_title_control"),
        ("1671+QĐ-TTg_2026-08-28", 27, 4, "mixed_merge_printed_control"),
    ):
        take(label,[r for r in parents if (r["document_id"],r["page_index_0based"],r["crop_index"]) == (document,page,index)],1)
    take("coverage_fill", parents, 30-len(selected)) if len(selected) < 30 else None
    if len(selected) != 30:
        raise ValueError(f"Expected 30 unique visual samples, found {len(selected)}")
    return [{**row, "case_id": f"case_{i:02d}"} for i, row in enumerate(selected)]


def font(size):
    from PIL import ImageFont
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


def render_case(case, original, fast_words, trocr, output):
    from PIL import Image, ImageDraw
    import numpy as np
    image = Image.open(case["parent_path"]).convert("RGB")
    metadata = trocr["detail"]["metadata"]
    marked = image.copy()
    painter = ImageDraw.Draw(marked)
    for index, box in enumerate(metadata["boxes"]):
        painter.rectangle((box[0], box[1], box[2]-1, box[3]-1), outline="#d12a2a", width=1)
    scale = min(2.0, 1840/image.width, 140/image.height)
    marked = marked.resize((max(1, round(image.width*scale)), max(1, round(image.height*scale))))
    lines = []
    for title, value in (("A FastOCR line", case["fastocr_line_text"]), ("B FastOCR same words", case["fastocr_word_text"]), ("C TrOCR", case["trocr_text"])):
        lines.extend(textwrap.wrap(title + ": " + value, 160) or [title + ": [empty]"])
    header_height = 80 + marked.height + len(lines)*24
    row_count = math.ceil(max(1, len(metadata["boxes"])) / 6)
    canvas = Image.new("RGB", (1900, header_height+row_count*250+30), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((15, 8), case["case_id"] + " | " + case["selection_stratum"], font=font(23), fill="black")
    draw.text((15, 39), f"{case['document_id']} | physical page {case['page_index_0based']+1}, crop {case['crop_index']}, segments {case['segments']}", font=font(18), fill="black")
    canvas.paste(marked, (15, 72))
    y = marked.height+82
    for line in lines:
        draw.text((15, y), line, font=font(19), fill="black")
        y += 24
    for index, (box, native, control) in enumerate(zip(metadata["boxes"], metadata["words_raw"], fast_words["detail"]["metadata"]["words_raw"])):
        word = image.crop(box)
        expected = metadata["words"][index]["rgb_sha256"]
        if hashlib.sha256(np.asarray(word).tobytes()).hexdigest() != expected:
            raise ValueError("Selected visual word crop hash mismatch")
        x, y = 15+(index % 6)*310, header_height+(index//6)*250
        word.thumbnail((295, 100))
        canvas.paste(word, (x, y+23))
        draw.text((x, y), f"word {index} | {box[2]-box[0]}x{box[3]-box[1]}", font=font(15), fill="black")
        for label, value, delta in (("B: ", control["raw_text"], 128), ("C: ", native["raw_text"], 184)):
            wrapped = textwrap.wrap(label+value, 30)
            shown = wrapped[:2]
            if len(wrapped) > 2:
                shown[-1] = shown[-1][:26] + "..."
            draw.multiline_text((x, y+delta), "\n".join(shown), font=font(17), fill="black")
    canvas.save(output)


def prepare(output):
    import benchmark as b
    current = {case.document_id: case for case in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    labels, fingerprint_inputs = None, None
    protected = []
    field_metrics, results = [], {}
    for run in RUNS:
        folder = EXPERIMENT / run
        manifest, fingerprint = read(folder/"manifest.json"), read(folder/"run_fingerprint.json")
        if manifest["status"] != "completed" or manifest["metric_version"] != b.METRIC_VERSION:
            raise ValueError("Incomplete/incompatible run")
        inputs = {k:fingerprint[k] for k in ("labels", "baseline_sha256", "baseline_predictions_sha256", "config_sha256", "cache_manifest_sha256")}
        if fingerprint_inputs is None:
            fingerprint_inputs = inputs
            labels = inputs["labels"]
            if any(sha256(current[name].json_path) != digest for name,digest in labels.items()):
                raise ValueError("Current GT changed; explicit rescore needed, not a mixed comparison")
            protected.extend(dict(path=str(current[name].json_path),sha256=digest) for name,digest in labels.items())
        if inputs != fingerprint_inputs:
            raise ValueError("Source/GT/crop provenance mismatch")
        for file in ("manifest.json", "run_fingerprint.json", "candidate_predictions.jsonl", "recognizer_config.json"):
            path = folder/file
            protected.append(dict(path=str(path), sha256=sha256(path)))
        protected.extend(dict(path=str(path),sha256=sha256(path)) for path in sorted((folder/"cache").glob("*/page_*/results.json")))
        with (folder/"evaluation/candidate/metrics.csv").open() as handle:
            field_metrics.extend(dict(model=run, **row) for row in csv.DictReader(handle))
        results[run] = load_page_records(run)
    if any(set(results[run]) != set(results[RUNS[0]]) for run in RUNS) or len(results[RUNS[0]]) != 6619:
        raise ValueError("Parent coverage differs")
    mapping_path = EXPERIMENT/"word_crop_cache_manifest.json"
    mapping = read(mapping_path)
    protected.append(dict(path=str(mapping_path),sha256=sha256(mapping_path)))
    parent_rows, word_rows = [], []
    for source in mapping["parents"]:
        key = source["document_id"], source["physical_page_index_0based"], source["detection_index"]
        a, control, candidate = [results[run][key] for run in RUNS]
        bm, cm = control["detail"]["metadata"], candidate["detail"]["metadata"]
        for prop in ("parent_rgb_sha256", "cache_key", "policy", "shape", "boxes", "words"):
            if source[prop] != cm[prop] or bm[prop] != cm[prop]:
                raise ValueError(f"Word input mismatch {key}: {prop}")
        if len(cm["boxes"]) != len(cm["words_raw"]) or len(cm["boxes"]) != len(bm["words_raw"]):
            raise ValueError("Word output cardinality mismatch")
        parent_path = CACHE/key[0]/f"page_{key[1]+1}"/"crops"/f"{key[2]}.png"
        row = dict(document_id=key[0], page_index_0based=key[1], crop_index=key[2],
            parent_path=str(parent_path), cache_key=cm["cache_key"], height=cm["shape"][0], width=cm["shape"][1],
            blank=cm["blank"], **geometry_flags(cm["shape"],cm["boxes"]),
            fastocr_line_text=a["recognition"]["text"], fastocr_word_text=control["recognition"]["text"],
            trocr_text=candidate["recognition"]["text"], parent_truncated=candidate["detail"]["truncated"])
        parent_rows.append(row)
        for index,(box, native, baseline) in enumerate(zip(cm["boxes"],cm["words_raw"],bm["words_raw"])):
            ids = native.get("token_ids",[])
            word_rows.append(dict(document_id=key[0], page_index_0based=key[1], crop_index=key[2], word_index=index,
                width=box[2]-box[0], height=box[3]-box[1], aspect_ratio=(box[2]-box[0])/(box[3]-box[1]),
                fastocr_text=baseline["raw_text"], trocr_text=native["raw_text"],
                exact_decoder_agreement=baseline["raw_text"] == native["raw_text"],
                trocr_truncated=native["truncated"], starts_with_token=ids[0] if ids else None,
                second_token=ids[1] if len(ids)>1 else None, generated_nonpad_tokens=sum(t!=1 for t in ids[1:]),
                output_contains_whitespace=any(c.isspace() for c in native["raw_text"].strip())))
    parent_rows.sort(key=lambda row:(row["document_id"],row["page_index_0based"],row["crop_index"]))
    csv_write(output/"parent_crop_diagnostics.csv",parent_rows)
    csv_write(output/"word_diagnostics.csv",word_rows)
    csv_write(output/"field_metrics.csv",field_metrics)
    selected=select_cases(parent_rows)
    write(output/"selected_cases.json",selected)
    evidence=output/"evidence"
    evidence.mkdir()
    for case in selected:
        key=case["document_id"],case["page_index_0based"],case["crop_index"]
        render_case(case,*[results[run][key] for run in RUNS],evidence/f"{case['case_id']}.png")
    summary=dict(parent_crops=len(parent_rows),segments=len(word_rows),blank_parents=sum(r["blank"] for r in parent_rows),
        vertical_parents=sum(r["vertical_parent"] for r in parent_rows),single_wide_parents=sum(r["single_wide_segment"] for r in parent_rows),
        parents_with_wide_segment=sum(r["wide_segments"]>0 for r in parent_rows),
        parents_with_narrow_fragment=sum(r["narrow_segments"]>0 for r in parent_rows),
        wide_segments=sum(r["aspect_ratio"]>5 for r in word_rows),narrow_segments=sum(r["aspect_ratio"]<.35 for r in word_rows),
        same_word_decoder_agreements=sum(r["exact_decoder_agreement"] for r in word_rows),
        empty_trocr_segments=sum(not r["trocr_text"].strip() for r in word_rows),
        truncated_trocr_segments=sum(r["trocr_truncated"] for r in word_rows),
        output_multi_token_segments=sum(r["output_contains_whitespace"] for r in word_rows),
        first_token_counts=dict(Counter(r["starts_with_token"] for r in word_rows)),
        second_token_counts=dict(Counter(r["second_token"] for r in word_rows)),
        input_parity_verified=True,selected_visual_cases=len(selected),visual_review="pending",
        note="Geometry thresholds are risk flags, not visually confirmed word segmentation errors. Decoder agreement is not accuracy.")
    summary["runs"]={run:dict(document_success=read(EXPERIMENT/run/"evaluation/candidate/summary.json")["document_success_at_5"],
        config=read(EXPERIMENT/run/"recognizer_config.json")) for run in RUNS}
    write(output/"summary.json",summary)
    write(output/"input_integrity_before.json",protected)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/"summary.json").exists():
        raise FileExistsError("Use a fresh analysis directory; existing analysis preserved")
    prepare(args.output.resolve())


if __name__=="__main__":
    main()
