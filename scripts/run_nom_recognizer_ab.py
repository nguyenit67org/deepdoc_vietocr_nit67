"""Gated Nôm Tesseract raw/spell benchmark with 40-second live monitoring."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.monitor_recognizer_job import run_monitored
from scripts.run_recognizer_ab import smoke_is_valid, SMOKE_DOCUMENTS


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    control = root / "fastocr_control"
    base = [sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"),
        str(ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015")]
    cache = ["--crop-cache", str(ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015")]

    def execute(command, name):
        print(f"RUN {name}", flush=True)
        code = run_monitored(command, root / f"{name}.log", root)
        if code:
            raise SystemExit(f"FAILED {name}: exit {code}; inspect log/health; no automatic config changes")
        print(f"COMPLETED {name}", flush=True)

    if not (control / "manifest.json").is_file():
        command = base + [str(control)] + cache + ["--allow-recognizer-integration"]
        if control.exists() and args.resume:
            command.append("--resume")
        execute(command, "fastocr_control")
    elif not args.resume:
        raise FileExistsError(control)
    manifest = read(control / "manifest.json")
    exact = read(control / "recognition_vs_cache.json")
    if manifest["status"] != "completed" or not manifest["ab_ready"] or exact["exact_crop_results"] != 6619 or exact["changes"]:
        raise ValueError("Fresh FastOCR control is not exact/complete")
    fingerprint = read(control / "run_fingerprint.json")
    for stage in ("smoke", "full"):
        for model in ("nom_tesseract_raw", "nom_tesseract_spell"):
            config_path = ROOT / f"conf/recognizers/{model}.json"
            config = read(config_path)
            smoke = root / f"{model}_smoke"
            folder = smoke if stage == "smoke" else root / model
            if stage == "full" and not smoke_is_valid(smoke, config, fingerprint):
                raise ValueError(f"Missing/stale smoke: {model}")
            if (folder / "manifest.json").is_file():
                if not args.resume:
                    raise FileExistsError(folder)
                saved = read(folder / "run_fingerprint.json")
                if saved["dependencies"] != fingerprint["dependencies"] or saved["recognizer_config"] != config:
                    raise ValueError("Completed run fingerprint differs")
                continue
            command = base + [str(folder)] + cache + ["--integration-control", str(control), "--recognizer-config", str(config_path)]
            if stage == "smoke":
                for document in SMOKE_DOCUMENTS:
                    command.extend(["--document-id", document])
            if folder.exists() and args.resume:
                command.append("--resume")
            execute(command, f"{model}_{stage}")
    for name, before, candidates in (
        ("comparison_vs_fastocr", control, [root / "nom_tesseract_raw", root / "nom_tesseract_spell"]),
        ("spell_vs_raw", root / "nom_tesseract_raw", [root / "nom_tesseract_spell"]),
    ):
        output = root / name
        if output.exists() and args.resume and (output / "manifest.json").is_file():
            continue
        command = [sys.executable, str(ROOT / "scripts/summarize_recognizer_ab.py"), str(before), str(output)]
        for candidate in candidates:
            command.extend(["--candidate", str(candidate)])
        execute(command, name)
    execute([sys.executable, str(ROOT / "scripts/summarize_recognizer_timing.py"), str(root), str(root / "timing_final")], "timing_export")
    execute([sys.executable, str(ROOT / "scripts/report_nom_recognizer_ab.py"), str(root)], "final_report")


if __name__ == "__main__":
    main()
