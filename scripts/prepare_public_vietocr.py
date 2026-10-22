"""Pinned public checkpoints and unchanged upstream adapter assets, no package installation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import digest


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "public-vietocr-benchmark"}), timeout=120) as response:
        return response.read()


def prepare(name, entry):
    import yaml
    folder = ROOT / "scratch/ocr-recognizers/models" / name
    folder.mkdir(parents=True, exist_ok=False)
    prefix = "spaces/" if entry["repo_type"] == "space" else ""
    base = f"https://huggingface.co/{prefix}{entry['repo_id']}"
    rev = entry["revision"]
    endpoint = "spaces" if prefix else "models"
    metadata = json.loads(fetch(f"https://huggingface.co/api/{endpoint}/{entry['repo_id']}/revision/{rev}?blobs=true"))
    if metadata["sha"] != rev:
        raise ValueError("Source revision mismatch")
    (folder / "hub_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    info = next(s for s in metadata["siblings"] if s["rfilename"] == entry["weight_path"])
    if info["lfs"]["sha256"] != entry["weight_sha256"]:
        raise ValueError("Published weight hash changed")
    partial = folder / "weights.pth.download"
    url = f"{base}/resolve/{rev}/{entry['weight_path']}"
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("xb") as handle:
        count = 0
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
            count += len(chunk)
            if count // (20 * 1024 * 1024) != (count - len(chunk)) // (20 * 1024 * 1024):
                print(f"{name}: downloaded {count}/{info['size']} bytes", flush=True)
    if count != info["size"] or digest(partial) != entry["weight_sha256"]:
        raise ValueError("Weight bytes/hash mismatch")
    partial.rename(folder / "weights.pth")
    reference = ROOT / "scratch/ocr-recognizers/models" / ("vietocr_original_seq2seq" if entry["variant"] == "vgg_seq2seq" else "vietocr_original_transformer")
    ref = json.loads((reference / "download_manifest.json").read_text())
    for rel, saved in ref["artifacts"].items():
        if rel.startswith("source/"):
            if digest(reference / rel) != saved["sha256"]:
                raise ValueError(f"Pinned upstream asset changed: {rel}")
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reference / rel, target)
    if entry["config_path"]:
        raw = fetch(f"{base}/raw/{rev}/{entry['config_path']}")
        (folder / "author_config.yml").write_bytes(raw)
        config = yaml.safe_load(raw)
    else:
        config = yaml.safe_load((reference / "config.yml").read_text())
    # Complete checkpoint contains the CNN; block any hidden ImageNet fetch.
    config["cnn"]["pretrained"] = False
    (folder / "config.yml").write_text(yaml.safe_dump(config, allow_unicode=True))
    if name == "vietocr_nhay_seq2seq":
        sources = [s["rfilename"] for s in metadata["siblings"] if s["rfilename"].endswith(".py") or s["rfilename"] in ("requirements.txt", "README.md")]
        def native_file(rel):
            target = folder / "native_source" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fetch(f"{base}/raw/{rev}/{rel}"))
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(native_file, sources))
    else:
        for rel in ("README.md", "web_demo.py"):
            if any(s["rfilename"] == rel for s in metadata["siblings"]):
                (folder / rel).write_bytes(fetch(f"{base}/raw/{rev}/{rel}"))
    artifacts = {str(p.relative_to(folder)): {"sha256": digest(p), "bytes": p.stat().st_size}
                 for p in sorted(folder.rglob("*")) if p.is_file()}
    manifest = dict(entry, name=name, backend="vietocr_original", source_revision=ref["source_revision"], artifacts=artifacts,
        runtime_protocol="Pinned upstream greedy decoder, FP32, identical-width buckets, fixed parent crops. Not native full-page applications.",
        config_override="cnn.pretrained=False only, to prevent hidden ImageNet fetch; runtime device and decode limit set in recognizer config",
        config_assumed=entry["config_path"] is None)
    (folder / "download_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"PREPARED {name}, weights SHA256 verified", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "conf/recognizers/public_vietocr_catalog.json").read_text())
    selected = args.model or list(catalog)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda name: prepare(name, catalog[name]), selected))


if __name__ == "__main__":
    main()
