"""Verify four-case weight identity and actual serialized Rethinking graph use."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_additional_recognizers import digest

CASES = {
    "vnhtr_vgg_base": ("vt", False),
    "vnhtr_vgg": ("vta", True),
    "vnhtr_trocr_base": ("tr", False),
    "vnhtr_trocr": ("tra", True),
}


def inspect_decoder(path):
    with zipfile.ZipFile(path) as archive:
        root_code = next(name for name in archive.namelist() if name.endswith("/code/__torch__.py"))
        code = archive.read(root_code).decode()
    references = [line.strip() for line in code.splitlines() if "rethinking" in line.lower()]
    return references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    rows = []
    for name, (prefix, expected_head) in CASES.items():
        folder = ROOT / "scratch/ocr-recognizers/models" / name
        manifest = folder / "download_manifest.json"
        if not manifest.exists():
            rows.append(dict(case=name, status="not_downloaded_yet"))
            continue
        saved = json.loads(manifest.read_text())
        decoder = f"{prefix}_decoder.pt"
        actual = digest(folder / decoder)
        if saved["artifacts"][decoder]["sha256"] != actual:
            raise ValueError(f"Decoder checksum changed: {name}")
        references = inspect_decoder(folder / decoder)
        if bool(references) != expected_head:
            raise ValueError(f"Head label differs from serialized root graph: {name}")
        rows.append(dict(case=name, status="verified", expected_rethinking_head=expected_head,
                         decoder_sha256=actual, serialized_root_graph_references=references))
    hashes = [row["decoder_sha256"] for row in rows if row["status"] == "verified"]
    if len(set(hashes)) != len(hashes):
        raise ValueError("Different VNHTR cases reuse identical decoder weights")
    preprocessing_pairs = {}
    for family in ("vgg", "trocr"):
        folders = [ROOT / "scratch/ocr-recognizers/models" / f"vnhtr_{family}{suffix}" for suffix in ("", "_base")]
        if not all((folder / "download_manifest.json").exists() for folder in folders):
            continue
        maps = []
        for folder in folders:
            artifacts = json.loads((folder / "download_manifest.json").read_text())["artifacts"]
            maps.append({rel: info["sha256"] for rel, info in artifacts.items()
                         if rel == "upstream_tools.py.txt" or rel.startswith(("tokenizer/", "processor/"))})
        if maps[0] != maps[1]:
            raise ValueError(f"Head/no-head tokenizer or native preprocessing sources differ: {family}")
        preprocessing_pairs[family] = dict(identical=True, verified_assets=list(maps[0]))
    output = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021/source_audit/vnhtr/case_assets.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(cases=rows, preprocessing_pairs=preprocessing_pairs,
                                    note="Graph identity audit, not evidence of the exact training dataset"), indent=2) + "\n")
    print(json.dumps(rows, indent=2))
    if args.require_all and len(hashes) != 4:
        raise SystemExit("Not all four VNHTR asset sets are ready")


if __name__ == "__main__":
    main()
