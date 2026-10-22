"""Functional GPU smoke on cached printed/handwritten/long line inputs."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import dump, load_cached_page, sha256


def samples():
    cache = ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015/cache"
    for doc, page, indices in (
        ("43+2026+QH16_2026-08-24", 1, [0, 1, 2]),
        ("155+2020+NĐ-CP_2020-12-31", 1, list(range(12))),
        ("155+2020+NĐ-CP_2020-12-31", 254, list(range(12))),
        ("117+2020+TT-BTC_2020-12-31", 1, [0]),
    ):
        folder = cache / doc / f"page_{page}"
        prep, crops, _ = load_cached_page(folder, {})
        indices.append(max(range(len(crops)), key=lambda i: crops[i].shape[1] / crops[i].shape[0]))
        for index in dict.fromkeys(i for i in indices if i < len(crops)):
            path = folder / "crops" / f"{prep.crop_indices[index]}.png"
            yield crops[index], dict(document_id=doc, physical_page_0based=page - 1,
                                     detection_index=prep.crop_indices[index], path=str(path), sha256=sha256(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", choices=("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr", "vietdoc_vudang_pth",
                                            "vnhtr_vgg_base", "vnhtr_trocr_base", "easyocr_latin_pretrained", "vietdoc_base_pth"), action="append")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import cv2
    from PIL import Image, ImageDraw
    selected = list(samples())
    dump(args.output / "samples.json", [meta for _, meta in selected])
    sheet = Image.new("RGB", (1800, len(selected) * 120), "#dddddd")
    draw = ImageDraw.Draw(sheet)
    for index, (crop, meta) in enumerate(selected):
        image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        image.thumbnail((1780, 90))
        draw.text((5, index * 120), f"{index}: {meta['document_id']} / detection {meta['detection_index']}", fill="black")
        sheet.paste(image, (5, index * 120 + 22))
    sheet.save(args.output / "contact.png")
    if args.prepare_only:
        return
    from module.ocr.recognizers import create_recognizer
    for name in args.model or ("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr", "vietdoc_vudang_pth"):
        model = None
        try:
            config = json.loads((ROOT / f"conf/recognizers/{name}.json").read_text())
            config["device"] = args.device
            if args.device == "cpu":
                config["runtime"]["env"].update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
            folder = ROOT / config["model_dir"]
            manifest = json.loads((folder / "download_manifest.json").read_text())
            if any(sha256(folder / relative) != info["sha256"] for relative, info in manifest["artifacts"].items()):
                raise ValueError("Model assets changed")
            started = time.perf_counter()
            model = create_recognizer(config)
            load_seconds = time.perf_counter() - started
            results, elapsed = model([crop for crop, _ in selected])
            if len(results) != len(selected):
                raise ValueError("Smoke dropped crops")
            dump(args.output / f"{name}.json", dict(status="passed", config=config, load_seconds=load_seconds,
                 elapsed_seconds=elapsed, samples=[meta for _, meta in selected], results=results,
                 details=model.last_details, worker_runtime=model.worker_runtime,
                 note="Functional smoke only, no transcription GT or recognition accuracy claim"))
            print(f"PASS {name}: {len(selected)} crops", flush=True)
        except Exception:
            error = traceback.format_exc()
            dump(args.output / f"{name}.json", dict(status="failed", error=error))
            print(f"FAIL {name}\n{error}", flush=True)
        finally:
            if model is not None:
                model.close()


if __name__ == "__main__":
    main()
