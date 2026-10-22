"""Stage supplementary recognizers without editing the active model registry.

CPU by default while the primary GPU benchmark is active. This is a crop-level
functional smoke, not a KIE benchmark or a comparable latency measurement.
"""
import argparse
from dataclasses import asdict
import gc
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import dump, load_cached_page, sha256

MODELS = ("akaocr", "vietocr_original_seq2seq", "vietocr_original_transformer", "vietocr_dunghugging")


def sample_pages(cache):
    # Explicit known regression cases select samples only, never extraction rules.
    for doc, index in (("43+2026+QH16_2026-08-24", 0), ("43+2026+QH16_2026-08-24", 1),
                       ("117+2020+TT-BTC_2020-12-31", 0)):
        folder = cache / "cache" / doc / f"page_{index + 1}"
        prep, crops, _ = load_cached_page(folder, {})
        selected = [0, max(range(len(crops)), key=lambda i: crops[i].shape[1] / crops[i].shape[0])]
        if 14 in prep.crop_indices and doc.startswith("117+"):
            selected.append(prep.crop_indices.index(14))
        for i in dict.fromkeys(selected):
            yield crops[i], dict(document_id=doc, physical_page_index_0based=index,
                detection_index=prep.crop_indices[i], crop_path=str(folder / "crops" / f"{prep.crop_indices[i]}.png"),
                crop_sha256=sha256(folder / "crops" / f"{prep.crop_indices[i]}.png"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--model", choices=MODELS, action="append")
    parser.add_argument("--cpu-threads", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    import torch
    torch.set_num_threads(args.cpu_threads)
    from module.ocr.recognizers.akaocr import AkaOcrRecognizer
    from module.ocr.recognizers.vietocr_original import VietOcrOriginalRecognizer
    classes = {"akaocr": AkaOcrRecognizer, "vietocr_original": VietOcrOriginalRecognizer}
    control = ROOT / "ocr-collab/artifacts/recognizer_ab_20261015/fastocr_control"
    active = json.loads((control / "run_fingerprint.json").read_text())["dependencies"]
    changed = [path for path, digest in active.items() if sha256(ROOT / path) != digest]
    if changed:
        raise ValueError(f"Active primary runtime source changed: {changed}")
    samples = list(sample_pages(ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"))
    crops, provenance = zip(*samples)
    statuses = []
    for name in args.model or MODELS:
        options = json.loads((ROOT / f"conf/recognizers/{name}.json").read_text())
        options["device"] = args.device
        backend = options.pop("backend")
        root = ROOT / options["model_dir"]
        manifest = json.loads((root / "download_manifest.json").read_text())
        for relative, info in manifest["artifacts"].items():
            if sha256(root / relative) != info["sha256"]:
                raise ValueError(f"Changed additional asset: {name}/{relative}")
        model = None
        try:
            started = time.perf_counter()
            model = classes[backend](**options)
            load_seconds = time.perf_counter() - started
            results, elapsed = model(list(crops))
            if len(results) != len(crops) or len(model.last_details) != len(crops):
                raise ValueError("Supplementary adapter lost crops")
            dump(args.output / f"{name}.json", dict(status="passed", device=args.device, config={"backend": backend, **options},
                load_seconds=load_seconds, smoke_wall_seconds=elapsed, samples=provenance,
                results=results, details=model.last_details,
                timing_note="Functional smoke during another run; NOT comparable benchmark timing"))
            statuses.append(dict(model=name, status="passed", crops=len(crops)))
            print(f"PASS {name}: {len(crops)} crops on {args.device}", flush=True)
        except Exception:
            error = traceback.format_exc()
            dump(args.output / f"{name}.json", dict(status="failed", device=args.device, error=error))
            statuses.append(dict(model=name, status="failed"))
            print(f"FAIL {name}\n{error}", flush=True)
        finally:
            del model
            gc.collect()
    dump(args.output / "manifest.json", dict(status="passed" if all(r["status"] == "passed" for r in statuses) else "partial_failure",
        mode="supplementary_crop_functional_smoke", device=args.device, models=statuses,
        source_runtime_unchanged=True, registry_modified=False, transcription_gt_used=False,
        cuda_initialized_in_smoke_process=torch.cuda.is_initialized(),
        next_step="Wire registry only after primary runner finishes, then fresh control and KIE smoke/full"))
    if any(r["status"] != "passed" for r in statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
