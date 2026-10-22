"""Download pinned public recognition weights/source, without importing model code."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "scratch/ocr-recognizers/models")
    parser.add_argument("--model", action="append")
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    catalog = json.loads((ROOT / "conf/recognizers/catalog.json").read_text())
    for name in args.model or catalog:
        entry = catalog[name]
        folder = args.root / name
        snapshot_download(repo_id=entry["repo_id"], revision=entry["revision"],
                          allow_patterns=entry["files"], local_dir=folder, max_workers=3)
        files = {}
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or ".cache" in path.parts or path.name == "download_manifest.json":
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            files[str(path.relative_to(folder))] = dict(sha256=digest.hexdigest(), bytes=path.stat().st_size)
        manifest = {**entry, "name": name, "status": "downloaded", "artifacts": files}
        (folder / "download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Downloaded {name}: {len(files)} files at {entry['revision']}", flush=True)


if __name__ == "__main__":
    main()
