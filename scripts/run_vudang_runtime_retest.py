"""Matched-parent-input native PyTorch/ONNX reruns after the extended cohort.

Retains each tested adapter's preprocessing; this is not numerical backend-only parity.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.finish_candidate_recognizer_ab import processes
from scripts.run_recognizer_ab import SMOKE_DOCUMENTS, smoke_is_valid

PREVIOUS = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_extended_20261021"
COHORT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_vudang_retest_20261021"
MODELS = (("vudang_pytorch_retest", "vietdoc_vudang_pth"), ("vudang_onnx_retest", "vietocr_handwriting"))


def read(path):
    return json.loads(path.read_text())


def run(command, log):
    print("RUN", log.name, flush=True)
    with log.open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    print("EXIT", result.returncode, log.name, flush=True)
    return result.returncode


def main():
    while processes("finish_extended_candidate_ab.py"):
        time.sleep(35)
    if read(PREVIOUS / "cohort_status.json").get("status") != "finished":
        raise ValueError("Extended cohort did not finish; do not silently restart or bypass it")
    if processes("check_cached_ocr_equivalence.py"):
        raise ValueError("Another benchmark is active; preserve sequential GPU protocol")
    control = PREVIOUS / "fastocr_control"
    manifest = read(control / "manifest.json")
    fingerprint = read(control / "run_fingerprint.json")
    if not manifest.get("ab_ready") or manifest.get("status") != "completed":
        raise ValueError("A completed exact integration control is required")
    COHORT.mkdir(exist_ok=False)
    outcomes = {}
    for name, config_name in MODELS:
        config_path = ROOT / f"conf/recognizers/{config_name}.json"
        config = read(config_path)
        smoke = COHORT / f"{name}_smoke"
        for stage, folder in (("smoke", smoke), ("full", COHORT / name)):
            if stage == "full" and not smoke_is_valid(smoke, config, fingerprint):
                outcomes[name] = "blocked_stale_or_failed_smoke"
                break
            command = [sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"),
                str(ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"), str(folder),
                "--crop-cache", str(ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"),
                "--integration-control", str(control), "--recognizer-config", str(config_path)]
            if stage == "smoke":
                for doc in SMOKE_DOCUMENTS:
                    command.extend(["--document-id", doc])
            if run(command, COHORT / f"{name}_{stage}.log"):
                outcomes[name] = f"{stage}_failed"
                break
            outcomes[name] = "completed" if stage == "full" else "smoke_completed"
    completed = [name for name, status in outcomes.items() if status == "completed"]
    if completed:
        command = [sys.executable, str(ROOT / "scripts/summarize_recognizer_ab.py"), str(control), str(COHORT / "comparison_vs_fastocr")]
        for name in completed:
            command.extend(["--candidate", str(COHORT / name)])
        if run(command, COHORT / "comparison_vs_fastocr.log"):
            raise RuntimeError("Retest comparison failed; preserve results")
    if len(completed) == 2:
        command = [sys.executable, str(ROOT / "scripts/report_vietdoc_checkpoint_parity.py"), str(COHORT / "runtime_parity"),
                   "--before", str(COHORT / "vudang_onnx_retest"), "--after", str(COHORT / "vudang_pytorch_retest")]
        if run(command, COHORT / "runtime_parity.log"):
            raise RuntimeError("Retest raw parity comparison failed")
    status = dict(status="finished", outcomes=outcomes, integration_control=str(control),
                  scope="Same parent crops/GT; native preprocessing, precision and decoding differ. Not backend-only numerical parity.")
    (COHORT / "cohort_status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2), flush=True)


if __name__ == "__main__":
    main()
