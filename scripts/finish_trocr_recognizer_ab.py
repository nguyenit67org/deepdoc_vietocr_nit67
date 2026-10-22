"""Run gated final composite cohort, then export comparisons/config-rich report."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    print("RUN", *map(str, args), flush=True)
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT).returncode


def main():
    experiment = Path("ocr-collab/artifacts/recognizer_ab_trocr_20261015")
    control = experiment / "fastocr_control"
    mapping = json.loads((experiment / "word_crop_cache_manifest.json").read_text())
    exact = json.loads((control / "recognition_vs_cache.json").read_text())
    if mapping["status"] != "completed" or mapping["parent_count"] != 6619:
        raise ValueError("Word mapping is not complete")
    if exact["compared_crops"] != 6619 or exact["exact_crop_results"] != 6619 or exact["changes"]:
        raise ValueError("FastOCR control is not exact")
    result = run("scripts/run_trocr_recognizer_ab.py", experiment, "--stage", "all")
    completed = [experiment / model for model in ("fastocr_words", "trocr_words")
                 if (experiment / model / "manifest.json").is_file()
                 and json.loads((experiment / model / "manifest.json").read_text()).get("status") == "completed"]
    failures = []
    if completed:
        command = ["scripts/summarize_recognizer_ab.py", control, experiment / "comparison_final"]
        for folder in completed:
            command.extend(["--candidate", folder])
        if run(*command):
            failures.append("comparison")
    if run("scripts/summarize_recognizer_timing.py", experiment, experiment / "timing_final"):
        failures.append("timing")
    if len(completed) == 2:
        if run("scripts/summarize_recognizer_ab.py", experiment / "fastocr_words", experiment / "trocr_vs_same_word_fastocr",
               "--candidate", experiment / "trocr_words"):
            failures.append("same-word comparison")
    if run("scripts/build_recognizer_final_report.py", "ocr-collab/artifacts/recognizer_ab_all_20261015/final"):
        failures.append("final report")
    if result or failures:
        raise SystemExit(f"Incomplete cohort/postprocessing: runner_exit={result}, reports={failures}")


if __name__ == "__main__":
    main()
