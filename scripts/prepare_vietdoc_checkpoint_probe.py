"""Stage VietDoc-downloaded handwriting weights for a checkpoint-only ablation.

Uses the existing pinned upstream VietOCR adapter, not the VietDoc application
decoder. This distinction is explicitly recorded in provenance.
"""
import json
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("base", "handwriting"), default="handwriting")
    args = parser.parse_args()
    probe = ROOT / "scratch/ocr-recognizers/sources/vietdoc_download_probe_26f9cfa/models" / args.variant
    reference = ROOT / "scratch/ocr-recognizers/models/vietocr_original_transformer"
    name = "vietdoc_base_pth" if args.variant == "base" else "vietdoc_vudang_pth"
    folder = ROOT / "scratch/ocr-recognizers/models" / name
    provenance = json.loads((probe / "provenance.json").read_text())
    if digest(probe / "model.pth") != provenance["sha256"]:
        raise ValueError("Downloaded VietDoc checkpoint changed")
    ref_manifest = json.loads((reference / "download_manifest.json").read_text())
    for rel, info in ref_manifest["artifacts"].items():
        if rel.startswith("source/") and digest(reference / rel) != info["sha256"]:
            raise ValueError(f"Pinned upstream source changed: {rel}")
    if folder.exists():
        raise FileExistsError(folder)
    folder.mkdir(parents=True)
    shutil.copytree(reference / "source", folder / "source")
    shutil.copyfile(probe / "model.pth", folder / "weights.pth")
    shutil.copyfile(probe / "config.yml", folder / "config.yml")
    manifest = dict(backend="vietocr_original", name=name, **provenance,
        source_revision=ref_manifest["source_revision"],
        protocol="Checkpoint-only ablation with pinned upstream VietOCR adapter; NOT native VietDoc application decoder. No optional DIP or segmentation.",
        decoder_difference="Upstream greedy translate, max_seq_length=256, width buckets; VietDoc native decode additionally suppresses pad/sos/mask tokens and runs one line at a time.",
        artifacts={str(p.relative_to(folder)): dict(sha256=digest(p), bytes=p.stat().st_size)
                   for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts})
    (folder / "download_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(folder)


if __name__ == "__main__":
    main()
