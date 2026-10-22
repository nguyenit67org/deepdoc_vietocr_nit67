"""Same upstream Transformer weights, additional VietDoc-config ablation."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.finish_candidate_recognizer_ab import processes
from scripts.run_recognizer_ab import SMOKE_DOCUMENTS, smoke_is_valid

PREVIOUS = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_vudang_retest_20261021"
CONTROL = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_extended_20261021/fastocr_control"
COHORT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_vietdoc_base_20261021"


def read(path):
    return json.loads(path.read_text())


def run(command, name):
    print("RUN", name, flush=True)
    with (COHORT / f"{name}.log").open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    print("EXIT", name, result.returncode, flush=True)
    return result.returncode


def main():
    while processes("run_vudang_runtime_retest.py"):
        time.sleep(35)
    if read(PREVIOUS / "cohort_status.json").get("status") != "finished":
        raise ValueError("Prior paired-runtime cohort did not finish")
    if processes("check_cached_ocr_equivalence.py"):
        raise ValueError("Another benchmark is active; no concurrent GPU run")
    control_manifest = read(CONTROL / "manifest.json")
    if control_manifest.get("status") != "completed" or not control_manifest.get("ab_ready"):
        raise ValueError("Exact fresh integration control required")
    COHORT.mkdir(exist_ok=False)
    name = "vietdoc_base_pth"
    config_path = ROOT / f"conf/recognizers/{name}.json"
    config = read(config_path)
    functional = COHORT / "functional_smoke"
    if run([sys.executable, str(ROOT / "scripts/smoke_candidate_recognizers.py"), str(functional), "--model", name], "functional"):
        raise RuntimeError("Base functional smoke process failed")
    if read(functional / f"{name}.json").get("status") != "passed":
        raise RuntimeError("Base functional smoke failed")
    smoke = COHORT / f"{name}_smoke"
    for stage, folder in (("smoke", smoke), ("full", COHORT / name)):
        if stage == "full" and not smoke_is_valid(smoke, config, read(CONTROL / "run_fingerprint.json")):
            raise ValueError("Missing/stale GPU smoke; do not bypass")
        command = [sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"),
            str(ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"), str(folder),
            "--crop-cache", str(ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"),
            "--integration-control", str(CONTROL), "--recognizer-config", str(config_path)]
        if stage == "smoke":
            for doc in SMOKE_DOCUMENTS:
                command.extend(["--document-id", doc])
        if run(command, stage):
            raise RuntimeError(f"Base {stage} failed; preserve partial outputs")
    command = [sys.executable, str(ROOT / "scripts/summarize_recognizer_ab.py"), str(CONTROL),
               str(COHORT / "comparison_vs_fastocr"), "--candidate", str(COHORT / name)]
    if run(command, "comparison_vs_fastocr"):
        raise RuntimeError("Base comparison failed")
    parity = [sys.executable, str(ROOT / "scripts/report_vietdoc_checkpoint_parity.py"), str(COHORT / "checkpoint_config_parity"),
              "--before", str(PREVIOUS / "vudang_onnx_retest"), "--after", str(PREVIOUS / "vudang_pytorch_retest")]
    if run(parity, "checkpoint_config_parity"):
        raise RuntimeError("Base/runtime parity report failed")
    status = dict(status="finished", outcomes={name: "completed"}, integration_control=str(CONTROL),
                  scope="Same official Transformer weights; upstream decoder with VietDoc supplied width/decode limits; not native VietDoc application decoder.")
    (COHORT / "cohort_status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2), flush=True)


if __name__ == "__main__":
    main()
