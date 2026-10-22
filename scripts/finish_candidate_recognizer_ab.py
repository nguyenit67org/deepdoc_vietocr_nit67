"""Finish this cohort sequentially after the already-running Duyle driver.

Never restarts a disappeared job, trains missing models, or bypasses fingerprints.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
COHORT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021"


def processes(script):
    found = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = path.read_bytes().decode().split("\0")
            if any(Path(arg).name == script for arg in argv[1:] if arg):
                found.append(int(path.parent.name))
        except (OSError, UnicodeError):
            continue
    return found


def read(path):
    return json.loads(path.read_text())


def run(command, log):
    print("RUN", " ".join(str(part) for part in command), flush=True)
    with log.open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    print("EXIT", result.returncode, log, flush=True)
    return result.returncode


def main():
    # The launched Duyle driver must finish normally. Do not mistake saved
    # checkpoints for an active process or silently restart a lost worker.
    while processes("run_candidate_recognizer_ab.py"):
        time.sleep(35)
    duyle = COHORT / "trocr_duyle/manifest.json"
    outcomes = {"trocr_duyle": "completed" if duyle.exists() and read(duyle).get("status") == "completed" else "failed_or_interrupted"}
    for name in ("vnhtr_vgg", "vnhtr_trocr", "vietdoc_vudang_pth"):
        asset_manifest = ROOT / "scratch/ocr-recognizers/models" / name / "download_manifest.json"
        while not asset_manifest.exists() and processes("download_candidate_recognizers.py"):
            time.sleep(35)
        if not asset_manifest.exists():
            outcomes[name] = "blocked_asset_download_failed"
            continue
        functional = COHORT / "functional_smoke" / f"{name}.json"
        if functional.exists():
            raise FileExistsError(f"Existing functional smoke needs explicit review: {functional}")
        code = run([sys.executable, str(ROOT / "scripts/smoke_candidate_recognizers.py"),
                    str(COHORT / "functional_smoke"), "--model", name], COHORT / f"{name}_functional.log")
        if code or not functional.exists() or read(functional).get("status") != "passed":
            outcomes[name] = "functional_smoke_failed"
            continue
        code = run([sys.executable, str(ROOT / "scripts/run_candidate_recognizer_ab.py"),
                    str(COHORT), "--stage", "all", "--model", name], COHORT / f"{name}_driver.log")
        manifest = COHORT / name / "manifest.json"
        outcomes[name] = "completed" if code == 0 and manifest.exists() and read(manifest).get("status") == "completed" else "benchmark_failed"
    complete = [name for name, status in outcomes.items() if status == "completed"]
    if complete:
        command = [sys.executable, str(ROOT / "scripts/summarize_recognizer_ab.py"),
                   str(COHORT / "fastocr_control"), str(COHORT / "comparison_final")]
        for name in complete:
            command.extend(["--candidate", str(COHORT / name)])
        if run(command, COHORT / "comparison_final.log"):
            raise RuntimeError("Comparison failed; preserve partial results and inspect log")
        from scripts.summarize_recognizer_timing import primary_file_timings, summarize_models
        from scripts.check_cached_ocr_equivalence import write_csv
        rows = primary_file_timings(COHORT, ["fastocr_control", *complete])
        timing = COHORT / "timing_final"
        timing.mkdir(exist_ok=False)
        write_csv(timing / "per_file.csv", rows, list(rows[0]))
        summaries = summarize_models(rows)
        write_csv(timing / "per_model.csv", summaries, list(summaries[0]))
    status = dict(status="finished", outcomes=outcomes, note="Finished driver is not proof all requested models ran successfully; inspect per-model outcomes.")
    (COHORT / "cohort_status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2), flush=True)


if __name__ == "__main__":
    main()
