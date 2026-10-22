"""Freeze parent-to-word mappings for both composite ablation branches."""
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PIL import Image
from module.ocr.recognizers.word_segment import WhitespaceWordSegmenter
from scripts.check_cached_ocr_equivalence import load_cached_page


def main():
    source = Path("ocr-collab/artifacts/cached_ocr_equivalence_20261015/cache")
    output = Path(sys.argv[1])
    if output.exists():
        raise FileExistsError(output)
    config = json.loads(Path("conf/recognizers/trocr_words.json").read_text())
    splitter = WhitespaceWordSegmenter(config["segmentation_cache"], config["gap_height_ratio"], config["pad_px"])
    rows = []
    started = time.perf_counter()
    for folder in sorted(source.glob("*/page_*")):
        prep, crops, _ = load_cached_page(folder, {})
        for index, crop in zip(prep.crop_indices, crops):
            _, data = splitter.segment(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
            manifest = Path(data["cache_manifest"])
            rows.append(dict(document_id=folder.parent.name, physical_page_index_0based=int(folder.name[5:]) - 1,
                detection_index=index, **data,
                segments_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()))
    if len(rows) != 6619 or len({r["document_id"] for r in rows}) != 100:
        raise ValueError("Unexpected parent crop coverage")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(status="completed", policy=splitter.policy, parent_count=len(rows),
        word_count=sum(len(r["boxes"]) for r in rows), blank_parents=sum(r["blank"] for r in rows),
        preparation_wall_seconds=time.perf_counter() - started,
        segmentation_compute_seconds=sum(r["segmentation_seconds"] for r in rows),
        note="Offline deterministic cache preparation, no OCR inference. Both branches use this mapping.", parents=rows), indent=2) + "\n")


if __name__ == "__main__":
    main()
