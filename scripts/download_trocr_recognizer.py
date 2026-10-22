"""Download the pinned Thaito98 word checkpoint, verifying its Git LFS hash."""
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.download_additional_recognizers import download, digest

REVISION = "823e8848ef9b676940af8d516f7fbba3041097bf"
WEIGHT_HASH = "2a94382180088ce9e9d433e4f5920ba1a128363e79cbb9fbfeaa591e8b16e290"


def main():
    root = Path("scratch/ocr-recognizers/models/trocr_thaito98")
    root.mkdir(parents=True, exist_ok=True)
    files = ("config.json", "generation_config.json", "processor_config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors")
    base = f"https://raw.githubusercontent.com/Thaito98/vietnamese-handwriting-ocr/{REVISION}/models/best_model"
    for name in files:
        url = (f"https://media.githubusercontent.com/media/Thaito98/vietnamese-handwriting-ocr/{REVISION}/models/best_model/{name}"
               if name == "model.safetensors" else f"{base}/{name}")
        download(url, root / name, WEIGHT_HASH if name == "model.safetensors" else None)
        print(f"Downloaded {name}: {(root / name).stat().st_size}", flush=True)
    manifest = dict(backend="word_to_line", repo="Thaito98/vietnamese-handwriting-ocr", revision=REVISION,
                    artifacts={name: dict(sha256=digest(root / name), bytes=(root / name).stat().st_size) for name in files})
    (root / "download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
