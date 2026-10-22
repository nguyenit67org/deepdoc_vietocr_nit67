"""Check boundary-page cached OCR against a saved full-inference run.

This is a hybrid diagnostic, not full inference: non-selected pages retain
source OCR. A saved-OCR reassembly control separates cache/geometry effects
from re-detection/recognition effects. Labels select pages and score outputs;
their field values are never supplied to OCR or extraction.
"""
import argparse
import copy
import csv
from collections import Counter
import importlib.metadata
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ocr-collab"))
sys.path.insert(0, str(ROOT / "ocr-collab/experiments"))


def selected_pages(metadata, page_count):
    start = metadata["document_start_page"]["value"]
    ends = metadata["document_end_pages"]["value"]
    if not isinstance(ends, list) or not ends:
        raise ValueError("document_end_pages must be a non-empty list")
    values = [start, *ends]
    if any(type(p) is not int or not 0 <= p < page_count for p in values):
        raise ValueError("Page metadata must contain valid physical 0-based indices")
    return sorted(set(values))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows, columns):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path, records):
    temporary = Path(str(path) + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def validate_source(source):
    conf = json.loads((source / "pipeline_config.json").read_text())
    if conf.get("table", {}).get("enabled", True) or conf.get("corrector", {}).get("enabled", False):
        raise ValueError("Equivalence harness requires source table/corrector disabled")
    for key in ("page_orientation", "page_deskew", "remove_red"):
        if conf.get(key, {}).get("enabled"):
            raise ValueError(f"Source {key} needs a separate cache protocol")
    hashes = {}
    for snapshot in sorted((source / "source_snapshot").iterdir()):
        relative = snapshot.name.replace("__", "/")
        current = ROOT / relative
        if not current.is_file() or sha256(current) != sha256(snapshot):
            raise ValueError(f"Current code/config differs from source: {relative}")
        hashes[relative] = sha256(current)
    if not hashes:
        raise ValueError("Missing source snapshot")
    return conf, hashes


def diagnostic_record(record, prediction, evidence, diagnostic_path):
    # Source traces/resources describe full inference, never this hybrid run.
    from replay_all_v3 import RESOURCE_NULL_KEYS
    result = {**record, "prediction": prediction, "field_evidence": evidence,
              "trace_path": None, "source_trace_path": record["trace_path"],
              "diagnostic_path": str(diagnostic_path), "resource_timeline": None,
              "generation_mode": "hybrid_boundary_page_ocr_equivalence"}
    for key in RESOURCE_NULL_KEYS:
        result[key] = None
    return result


def flat_prediction(result, fields):
    return {f: result["information"][0][f]["value"] for f in fields}


def line_comparison(saved, fresh):
    """Compare retained lines, not original pre-filter baseline detections."""
    def key(line):
        return tuple(round(float(v), 1) for point in line["quad"] for v in point)
    old, new = Counter(key(x) for x in saved), Counter(key(x) for x in fresh)
    old_pairs = Counter((key(x), x["text"]) for x in saved)
    new_pairs = Counter((key(x), x["text"]) for x in fresh)
    return dict(saved_retained_lines=len(saved), fresh_retained_lines=len(fresh),
        common_rounded_quads=sum((old & new).values()),
        saved_only_rounded_quads=sum((old - new).values()),
        fresh_only_rounded_quads=sum((new - old).values()),
        common_quad_text_pairs=sum((old_pairs & new_pairs).values()),
        ordered_quad_text_equal=[(key(x), x["text"]) for x in saved] == [(key(x), x["text"]) for x in fresh])


def load_cached_page(page_dir, expected):
    """Load exact BGR crop arrays, never detect, crop, or recognize here."""
    import cv2
    import numpy as np
    from module.pipeline.ocr_page import PageOcrPrep

    data = json.loads((page_dir / "input.json").read_text())
    for key, value in expected.items():
        if data.get(key) != value:
            raise ValueError(f"Cache geometry/identity mismatch: {page_dir}, {key}")
    indices, excluded = data["crop_indices"], data["excluded_indices"]
    quads = np.asarray(data["detection_quads"], dtype=float)
    all_indices = indices + excluded
    if (any(type(i) is not int for i in all_indices) or len(set(all_indices)) != len(all_indices)
            or set(all_indices) != set(range(len(quads)))):
        raise ValueError(f"Invalid cached detection-index partition: {page_dir}")
    if len(quads) and (quads.shape != (len(quads), 4, 2) or not np.isfinite(quads).all()):
        raise ValueError(f"Invalid detection quads: {page_dir}")
    entries = json.loads((page_dir / "crop_manifest.json").read_text())
    if [e["detection_index"] for e in entries] != indices:
        raise ValueError(f"Cache crop order/index mismatch: {page_dir}")
    crops = []
    for entry in entries:
        path = (page_dir / entry["path"]).resolve()
        if not path.is_relative_to(page_dir.resolve()):
            raise ValueError(f"Crop path escapes page cache: {path}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Crop file hash mismatch: {path}")
        crop = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if (crop is None or list(crop.shape) != entry["shape_bgr"]
                or hashlib.sha256(crop.tobytes()).hexdigest() != entry["array_sha256"]):
            raise ValueError(f"Decoded BGR crop mismatch: {path}")
        crops.append(crop)
    return PageOcrPrep(dt_boxes=quads, crop_indices=indices, excluded_indices=set(excluded)), crops, data


def compare(before, after):
    import benchmark as b
    old_errors, old_metrics = b.evaluate_records(before)
    new_errors, new_metrics = b.evaluate_records(after)
    old_cells = {(r["document_id"], r["field_name"]): r for r in old_errors}
    if {r["document_id"] for r in before} != {r["document_id"] for r in after}:
        raise ValueError("Comparisons require identical document sets")
    good = {"Exact", "Acceptable", "Correct Absent"}
    changes, regressions, improvements = [], [], []
    for row in new_errors:
        old = old_cells[(row["document_id"], row["field_name"])]
        if old["pred_raw"] != row["pred_raw"] or old["error_bucket"] != row["error_bucket"]:
            change = dict(document_id=row["document_id"], field=row["field_name"],
                          before=old["pred_raw"], after=row["pred_raw"], gt=row["gt_raw"],
                          old_bucket=old["error_bucket"], new_bucket=row["error_bucket"])
            changes.append(change)
            if old["error_bucket"] in good and row["error_bucket"] not in good:
                regressions.append(change)
            if old["error_bucket"] not in good and row["error_bucket"] in good:
                improvements.append(change)
    metrics = []
    new_by_field = {row["field_name"]: row for row in new_metrics}
    for old in old_metrics:
        new = new_by_field[old["field_name"]]
        metric = {"field": old["field_name"]}
        for key in ("f1", "precision", "recall", "nem", "vai_acc", "hallucination_rate"):
            metric[key + "_before"] = old[key]
            metric[key + "_after"] = new[key]
            metric[key + "_delta"] = None if old[key] is None or new[key] is None else new[key] - old[key]
        metrics.append(metric)
    buckets = ("Exact", "Acceptable", "Wrong", "Missing", "Hallucination", "Correct Absent")
    page_counts = {r["document_id"]: r["page_count"] for r in before}
    transitions = []
    for split, maximum in (("all", float("inf")), ("<=2", 2), ("<=5", 5), ("<=14", 14)):
        for old_bucket in buckets:
            for new_bucket in buckets:
                transitions.append(dict(split=split, old_bucket=old_bucket, new_bucket=new_bucket,
                    count=sum(page_counts[r["document_id"]] <= maximum and r["error_bucket"] == new_bucket
                              and old_cells[(r["document_id"], r["field_name"])]["error_bucket"] == old_bucket
                              for r in new_errors)))
    old_success = b.summarize_document_success(old_errors)[1]
    new_success = b.summarize_document_success(new_errors)[1]
    old_predictions = {r["document_id"]: r["prediction"] for r in before}
    raw_changes = [dict(document_id=r["document_id"], field=f, before=old_predictions[r["document_id"]].get(f), after=r["prediction"].get(f))
                   for r in after for f in set(r["prediction"]) | set(old_predictions[r["document_id"]])
                   if old_predictions[r["document_id"]].get(f) != r["prediction"].get(f)]
    return dict(changed_cells=changes, raw_prediction_changes=raw_changes,
                exact_prediction_documents=sum(r["prediction"] == old_predictions[r["document_id"]] for r in after),
                regressions=regressions, improvements=improvements, bucket_transitions=transitions,
                metrics=metrics, document_success_before=b.summarize_document_success(old_errors)[1],
                document_success_after=new_success, document_success_rate_delta=new_success["rate"] - old_success["rate"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--document-id", action="append", help="Exact ID, repeat for smoke tests")
    parser.add_argument("--preflight-only", action="store_true", help="Replay all saved blocks, no OCR models")
    parser.add_argument("--crop-cache", type=Path, help="Prior diagnostic bundle; recognize verified PNG crops without detection")
    parser.add_argument("--recognizer-config", type=Path, help="Recognition adapter JSON, cached mode only")
    parser.add_argument("--allow-recognizer-integration", action="store_true", help="Allow only approved OCR interface/factory changes for a fresh FastOCR control")
    parser.add_argument("--integration-control", type=Path, help="Completed FastOCR control with this exact code and GT; required for candidates")
    parser.add_argument("--resume", action="store_true", help="Resume only matching code/config/GT/cache checkpoints")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    crop_cache = args.crop_cache.resolve() if args.crop_cache else None
    if args.recognizer_config and (not crop_cache or not args.integration_control):
        parser.error("Candidates require --crop-cache and --integration-control")
    recognizer_options = json.loads(args.recognizer_config.read_text()) if args.recognizer_config else None
    mode = "hybrid_cached_crop_recognition" if crop_cache else "hybrid_boundary_page_ocr_equivalence"
    output.mkdir(parents=True, exist_ok=args.resume)
    if args.resume and (not (output / "run_fingerprint.json").is_file() or (output / "manifest.json").is_file()):
        raise ValueError("Resume requires an incomplete, fingerprinted diagnostic run")
    conf, snapshot_hashes = validate_source(source)
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib"))
    import benchmark as b
    from replay_all_v3 import _original_page_sizes, _trace_pages_for_extractor
    import numpy as np
    from PIL import Image
    from module.extract.vbhc_rules import extract_vbhc
    from module.layout.pp_doclayout import PPDocLayoutBackend
    from module.ocr import get_ocr_engine, TextRecognizer
    from module.pipeline.config import PipelineConfig
    from module.pipeline.document_pipeline import DocumentPipeline, _PreparedPage
    from module.pipeline.ocr_page import PageOcrPrep, prepare_ocr_page, finish_ocr_page

    cases = {c.document_id: c for c in b.load_cases(b.DEFAULT_CLEAN_DIR, b.DEFAULT_DATA_ROOT)}
    records = [json.loads(line) for line in (source / "predictions.jsonl").read_text().splitlines() if line.strip()]
    if len({r["document_id"] for r in records}) != len(records):
        raise ValueError("Duplicate source document IDs")
    if args.document_id:
        unknown = set(args.document_id) - {r["document_id"] for r in records}
        if unknown:
            raise ValueError(f"Unknown document IDs: {sorted(unknown)}")
        records = [r for r in records if r["document_id"] in args.document_id]
    manifest_docs = {d["document_id"]: d for d in json.loads((source / "manifest.json").read_text())["documents"]}
    cache_expected, prior_records, integration_changes = {}, [], []
    approved_integration_files = {"module/ocr/base.py", "module/ocr/engine.py", "module/ocr/__init__.py"}
    if args.integration_control:
        control_dir = args.integration_control.resolve()
        control_manifest = json.loads((control_dir / "manifest.json").read_text())
        control_preflight = json.loads((control_dir / "preflight.json").read_text())
        if control_manifest.get("status") != "completed" or control_manifest.get("is_recognizer_candidate", True) or not control_manifest.get("ab_ready"):
            raise ValueError("Integration control is not a completed equivalent FastOCR control")
        if control_manifest["source_manifest_sha256"] != sha256(source / "manifest.json"):
            raise ValueError("Integration control baseline mismatch")
        for relative, digest in control_preflight["dependency_sha256"].items():
            if sha256(ROOT / relative) != digest:
                raise ValueError(f"Code changed since integration control: {relative}")
    if crop_cache:
        cached_manifest = json.loads((crop_cache / "manifest.json").read_text())
        if cached_manifest.get("status") != "completed" or cached_manifest["source_manifest_sha256"] != sha256(source / "manifest.json"):
            raise ValueError("Crop cache is incomplete or belongs to another baseline")
        if sha256(crop_cache / "pipeline_config.json") != sha256(source / "pipeline_config.json"):
            raise ValueError("Crop cache config differs from baseline")
        cached_preflight = json.loads((crop_cache / "preflight.json").read_text())
        for relative, digest in cached_preflight["dependency_sha256"].items():
            if sha256(ROOT / relative) != digest:
                if relative not in approved_integration_files or not (args.allow_recognizer_integration or args.integration_control):
                    raise ValueError(f"Dependency differs from crop-cache run: {relative}")
                integration_changes.append(dict(path=relative, source_sha256=digest, current_sha256=sha256(ROOT / relative)))
        cached_runtime = json.loads((crop_cache / "runtime.json").read_text())
        if cached_runtime["fastocr_weight_sha256"] != sha256(conf["ocr"]["fastocr_weight_path"]):
            raise ValueError("FastOCR control weight differs from cache run")
        prior_records = [json.loads(line) for line in (crop_cache / "candidate_predictions.jsonl").read_text().splitlines() if line.strip()]
        prior_by_id = {r["document_id"]: r for r in prior_records}
        if len(prior_by_id) != len(prior_records) or any(r["document_id"] not in prior_by_id for r in records):
            raise ValueError("Crop-cache predictions have duplicate or missing document IDs")
        prior_records = [{**prior_by_id[r["document_id"]], "ground_truth": cases[r["document_id"]].ground_truth} for r in records]
    prepared = {}
    replay_records, preflight_rows = [], []
    for record in records:
        name = record["document_id"]
        case = cases[name]
        if sha256(case.pdf_path) != manifest_docs[name]["pdf_sha256"]:
            raise ValueError(f"PDF differs from baseline: {name}")
        trace = json.loads(Path(record["trace_path"]).read_text())
        raw = json.loads((source / "pipeline_outputs" / name / "output.json").read_text())
        if trace["document_id"] != name or len(trace["pages"]) != record["page_count"]:
            raise ValueError(f"Trace identity/page count mismatch: {name}")
        selected = selected_pages(json.loads(case.json_path.read_text())["metadata"], len(trace["pages"]))
        page_blocks = _trace_pages_for_extractor(trace)
        sizes = _original_page_sizes(case.pdf_path, len(page_blocks))
        processed = [(p["width"], p["height"]) for p in trace["pages"]]
        offsets = [p["crop_offset"] for p in raw["pages"]]
        if len(sizes) != len(page_blocks) or len(offsets) != len(page_blocks):
            raise ValueError(f"Geometry page count mismatch: {name}")
        image_hashes = {}
        for index, page in enumerate(trace["pages"]):
            if page["page"] != index + 1 or raw["pages"][index]["page"] != index + 1:
                raise ValueError(f"Physical page mapping mismatch: {name}, {index}")
            if index in selected:
                path = Path(page["image_url"])
                with Image.open(path) as image:
                    if image.size != processed[index]:
                        raise ValueError(f"Image/trace size mismatch: {name}, {index}")
                image_hashes[index] = sha256(path)
                if crop_cache:
                    expected = dict(page_index_0based=index, image_sha256=image_hashes[index],
                                    processed_size=list(processed[index]), original_size=list(sizes[index]),
                                    crop_offset=offsets[index], layout_blocks=page["layout_blocks"])
                    cache_expected[name, index] = expected
                    # Validate every page before model loading, not halfway through inference.
                    load_cached_page(crop_cache / "cache" / name / f"page_{index + 1}", expected)
        if crop_cache:
            selection = json.loads((crop_cache / "cache" / name / "selection.json").read_text())
            if selection["selected_physical_pages_0based"] != selected or selection["pdf_sha256"] != sha256(case.pdf_path):
                raise ValueError(f"Cached page selection/PDF mismatch: {name}")
        kwargs = dict(original_page_sizes=sizes, processed_page_sizes=processed, crop_offsets=offsets,
                      geometry_reliable=trace["extraction"]["geometry_reliable"])
        result, _ = extract_vbhc(page_blocks, **kwargs)
        prediction = flat_prediction(result, record["prediction"])
        replay_records.append({**record, "ground_truth": case.ground_truth, "prediction": prediction})
        preflight_rows.append(dict(document_id=name, selected_pages_0based=selected,
            exact_prediction=prediction == record["prediction"], image_sha256=image_hashes,
            label_sha256=sha256(case.json_path), source_label_sha256=manifest_docs[name]["label_sha256"]))
        prepared[name] = trace, selected, page_blocks, sizes, processed, offsets, kwargs
    before_replay = [{**r, "ground_truth": cases[r["document_id"]].ground_truth} for r in records]
    if args.integration_control:
        control_labels = {r["document_id"]: r["label_sha256"] for r in control_preflight["documents"]}
        if any(control_labels.get(r["document_id"]) != r["label_sha256"] for r in preflight_rows):
            raise ValueError("GT/selection differs from integration control")
    fingerprint = dict(harness_sha256=sha256(__file__), baseline_sha256=sha256(source / "manifest.json"),
        baseline_predictions_sha256=sha256(source / "predictions.jsonl"), config_sha256=sha256(source / "pipeline_config.json"),
        recognizer_config=recognizer_options,
        model_manifest_sha256=sha256(Path(recognizer_options["model_dir"]) / "download_manifest.json") if recognizer_options else None,
        cache_manifest_sha256=sha256(crop_cache / "manifest.json") if crop_cache else None,
        control_manifest_sha256=sha256(args.integration_control / "manifest.json") if args.integration_control else None,
        labels={r["document_id"]: r["label_sha256"] for r in preflight_rows},
        python_version=sys.version,
        installed_packages={d.metadata["Name"]: d.version for d in importlib.metadata.distributions() if d.metadata["Name"]},
        worker_packages={str(folder): {d.metadata["Name"]: d.version for d in importlib.metadata.distributions(path=[folder]) if d.metadata["Name"]}
                         for folder in (recognizer_options or {}).get("runtime", {}).get("pythonpath", [])},
        dependencies={str(p.relative_to(ROOT)): sha256(p) for folder in ("module/pipeline", "module/ocr", "module/layout", "fastocr") for p in sorted((ROOT / folder).rglob("*.py"))})
    if args.resume and json.loads((output / "run_fingerprint.json").read_text()) != fingerprint:
        raise ValueError("Resume fingerprint mismatch: code/config/GT/cache/model changed")
    dump(output / "run_fingerprint.json", fingerprint)
    replay_report = compare(before_replay, replay_records)
    dump(output / "saved_blocks_vs_full.json", replay_report)
    dump(output / "preflight.json", dict(documents=preflight_rows, snapshot_sha256=snapshot_hashes,
        harness_sha256=sha256(__file__), config_sha256=sha256(source / "pipeline_config.json"),
        exact_predictions=sum(r["exact_prediction"] for r in preflight_rows),
        selected_pages=sum(len(r["selected_pages_0based"]) for r in preflight_rows),
        crop_cache=str(crop_cache) if crop_cache else None,
        cache_manifest_sha256=sha256(crop_cache / "manifest.json") if crop_cache else None,
        approved_recognizer_integration_changes=integration_changes,
        unsnapshotted_dependencies="ocr_page, OCR engine, layout schema, mapping and reading order are hashed below but have no baseline snapshot",
        dependency_sha256={str(p.relative_to(ROOT)): sha256(p) for folder in ("module/pipeline", "module/ocr", "module/layout", "fastocr") for p in sorted((ROOT / folder).rglob("*.py"))}))
    dump(output / "pipeline_config.json", conf)
    print(f"Preflight: {len(records)} documents, {sum(r['exact_prediction'] for r in preflight_rows)} exact predictions", flush=True)
    if any(not r["exact_prediction"] for r in preflight_rows):
        raise ValueError("Saved-block replay differs from baseline; inspect saved_blocks_vs_full.json before OCR")
    if args.preflight_only:
        return
    config = PipelineConfig.from_conf(conf)
    model_provenance = None
    if recognizer_options:
        model_root = Path(recognizer_options["model_dir"])
        model_provenance = json.loads((model_root / "download_manifest.json").read_text())
        if model_provenance["backend"] != recognizer_options["backend"]:
            raise ValueError("Model manifest/backend mismatch")
        for relative, info in model_provenance["artifacts"].items():
            if sha256(model_root / relative) != info["sha256"]:
                raise ValueError(f"Downloaded model/source changed: {relative}")
    load_start = time.perf_counter()
    if crop_cache:
        # Assembly only needs drop_score. Do not instantiate a detector at all.
        if recognizer_options:
            from module.ocr.recognizers import create_recognizer
            recognizer = create_recognizer(recognizer_options)
        else:
            recognizer = TextRecognizer(weight_path=conf["ocr"]["fastocr_weight_path"],
                base_config_name=conf["ocr"]["fastocr_base_config"], max_batch_size=conf["ocr"].get("fastocr_max_batch_size", 64))
        ocr = SimpleNamespace(drop_score=0.5, text_recognizer=[recognizer])
    else:
        ocr = get_ocr_engine(conf)
    pipeline = DocumentPipeline(SimpleNamespace(label_schema=PPDocLayoutBackend.label_schema), ocr, None, config)
    load_seconds = time.perf_counter() - load_start
    versions = {}
    for package in ("torch", "numpy", "Pillow", "opencv-python", "onnxruntime", "onnxruntime-gpu", "transformers", "timm", "sentencepiece"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    dump(output / "runtime.json", dict(python=sys.version, packages=versions,
        fastocr_weight_sha256=sha256(conf["ocr"]["fastocr_weight_path"]),
        detector_loaded=not bool(crop_cache), drop_score=ocr.drop_score,
        recognizer_config=recognizer_options, confidence_policy="neutral 1.0 for assembly; native confidence and raw output retained separately",
        model_provenance=model_provenance,
        worker_runtime=getattr(ocr.text_recognizer[0], "worker_runtime", None),
        recognition_batch_protocol="Selected pages, per document, source fastocr_max_batch_size cap; differs from full-window composition"))
    before, controls, candidates, page_stats = [], [], [], []
    dump(output / "recognizer_config.json", recognizer_options or {"backend": "fastocr", **conf["ocr"]})
    source_snapshot = output / "source_snapshot"
    source_snapshot.mkdir(exist_ok=args.resume)
    for path in [Path(__file__).resolve(), ROOT / "module/ocr/base.py", ROOT / "module/ocr/engine.py", ROOT / "module/ocr/__init__.py",
                 ROOT / "module/extract/vbhc_rules.py", ROOT / "module/pipeline/document_pipeline.py",
                 *sorted((ROOT / "module/ocr/recognizers").glob("*.py"))]:
        shutil.copyfile(path, source_snapshot / str(path.relative_to(ROOT)).replace("/", "__"))
    recognition_changes = []
    recognition_compared = 0
    started = time.perf_counter()
    checkpoints = output / "checkpoints"
    checkpoints.mkdir(exist_ok=args.resume)
    for position, record in enumerate(records, 1):
        name = record["document_id"]
        checkpoint_path = checkpoints / f"{name}.json"
        if args.resume and checkpoint_path.is_file():
            completed = json.loads(checkpoint_path.read_text())
            before.append(completed["baseline"])
            controls.append(completed["control"])
            candidates.append(completed["candidate"])
            page_stats.extend(completed["page_stats"])
            recognition_changes.extend(completed["recognition_changes"])
            recognition_compared += completed["recognition_compared"]
            print(f"[{position}/{len(records)}] {name}: resumed completed checkpoint", flush=True)
            continue
        case = cases[name]
        trace, selected, page_blocks, sizes, processed, offsets, kwargs = prepared[name]
        record = {**record, "ground_truth": case.ground_truth, "has_handwriting": case.has_handwriting,
                  "metadata": json.loads(case.json_path.read_text())["metadata"]}
        control_pages = list(page_blocks)
        candidate_pages = list(page_blocks)
        doc_dir = output / "cache" / name
        doc_dir.mkdir(parents=True, exist_ok=args.resume)
        dump(doc_dir / "selection.json", dict(selected_physical_pages_0based=selected,
             label_sha256=sha256(case.json_path), pdf_sha256=sha256(case.pdf_path)))
        crop_preps, all_crops, images, layouts = {}, [], {}, {}
        for page_index in selected:
            page = trace["pages"][page_index]
            image_path = Path(page["image_url"])
            image = Image.open(image_path).convert("RGB")
            if image.size != processed[page_index]:
                raise ValueError(f"Image/trace size mismatch: {name}, page {page_index + 1}")
            images[page_index], layouts[page_index] = image, page["layout_blocks"]
            page_dir = doc_dir / f"page_{page_index + 1}"
            page_dir.mkdir(exist_ok=args.resume)
            exclusions = [x["bbox"] for x in page["layout_blocks"] if x["type"].lower() in pipeline.layout.label_schema.table_types]
            det_start = time.perf_counter()
            if crop_cache:
                source_page_dir = crop_cache / "cache" / name / f"page_{page_index + 1}"
                prep, crops, _ = load_cached_page(source_page_dir, cache_expected[name, page_index])
                (page_dir / "crops").mkdir(exist_ok=args.resume)
                for entry in json.loads((source_page_dir / "crop_manifest.json").read_text()):
                    shutil.copyfile(source_page_dir / entry["path"], page_dir / "crops" / f"{entry['detection_index']}.png")
            else:
                prep, crops = prepare_ocr_page(image, ocr, crop_debug_dir=str(page_dir / "crops"),
                    excluded_regions=exclusions, exclusion_overlap_threshold=config.map_overlap_threshold)
            elapsed = time.perf_counter() - det_start
            crop_preps[page_index] = (prep, len(all_crops), len(crops))
            all_crops.extend(crops)
            quads = [] if prep.dt_boxes is None else np.asarray(prep.dt_boxes).tolist()
            dump(page_dir / "input.json", dict(page_index_0based=page_index, image_path=str(image_path),
                image_sha256=sha256(image_path), processed_size=image.size, original_size=sizes[page_index],
                crop_offset=offsets[page_index], layout_blocks=page["layout_blocks"],
                detection_quads=quads, crop_indices=prep.crop_indices,
                excluded_indices=sorted(prep.excluded_indices), detection_crop_seconds=0.0 if crop_cache else elapsed,
                source_page_cache=str(source_page_dir) if crop_cache else None,
                source_input_sha256=sha256(source_page_dir / "input.json") if crop_cache else None,
                source_crop_manifest_sha256=sha256(source_page_dir / "crop_manifest.json") if crop_cache else None))
            dump(page_dir / "crop_manifest.json", [dict(detection_index=i, path=f"crops/{i}.png",
                sha256=sha256(page_dir / "crops" / f"{i}.png"), shape_bgr=list(crop.shape),
                array_sha256=hashlib.sha256(crop.tobytes()).hexdigest()) for i, crop in zip(prep.crop_indices, crops)])
            page_stats.append(dict(document_id=name, page=page_index + 1, crop_count=len(crops),
                                   baseline_line_count=len(page["ocr_lines"]), detection_crop_seconds=0.0 if crop_cache else elapsed,
                                   cache_load_copy_seconds=elapsed if crop_cache else None))
        rec_start = time.perf_counter()
        recognition, _ = ocr.text_recognizer[0](all_crops) if all_crops else ([], 0.0)
        recognition_seconds = time.perf_counter() - rec_start
        details = getattr(ocr.text_recognizer[0], "last_details", [])
        if details and len(details) != len(all_crops):
            raise ValueError("Recognizer detail/crop cardinality mismatch")
        if len(recognition) != len(all_crops):
            raise ValueError("Recognizer returned a different number of results than crops")
        for page_index in selected:
            prep, start, count = crop_preps[page_index]
            fresh_results = recognition[start:start + count]
            if crop_cache:
                source_results = json.loads((crop_cache / "cache" / name / f"page_{page_index + 1}" / "results.json").read_text())["recognition"]
                if [r["crop_index"] for r in source_results] != prep.crop_indices:
                    raise ValueError(f"Prior recognition index mismatch: {name}, {page_index}")
                for index, old, new in zip(prep.crop_indices, source_results, fresh_results):
                    recognition_compared += 1
                    if (old["text"], old["score"]) != tuple(new):
                        recognition_changes.append(dict(document_id=name, page_index_0based=page_index,
                            detection_index=index, before=old, after=dict(text=new[0], score=new[1])))
            fresh_lines = finish_ocr_page(prep, fresh_results, ocr)
            saved_lines = trace["pages"][page_index]["ocr_lines"]
            for stat in page_stats:
                if stat["document_id"] == name and stat["page"] == page_index + 1:
                    stat["retained_line_comparison"] = line_comparison(saved_lines, fresh_lines)
            # Recompute bbox_row (not serialized in traces), preserving the
            # source text/quad pairs, to control for cached layout reassembly.
            old_prep = PageOcrPrep(dt_boxes=np.asarray([x["quad"] for x in saved_lines]),
                                   crop_indices=list(range(len(saved_lines))))
            control_lines = finish_ocr_page(old_prep, [(x["text"], 1.0) for x in saved_lines], ocr)

            def assemble(lines):
                blocks, tables = pipeline._build_table_skeleton(page_index, images[page_index], copy.deepcopy(layouts[page_index]))
                if tables:
                    raise ValueError("Unexpected table processing in page-only test")
                return pipeline._process_page_after_layout(page_index,
                    _PreparedPage(images[page_index], None, None), blocks, lines)

            control_pages[page_index] = assemble(control_lines)
            candidate_pages[page_index] = assemble(fresh_lines)
            dump(doc_dir / f"page_{page_index + 1}" / "results.json", dict(
                recognition=[dict(crop_index=i, text=r[0], score=r[1]) for i, r in zip(prep.crop_indices, fresh_results)],
                 recognition_details=details[start:start + count] if details else [],
                 baseline_ocr_lines=saved_lines, candidate_ocr_lines=fresh_lines,
                 control_ocr_lines=control_lines,
                 control_limitations="Trace coordinates rounded; filtered empty/low-score detections absent; bbox_row reconstructed from retained lines only",
                 control_blocks=control_pages[page_index], candidate_blocks=candidate_pages[page_index]))
        control_result, control_debug = extract_vbhc(control_pages, **kwargs)
        candidate_result, candidate_debug = extract_vbhc(candidate_pages, **kwargs)
        before.append(record)
        controls.append(diagnostic_record(record, flat_prediction(control_result, record["prediction"]),
                                          control_debug.get("evidence", {}), doc_dir / "diagnostic.json"))
        candidates.append(diagnostic_record(record, flat_prediction(candidate_result, record["prediction"]),
                                            candidate_debug.get("evidence", {}), doc_dir / "diagnostic.json"))
        controls[-1]["generation_mode"] = candidates[-1]["generation_mode"] = mode
        dump(doc_dir / "diagnostic.json", dict(document_id=name, source_trace=record["trace_path"],
             control_extraction=control_debug, candidate_extraction=candidate_debug,
             recognition_seconds=recognition_seconds, crop_count=len(all_crops)))
        dump(checkpoint_path, dict(baseline=record, control=controls[-1], candidate=candidates[-1],
            page_stats=[r for r in page_stats if r["document_id"] == name],
            recognition_changes=[r for r in recognition_changes if r["document_id"] == name],
            recognition_compared=len(all_crops) if crop_cache else 0))
        for filename, items in (("candidate_predictions.jsonl", candidates),
                                ("control_predictions.jsonl", controls), ("baseline_predictions.jsonl", before)):
            write_jsonl(output / filename, items)
        print(f"[{position}/{len(records)}] {name}: {len(selected)} pages, {len(all_crops)} crops", flush=True)
        for image in images.values():
            image.close()
    for filename, items in (("candidate_predictions.jsonl", candidates), ("control_predictions.jsonl", controls),
                            ("baseline_predictions.jsonl", before)):
        write_jsonl(output / filename, items)
    reports = {"saved_ocr_reassembly_vs_full": compare(before, controls),
               ("cached_recognize_vs_full" if crop_cache else "redetect_recognize_vs_full"): compare(before, candidates),
               ("cached_recognize_vs_reassembly" if crop_cache else "redetect_recognize_vs_reassembly"): compare(controls, candidates)}
    if crop_cache:
        reports["cached_recognize_vs_prior_hybrid"] = compare(prior_records, candidates)
        dump(output / "recognition_vs_cache.json", dict(compared_crops=recognition_compared,
            exact_crop_results=recognition_compared - len(recognition_changes), changes=recognition_changes))
    for name, report in reports.items():
        dump(output / (name + ".json"), report)
        report_dir = output / name
        report_dir.mkdir(exist_ok=args.resume)
        columns = ["document_id", "field", "before", "after", "gt", "old_bucket", "new_bucket"]
        for key, filename in (("changed_cells", "all_changes.csv"), ("regressions", "sample_regressions.csv"),
                              ("improvements", "sample_improvements.csv")):
            write_csv(report_dir / filename, report[key], columns)
        write_csv(report_dir / "metrics_delta.csv", report["metrics"], list(report["metrics"][0]))
        write_csv(report_dir / "bucket_transitions.csv", report["bucket_transitions"],
                  ["split", "old_bucket", "new_bucket", "count"])
        print(name, "changed cells", len(report["changed_cells"]),
              "regressions", len(report["regressions"]), "improvements", len(report["improvements"]), flush=True)
    for label, evaluated in (("baseline", before), ("reassembly", controls), ("candidate", candidates)):
        evaluation_dir = output / "evaluation" / label
        evaluation_dir.mkdir(parents=True, exist_ok=args.resume)
        b.write_evaluation(evaluation_dir, evaluated, dict(mode=mode, full_inference=False))
    dump(output / "summary.json", dict(mode=mode, full_inference=False,
          detection_pages=0 if crop_cache else len(page_stats), crop_cache=str(crop_cache) if crop_cache else None,
          resumed=args.resume, timing_note="experiment_seconds covers current invocation after model load, including resumed-report assembly; per-document recognition seconds live in diagnostics",
         source=str(source), documents=len(records), selected_pages=len(page_stats),
         total_crops=sum(x["crop_count"] for x in page_stats), model_load_seconds=load_seconds,
         experiment_seconds=time.perf_counter() - started, metric_version=b.METRIC_VERSION,
          note=("Verified PNG BGR crops loaded from prior diagnostic; detection and crop generation not run. " if crop_cache else "") + "GT metadata selects pages; unselected pages retain baseline OCR. Layout comes from rounded source traces. Recognition is batched over selected pages per document, not the source full-page windows.",
          comparisons={name: {k: len(report[k]) for k in ("changed_cells", "regressions", "improvements")}
                       for name, report in reports.items()}))
    dump(output / "manifest.json", dict(mode=mode, status="completed",
        source=str(source), source_manifest_sha256=sha256(source / "manifest.json"),
        source_predictions_sha256=sha256(source / "predictions.jsonl"),
        documents=[r["document_id"] for r in records], metric_version=b.METRIC_VERSION,
        is_recognizer_candidate=bool(recognizer_options), recognizer_config=recognizer_options,
        integration_control=str(args.integration_control.resolve()) if args.integration_control else None,
        evidence_note="Diagnostic cache and extraction evidence only. Source traces are provenance, not fresh evidence.",
        causal_limits=("Fixed cached crops and original per-document recognition batch order; comparison with prior hybrid isolates cache decode/load and rerun variability. " if crop_cache else "Candidate vs control mixes detection/crops and recognition batch composition; no isolated batch effect experiment. ") + "Rounded layout/quads and missing pre-filter detections limit reassembly control.",
        ab_ready=all(not r["raw_prediction_changes"] for r in reports.values()) and not recognition_changes))
    dump(output / "page_stats.json", page_stats)
    dump(output / "pipeline_config.json", conf)
    if hasattr(ocr.text_recognizer[0], "close"):
        ocr.text_recognizer[0].close()


if __name__ == "__main__":
    main()
