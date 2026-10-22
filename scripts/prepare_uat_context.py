"""Export a fresh allowlisted build context using existing verified local assets."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument("--layout-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    original = args.assets_root / "scratch/ocr-recognizers/models/vietocr_original_transformer"
    manifest = json.loads((original / "download_manifest.json").read_text())
    for rel, expected in manifest["artifacts"].items():
        if digest(original / rel) != expected["sha256"]:
            raise ValueError(f"Upstream asset checksum mismatch: {rel}")
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=False)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "weight")
    for folder in ("module", "utils", "fastocr"):
        shutil.copytree(repo / folder, target / folder, ignore=ignore)
    for rel in ("server/__init__.py", "server/schemas.py", "server/security.py", "server/uat.py",
                "conf/uat.yaml", "deploy/Dockerfile", "deploy/requirements.lock"):
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, destination)
    shutil.copy2(repo / "deploy/context.dockerignore", target / ".dockerignore")
    shutil.copytree(original / "source", target / "models/vietocr/source", ignore=ignore)
    for name in ("weights.pth", "config.yml", "download_manifest.json"):
        shutil.copy2(original / name, target / "models/vietocr" / name)
    (target / "models/detector").mkdir(parents=True)
    shutil.copy2(args.assets_root / "onnx/det.onnx", target / "models/detector/det.onnx")
    (target / "models/layout").mkdir()
    for name in ("inference.json", "inference.pdiparams", "inference.yml"):
        shutil.copy2(args.layout_dir / name, target / "models/layout" / name)
    model_files = sorted(p for p in (target / "models").rglob("*") if p.is_file())
    checksums = {str(p.relative_to(target)): {"sha256": digest(p), "bytes": p.stat().st_size} for p in model_files}
    (target / "models/manifest.json").write_text(json.dumps(checksums, indent=2) + "\n")
    total = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print(json.dumps({"context": str(target), "bytes": total, "model_files": len(model_files)}, indent=2))


if __name__ == "__main__":
    main()
