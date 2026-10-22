"""Sequential GPU smoke/full runner; completed smoke is mandatory before full."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("ocrdoc", "vietocr_handwriting", "htr_convtext", "senocr")
SMOKE_DOCUMENTS = (
    "43+2026+QH16_2026-08-24", "27+2026+VBHN-ND-BTC_2026-08-27",
    "155+2020+NĐ-CP_2020-12-31", "71+2017+NĐ-CP_2017-06-06",
    "117+2020+TT-BTC_2020-12-31",
)


def read(path):
    return json.loads(path.read_text())


def smoke_is_valid(folder, config, control_fingerprint):
    manifest = read(folder / "manifest.json")
    fingerprint = read(folder / "run_fingerprint.json")
    return (manifest["status"] == "completed" and manifest["is_recognizer_candidate"]
            and set(manifest["documents"]) == set(SMOKE_DOCUMENTS)
            and fingerprint["recognizer_config"] == config
            and fingerprint["dependencies"] == control_fingerprint["dependencies"]
            and all(control_fingerprint["labels"].get(key) == value for key, value in fingerprint["labels"].items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Experiment root, containing completed fastocr_control/")
    parser.add_argument("--stage", choices=("smoke", "full", "all"), default="smoke")
    parser.add_argument("--model", choices=MODELS, action="append")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    control = root / "fastocr_control"
    manifest = read(control / "manifest.json")
    if manifest.get("status") != "completed" or not manifest.get("ab_ready") or manifest.get("is_recognizer_candidate"):
        raise ValueError("A completed exact FastOCR integration control is required")
    control_fingerprint = read(control / "run_fingerprint.json")
    stages = ("smoke", "full") if args.stage == "all" else (args.stage,)
    failures = []
    for stage in stages:
        for model in args.model or MODELS:
            config_path = ROOT / f"conf/recognizers/{model}.json"
            config = read(config_path)
            smoke_folder = root / f"{model}_smoke"
            folder = smoke_folder if stage == "smoke" else root / model
            if stage == "full" and (not (smoke_folder / "manifest.json").is_file()
                                    or not smoke_is_valid(smoke_folder, config, control_fingerprint)):
                print(f"BLOCKED {model}: smoke missing, failed or stale", flush=True)
                failures.append((stage, model))
                continue
            if (folder / "manifest.json").is_file():
                if not args.resume:
                    raise FileExistsError(folder)
                fingerprint = read(folder / "run_fingerprint.json")
                if fingerprint["dependencies"] != control_fingerprint["dependencies"] or fingerprint["recognizer_config"] != config:
                    raise ValueError(f"Completed run is stale: {folder}")
                print(f"SKIP completed {folder}", flush=True)
                continue
            command = [sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"),
                str(ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"), str(folder),
                "--crop-cache", str(ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"),
                "--integration-control", str(control), "--recognizer-config", str(config_path)]
            if stage == "smoke":
                for document_id in SMOKE_DOCUMENTS:
                    command.extend(["--document-id", document_id])
            if folder.exists() and args.resume:
                command.append("--resume")
            log = root / f"{model}_{stage}.log"
            print(f"RUN {stage} {model}; log={log}", flush=True)
            with log.open("a" if args.resume else "x") as handle:
                result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
            if result.returncode:
                failures.append((stage, model))
                print(f"FAILED {stage} {model}; inspect {log}", flush=True)
            else:
                print(f"COMPLETED {stage} {model}", flush=True)
    if failures:
        raise SystemExit(f"Incomplete runs: {failures}")


if __name__ == "__main__":
    main()
