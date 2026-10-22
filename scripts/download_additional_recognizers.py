"""Prepare supplementary assets without installing packages or changing active OCR code."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def download(url, path, expected=None):
    if path.is_file() and (expected is None or digest(path) == expected):
        return
    temporary = path.with_suffix(path.suffix + ".download")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle, 1024 * 1024)
    if expected and digest(temporary) != expected:
        raise ValueError(f"Download checksum mismatch: {url}")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "scratch/ocr-recognizers/models")
    parser.add_argument("--model", action="append")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "conf/recognizers/additional_catalog.json").read_text())
    reference = ROOT / "scratch/ocr-recognizers/sources/vietocr"
    for name in args.model or catalog:
        entry = catalog[name]
        folder = args.root / name
        folder.mkdir(parents=True, exist_ok=True)
        manifest_path = folder / "download_manifest.json"
        if manifest_path.is_file():
            saved = json.loads(manifest_path.read_text())
            if any(digest(folder / path) != info["sha256"] for path, info in saved["artifacts"].items()):
                raise ValueError(f"Existing model assets changed: {name}")
            print(f"Verified existing {name}", flush=True)
            continue
        if name == "akaocr":
            wheel = folder / "akaocr-2.1.6-py3-none-any.whl"
            download(entry["wheel_url"], wheel, entry["wheel_sha256"])
            with zipfile.ZipFile(wheel) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    target = (folder / "source" / item.filename).resolve()
                    if not target.is_relative_to((folder / "source").resolve()):
                        raise ValueError("Wheel path escapes extraction root")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
            shutil.copyfile(folder / "source/akaocr/recog/data/model.onnx", folder / "recognition.onnx")
            shutil.copyfile(folder / "source/akaocr/recog/data/vocab.txt", folder / "vocab.txt")
        else:
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=reference, text=True).strip()
            if actual != entry["source_revision"]:
                raise ValueError("Unexpected VietOCR source revision")
            # Export pinned git content, never copy a possibly dirty working tree.
            source_root = folder / "source"
            tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", actual], cwd=reference, text=True)
            for relative in tracked.splitlines():
                if relative.startswith(("vietocr/", "config/")) or relative in ("LICENSE", "README.md", "setup.py"):
                    target = source_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(subprocess.check_output(["git", "show", f"{actual}:{relative}"], cwd=reference))
            import yaml
            if name == "vietocr_dunghugging":
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id=entry["repo_id"], revision=entry["revision"],
                    allow_patterns=["transformerocr.pth", "config.yml", "README.md", "evaluation_results.json"], local_dir=folder)
                shutil.copyfile(folder / "transformerocr.pth", folder / "weights.pth")
            else:
                download(entry["weight_url"], folder / "weights.pth")
                config = yaml.safe_load((source_root / "config/base.yml").read_text())
                variant_file = entry["variant"].replace("_", "-") + ".yml"
                config.update(yaml.safe_load((source_root / "config" / variant_file).read_text()))
                (folder / "config.yml").write_text(yaml.safe_dump(config, allow_unicode=True))
        artifacts = {str(path.relative_to(folder)): dict(sha256=digest(path), bytes=path.stat().st_size)
                     for path in sorted(folder.rglob("*")) if path.is_file() and ".cache" not in path.parts
                     and path != manifest_path and not path.name.endswith(".download")}
        manifest_path.write_text(json.dumps({**entry, "name": name, "status": "downloaded", "artifacts": artifacts},
                                            ensure_ascii=False, indent=2) + "\n")
        print(f"Prepared {name}: {len(artifacts)} asset/source files", flush=True)


if __name__ == "__main__":
    main()
