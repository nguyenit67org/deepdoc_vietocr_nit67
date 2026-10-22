"""Generate a reproducible visual smoke sheet and parent-to-word provenance."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from PIL import Image, ImageDraw
from module.ocr.recognizers.word_segment import WhitespaceWordSegmenter
from scripts.smoke_additional_recognizers import sample_pages


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=False)
    splitter = WhitespaceWordSegmenter("scratch/ocr-recognizers/word-cache-projection-v1")
    samples = list(sample_pages(Path("ocr-collab/artifacts/cached_ocr_equivalence_20261015")))
    sheet = Image.new("RGB", (1800, len(samples) * 180), "white")
    draw = ImageDraw.Draw(sheet)
    records = []
    for i, (crop, provenance) in enumerate(samples):
        image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        words, data = splitter.segment(image)
        marked = image.copy()
        pen = ImageDraw.Draw(marked)
        for j, (x0, y0, x1, y1) in enumerate(data["boxes"]):
            pen.rectangle((x0, y0, x1 - 1, y1 - 1), outline="red", width=1)
        factor = min(1750 / image.width, 120 / image.height, 3)
        marked = marked.resize((round(image.width * factor), round(image.height * factor)))
        draw.text((10, i * 180 + 5), f"sample {i}: page {provenance['physical_page_index_0based']}, detection {provenance['detection_index']}, segments {len(words)}", fill="black")
        sheet.paste(marked, (10, i * 180 + 30))
        image.save(output / f"sample_{i}.png")
        records.append(dict(**provenance, **data))
    sheet.save(output / "segmentation_sheet.png")
    (output / "samples.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
