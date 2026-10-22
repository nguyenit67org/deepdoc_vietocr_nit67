"""Pin and verify public Duyle and VNHTR inference assets, without training."""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import digest, download

DUYLE_REVISION = "96101b35a3e7bd9b066a77abe1b3e8631856e230"
VNHTR_REVISION = "18c127441dea3cd731289c7b292ab0af2c0aefa8"
WEIGHTS_REVISION = "da2e288871617d479c587f5c2f9903c923ef6e5c"


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "recognizer-candidate-audit"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download_lfs(url, path, expected, size):
    """Use checked byte ranges to avoid silently accepting truncated CDN bodies."""
    if path.exists():
        if path.stat().st_size != size or digest(path) != expected:
            raise ValueError(f"Existing asset failed verification: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".parts.download")
    with temporary.open("wb") as handle:
        for offset in range(0, size, 8 * 1024 * 1024):
            end = min(size - 1, offset + 8 * 1024 * 1024 - 1)
            for attempt in range(3):
                try:
                    request = urllib.request.Request(f"{url}?range_start={offset}", headers={"Range": f"bytes={offset}-{end}"})
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {offset}-{end}/{size}":
                            raise ValueError("CDN did not honor requested byte range")
                        data = response.read()
                    if len(data) != end - offset + 1:
                        raise ValueError("Truncated CDN range")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2)
            handle.write(data)
            handle.flush()
            print(f"Downloading {path.name}: {end + 1}/{size}", flush=True)
    if digest(temporary) != expected:
        raise ValueError(f"LFS checksum mismatch: {path}")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr", "vnhtr_vgg_base", "vnhtr_trocr_base"), action="append")
    args = parser.parse_args()
    for name in args.model or ("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr"):
        folder = ROOT / "scratch/ocr-recognizers/models" / name
        folder.mkdir(parents=True, exist_ok=True)
        manifest = folder / "download_manifest.json"
        if manifest.exists():
            saved = json.loads(manifest.read_text())
            if any(digest(folder / p) != info["sha256"] for p, info in saved["artifacts"].items()):
                raise ValueError(f"Changed existing assets: {name}")
            print(f"Verified {name}", flush=True)
            continue
        if name == "trocr_duyle":
            repo = "duyle2408/trocr-vietnamese-handwriting"
            revision = DUYLE_REVISION
            metadata = get_json(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true")
            (folder / "hub_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
            for item in metadata["siblings"]:
                filename = item["rfilename"]
                if filename == "training_args.bin" or filename.startswith("."):
                    continue
                expected = item.get("lfs", {}).get("sha256")
                download(f"https://huggingface.co/{repo}/resolve/{revision}/{filename}", folder / filename, expected)
                print(f"Downloaded {name}/{filename}: {(folder / filename).stat().st_size}", flush=True)
            backend = "trocr_duyle"
        else:
            repo, revision, backend = "anhnh2002/vnhtr", VNHTR_REVISION, "vnhtr_jit"
            prefix = {"vnhtr_vgg": "vta", "vnhtr_trocr": "tra",
                      "vnhtr_vgg_base": "vt", "vnhtr_trocr_base": "tr"}[name]
            for part in ("encoder", "decoder"):
                filename = f"{prefix}_{part}.pt"
                pointer_url = f"https://raw.githubusercontent.com/anhnh2002/vnhtr_weights/{WEIGHTS_REVISION}/{filename}"
                pointer = urllib.request.urlopen(pointer_url, timeout=60).read().decode()
                expected = next(line.split("sha256:")[1] for line in pointer.splitlines() if line.startswith("oid sha256:"))
                size = int(next(line.split()[1] for line in pointer.splitlines() if line.startswith("size ")))
                (folder / f"{filename}.lfs.txt").write_text(pointer)
                download_lfs(f"https://media.githubusercontent.com/media/anhnh2002/vnhtr_weights/{WEIGHTS_REVISION}/{filename}", folder / filename, expected, size)
                print(f"Downloaded {name}/{filename}: {(folder / filename).stat().st_size}", flush=True)
            # Keep provenance but never import or execute upstream downloader code.
            download(f"https://raw.githubusercontent.com/{repo}/{revision}/vnhtr/vnhtr_script/tools.py", folder / "upstream_tools.py.txt")
            download(f"https://raw.githubusercontent.com/{repo}/{revision}/LICENSE", folder / "LICENSE")
            if name in ("vnhtr_trocr", "vnhtr_trocr_base"):
                from huggingface_hub import snapshot_download
                for dep_repo, subfolder, patterns in (
                    ("vinai/bartpho-syllable-base", "tokenizer", ["*.json", "vocab.txt", "dict.txt", "bpe.codes", "*.model"]),
                    ("microsoft/trocr-small-handwritten", "processor", ["preprocessor_config.json"]),
                ):
                    info = get_json(f"https://huggingface.co/api/models/{dep_repo}")
                    snapshot_download(dep_repo, revision=info["sha"], allow_patterns=patterns, local_dir=folder / subfolder)
                    (folder / f"{subfolder}_provenance.json").write_text(json.dumps({"repo": dep_repo, "revision": info["sha"]}, indent=2))
        artifacts = {str(p.relative_to(folder)): {"sha256": digest(p), "bytes": p.stat().st_size}
                     for p in sorted(folder.rglob("*")) if p.is_file() and ".cache" not in p.parts
                     and p != manifest and not p.name.endswith(".download")}
        manifest.write_text(json.dumps(dict(name=name, repo=repo, revision=revision, backend=backend,
            weights_revision=WEIGHTS_REVISION if name.startswith("vnhtr") else None,
            artifacts=artifacts), indent=2) + "\n")


if __name__ == "__main__":
    main()
