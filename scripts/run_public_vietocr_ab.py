"""Sequential, guarded 100-document evaluation of three newly found checkpoints."""
import fcntl
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_cached_ocr_equivalence import sha256, dump
from scripts.finish_candidate_recognizer_ab import processes
from scripts.monitor_recognizer_job import run_monitored
from scripts.run_recognizer_ab import SMOKE_DOCUMENTS, smoke_is_valid

COHORT = ROOT / "ocr-collab/artifacts/recognizer_ab_public_vietocr_20261021"
CONTROL = ROOT / "ocr-collab/artifacts/recognizer_ab_candidates_extended_20261021/fastocr_control"
SOURCE = ROOT / "ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015"
CACHE = ROOT / "ocr-collab/artifacts/cached_ocr_equivalence_20261015"
MODELS = ("vietocr_nhay_seq2seq", "vietocr_hocba_transformer", "vietocr_khoi_handwritten")


def read(path):
    return json.loads(path.read_text())


def preservation():
    initial = read(COHORT / "initial_preservation.json")
    changed = [rel for rel, value in initial["files"].items() if not (ROOT / rel).is_file() or sha256(ROOT / rel) != value]
    if changed:
        raise ValueError(f"Protected files changed during experiment: {changed}")
    return dict(protected_files=len(initial["files"]), changed=[], gt_files=len(initial["gt"]))


def qualified(name, config):
    folder = COHORT / f"{name}_qualification"
    saved = read(folder / "qualification.json")
    if saved.get("status") != "passed" or read(folder / "functional_gpu.json")["config"] != config:
        raise ValueError("Qualification missing or stale")
    manifest = read(ROOT / config["model_dir"] / "download_manifest.json")
    for rel, info in manifest["artifacts"].items():
        if sha256(ROOT / config["model_dir"] / rel) != info["sha256"]:
            raise ValueError(f"Asset changed after qualification: {rel}")
    if name == "vietocr_nhay_seq2seq" and read(folder / "native_parity.json").get("status") != "passed":
        raise ValueError("Native/upstream parity not established")


def run(command, label):
    log = COHORT / f"{label}.log"
    if log.exists():
        raise FileExistsError(f"Preserve prior execution log: {log}")
    print("RUN", label, flush=True)
    return run_monitored(command, log, progress_root=COHORT, interval=35)


def main():
    with Path("/tmp/opencode/public-vietocr-benchmark.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if processes("check_cached_ocr_equivalence.py") or processes("qualify_public_vietocr.py") or processes("recognizers.worker"):
            raise ValueError("Another inference/qualification is active; no concurrent GPU job")
        control = read(CONTROL / "manifest.json")
        if control.get("status") != "completed" or not control.get("ab_ready"):
            raise ValueError("Need an exact completed FastOCR integration control")
        fingerprint = read(CONTROL / "run_fingerprint.json")
        current = {str(p.relative_to(ROOT)): sha256(p) for folder in ("module/pipeline", "module/ocr", "module/layout", "fastocr")
                   for p in sorted((ROOT / folder).rglob("*.py"))}
        if current != fingerprint["dependencies"]:
            raise ValueError("Recognizer integration changed; old control cannot be reused")
        outcomes = {}
        for name in MODELS:
            preservation()
            config_path = ROOT / f"conf/recognizers/{name}.json"
            config = read(config_path)
            qualification = COHORT / f"{name}_qualification"
            if not qualification.exists():
                code = run([sys.executable, str(ROOT / "scripts/qualify_public_vietocr.py"), str(qualification), "--model", name], f"{name}_qualification")
                if code:
                    outcomes[name] = "qualification_failed"
                    dump(COHORT / "progress.json", dict(outcomes=outcomes))
                    continue
            try:
                qualified(name, config)
            except Exception as error:
                outcomes[name] = f"qualification_blocked: {error}"
                dump(COHORT / "progress.json", dict(outcomes=outcomes))
                continue
            for stage in ("smoke", "full"):
                if stage == "full" and not smoke_is_valid(COHORT / f"{name}_smoke", config, fingerprint):
                    raise ValueError("Smoke missing, failed or stale; never bypass")
                folder = COHORT / (f"{name}_smoke" if stage == "smoke" else name)
                if folder.exists():
                    raise FileExistsError(f"No implicit restart or artifact overwrite: {folder}")
                command = [sys.executable, str(ROOT / "scripts/check_cached_ocr_equivalence.py"), str(SOURCE), str(folder),
                           "--crop-cache", str(CACHE), "--integration-control", str(CONTROL), "--recognizer-config", str(config_path)]
                if stage == "smoke":
                    for doc in SMOKE_DOCUMENTS:
                        command.extend(["--document-id", doc])
                if run(command, f"{name}_{stage}"):
                    outcomes[name] = f"{stage}_failed"
                    break
                if read(folder / "manifest.json").get("status") != "completed":
                    raise ValueError("Harness returned without a completed manifest")
                if stage == "full":
                    outcomes[name] = "completed"
            dump(COHORT / "progress.json", dict(outcomes=outcomes))
        dump(COHORT / "cohort_status.json", dict(status="inference_finished", outcomes=outcomes, integration_control=str(CONTROL)))
        if run([sys.executable, str(ROOT / "scripts/report_public_vietocr_ab.py"), str(COHORT)], "report"):
            raise RuntimeError("Report failed; retain inference outputs")
        preserved = preservation()
        dump(COHORT / "preservation_check.json", dict(status="passed", **preserved))
        dump(COHORT / "cohort_status.json", dict(status="finished", outcomes=outcomes, integration_control=str(CONTROL),
             all_requested_completed=all(outcomes.get(name) == "completed" for name in MODELS), preservation=preserved))
        print(json.dumps(dict(status="finished", outcomes=outcomes, report=str(COHORT / "report/REPORT.md")), indent=2), flush=True)


if __name__ == "__main__":
    main()
