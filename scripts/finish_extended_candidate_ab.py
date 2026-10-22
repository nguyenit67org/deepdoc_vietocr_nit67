"""Run the approved second cohort only after the first frozen cohort finishes."""
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PREVIOUS = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_20261021"
COHORT = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_extended_20261021"
MODELS = ("vnhtr_vgg_base", "vnhtr_trocr_base", "easyocr_latin_pretrained")


def read(path):
    return json.loads(path.read_text())


def run(command, name):
    print("RUN", name, flush=True)
    with (COHORT / f"{name}.log").open("x") as handle:
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    print("EXIT", name, result.returncode, flush=True)
    return result.returncode


def main():
    if read(PREVIOUS / "cohort_status.json").get("status") != "finished":
        raise ValueError("First cohort has not finished; preserve its frozen runtime")
    from scripts.finish_candidate_recognizer_ab import processes
    if processes("finish_candidate_recognizer_ab.py") or processes("run_candidate_recognizer_ab.py") or processes("check_cached_ocr_equivalence.py"):
        raise ValueError("An earlier benchmark process is still alive; do not compete for GPU")
    from module.ocr.recognizers import available_recognizers
    from module.ocr.recognizers.candidates import VnhtrJitRecognizer
    if "easyocr_latin" not in available_recognizers() or "rethinking_head" not in inspect.signature(VnhtrJitRecognizer).parameters:
        raise ValueError("Staged adapters are not activated; controller must activate after first-cohort completion")
    COHORT.mkdir(exist_ok=False)
    control = COHORT / "fastocr_control"
    source = ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"
    cache = ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"
    if run([sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"), str(source), str(control),
            "--crop-cache", str(cache), "--allow-recognizer-integration"], "fresh_control"):
        raise RuntimeError("Fresh integration control failed; do not run candidates")
    manifest = read(control / "manifest.json")
    crops = read(control / "recognition_vs_cache.json")
    if not manifest.get("ab_ready") or len(manifest["documents"]) != 100 or crops["exact_crop_results"] != 6619 or crops["compared_crops"] != 6619:
        raise ValueError("New control is not exact for all 100 documents / 6619 crops")
    first = read(PREVIOUS / "fastocr_control/run_fingerprint.json")
    second = read(control / "run_fingerprint.json")
    if first["labels"] != second["labels"]:
        raise ValueError("GT changed between cohorts; no four-case comparison permitted")
    if (PREVIOUS / "fastocr_control/candidate_predictions.jsonl").read_text() != (control / "candidate_predictions.jsonl").read_text():
        # Diagnostics and timing paths are expected to differ: compare actual
        # document-field predictions rather than serialized provenance strings.
        def predictions(path):
            return {row["document_id"]: row["prediction"] for row in
                    (json.loads(line) for line in path.read_text().splitlines() if line.strip())}
        if predictions(PREVIOUS / "fastocr_control/candidate_predictions.jsonl") != predictions(control / "candidate_predictions.jsonl"):
            raise ValueError("Cross-cohort FastOCR predictions differ")
    outcomes = {}
    for name in MODELS:
        if run([sys.executable, str(ROOT / "scripts/smoke_candidate_recognizers.py"), str(COHORT / "functional_smoke"),
                "--model", name], f"{name}_functional"):
            outcomes[name] = "functional_smoke_process_failed"
            continue
        functional = read(COHORT / "functional_smoke" / f"{name}.json")
        if functional.get("status") != "passed":
            outcomes[name] = "functional_smoke_failed"
            continue
        code = run([sys.executable, str(ROOT / "scripts/run_extended_candidate_ab.py"), str(COHORT),
                    "--stage", "all", "--model", name], f"{name}_driver")
        path = COHORT / name / "manifest.json"
        outcomes[name] = "completed" if code == 0 and path.exists() and read(path).get("status") == "completed" else "benchmark_failed"
    complete = [name for name, status in outcomes.items() if status == "completed"]
    if complete:
        command = [sys.executable, str(ROOT / "scripts/summarize_recognizer_ab.py"), str(control), str(COHORT / "comparison_final")]
        for name in complete:
            command.extend(["--candidate", str(COHORT / name)])
        if run(command, "comparison_final"):
            raise RuntimeError("Comparison failed; preserve results for inspection")
        from scripts.summarize_recognizer_timing import primary_file_timings, summarize_models
        from scripts.check_cached_ocr_equivalence import write_csv
        rows = primary_file_timings(COHORT, ["fastocr_control", *complete])
        timing = COHORT / "timing_final"
        timing.mkdir()
        write_csv(timing / "per_file.csv", rows, list(rows[0]))
        summaries = summarize_models(rows)
        write_csv(timing / "per_model.csv", summaries, list(summaries[0]))
    status = dict(status="finished", outcomes=outcomes, cross_cohort_control_predictions_exact=True,
                  note="Inspect per-model outcomes; finished driver does not imply every model succeeded.")
    (COHORT / "cohort_status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2), flush=True)


if __name__ == "__main__":
    main()
