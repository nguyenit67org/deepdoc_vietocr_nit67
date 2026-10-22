"""Stage the already-downloaded official EasyOCR Latin Gen2 weights and source."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import digest


def main():
    root = ROOT / "scratch/ocr-recognizers/models/easyocr_latin_pretrained"
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    downloaded = ROOT / "scratch/ocr-recognizers/sources/vietdoc_download_probe_26f9cfa/models/easyocr/latin_g2.pth"
    if digest(downloaded) != "aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55":
        raise ValueError("Downloaded Latin Gen2 weights changed")
    shutil.copyfile(downloaded, root / "latin_g2.pth")
    dependencies = ROOT / "scratch/ocr-recognizers/trocr-deps"
    shutil.copytree(dependencies / "easyocr", root / "source/easyocr", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(dependencies / "easyocr-1.7.2.dist-info", root / "source/easyocr-1.7.2.dist-info")
    manifest = dict(backend="easyocr_latin", name="easyocr_latin_pretrained", package="easyocr==1.7.2",
        model_kind="official Latin Gen2 pretrained; not VietDoc fine-tuned",
        source="VietDoc native --easyocr downloader; official EasyOCR assets, verified by Reader MD5 and retained SHA-256",
        detector_enabled=False, decoder="greedy", native_batch_size=1, quantize=False,
        artifacts={str(p.relative_to(root)): dict(sha256=digest(p), bytes=p.stat().st_size)
                   for p in sorted(root.rglob("*")) if p.is_file()})
    (root / "download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(root)


if __name__ == "__main__":
    main()
