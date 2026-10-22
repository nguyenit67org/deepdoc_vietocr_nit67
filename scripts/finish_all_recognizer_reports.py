"""Generate the requested all-model report only after every approved run finishes."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.finish_candidate_recognizer_ab import processes

BASE = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_vietdoc_base_20261021"
OUTPUT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021/final_all_models"


def main():
    while processes("run_vietdoc_base_config_test.py"):
        time.sleep(35)
    status = json.loads((BASE / "cohort_status.json").read_text())
    if status.get("status") != "finished" or any(value != "completed" for value in status["outcomes"].values()):
        raise ValueError("Base config experiment is incomplete; no final report claim")
    if processes("check_cached_ocr_equivalence.py"):
        raise ValueError("An inference harness remains active; do not infer completion from checkpoints")
    log = OUTPUT.parent / "final_all_models.log"
    print("RUN final current-GT all-model rescore/report", flush=True)
    with log.open("x") as handle:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/report_all_tested_recognizers.py"), str(OUTPUT)],
                                cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Final rescore/report failed; inspect {log}")
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    if manifest.get("status") != "completed":
        raise ValueError("Final report manifest is not completed")
    print(json.dumps(dict(status="report_generated_pending_controller_validation", report=str(OUTPUT / "REPORT.md"),
                          runs_rescored=manifest["runs_rescored"], best_hybrid_local_passed=manifest["best_hybrid_local_passed"]), indent=2), flush=True)


if __name__ == "__main__":
    main()
