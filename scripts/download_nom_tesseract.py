"""Prepare isolated pinned Nôm source, Tesseract 5, vie-best and spell model."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import download, digest

NOM_REVISION = "2c99458ff55d7aa6b8c97398e2f0b1282efbcb73"
SPELL_REVISION = "ba1e57fc3bacdfb22bfa20b19db7182a6d1b0b6b"
TESSDATA_REVISION = "e12c65a915945e4c28e237a9b52bc4a8f39a0cec"


def main():
    root = ROOT / "scratch/ocr-recognizers/models/nom_tesseract"
    source = root / "source/src/nom"
    if not (source / "doc/stages.py").is_file() or not (source / "text/diacritic_models.py").is_file():
        raise ValueError("Pinned nom-vn source export must be present before preparation")
    manifest = root / "download_manifest.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        for path, info in saved["artifacts"].items():
            if digest(root / path) != info["sha256"]:
                raise ValueError(f"Asset changed: {path}")
        print("All existing assets verified", flush=True)
        return
    packages = [
        ("https://ppa.launchpadcontent.net/alex-p/tesseract-ocr5/ubuntu/pool/main/t/tesseract-lept5/tesseract-ocr_5.5.1-1ppa1~jammy1_amd64.deb", "560951f4ac3ec82aa3986a7590537f59acaa4b6b23111cf7f85abcfc9a35f39a"),
        ("https://ppa.launchpadcontent.net/alex-p/tesseract-ocr5/ubuntu/pool/main/t/tesseract-lept5/libtesseract5_5.5.1-1ppa1~jammy1_amd64.deb", "aff1db9df37434f0111e4cd189e2dde0212bc8075b6de3dfc005e8b54f8d26fd"),
    ]
    for package in ("liblept5", "libgif7", "libwebpmux3"):
        output = subprocess.check_output(["apt-cache", "show", package], text=True).split("\n\n")[0]
        metadata = dict(line.split(": ", 1) for line in output.splitlines() if ": " in line and not line.startswith(" "))
        packages.append(("https://archive.ubuntu.com/ubuntu/" + metadata["Filename"], metadata["SHA256"]))
    (root / "packages").mkdir(exist_ok=True)
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    package_records = []
    for url, checksum in packages:
        path = root / "packages" / url.rsplit("/", 1)[1]
        download(url, path, checksum)
        subprocess.run(["dpkg-deb", "-x", str(path), str(runtime)], check=True)
        package_records.append(dict(url=url, sha256=checksum))
        print(f"Extracted {path.name}", flush=True)
    data = root / "tessdata"
    data.mkdir(exist_ok=True)
    url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{TESSDATA_REVISION}/vie.traineddata"
    download(url, data / "vie.traineddata")
    from huggingface_hub import snapshot_download
    snapshot_download("nrl-ai/vn-spell-correction-base", revision=SPELL_REVISION,
        local_dir=root / "spell", allow_patterns=["*.json", "*.safetensors", "spiece.model", "README.md"])
    artifacts = {str(path.relative_to(root)): dict(sha256=digest(path), bytes=path.stat().st_size)
        for path in sorted(root.rglob("*")) if path.is_file()
        and not any(part in (".cache", "__pycache__") for part in path.parts)
        and path != manifest and not path.name.endswith(".download")}
    manifest.write_text(json.dumps(dict(backend="nom_tesseract", nom_revision=NOM_REVISION,
        spell_repo="nrl-ai/vn-spell-correction-base", spell_revision=SPELL_REVISION,
        tessdata_repo="tesseract-ocr/tessdata_best", tessdata_revision=TESSDATA_REVISION,
        tesseract_version="5.5.1-1ppa1~jammy1", packages=package_records,
        wrapper="nom.doc.stages.OCR (documented nom.doc.ocr.TesseractOCR absent)", artifacts=artifacts), indent=2) + "\n")
    print(f"Prepared {len(artifacts)} assets; manifest={manifest}", flush=True)


if __name__ == "__main__":
    main()
