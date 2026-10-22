"""Run a command with 40-second process/progress/GPU health snapshots."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time


def run_monitored(command, log_path, progress_root=None, interval=40):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    health = log_path.with_suffix(log_path.suffix + ".health.jsonl")
    started = time.monotonic()
    with log_path.open("a") as log, health.open("a") as events:
        process = subprocess.Popen(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT)
        last_count, last_progress = 0, started
        last_log_bytes, last_activity, last_warning = 0, started, started
        while True:
            now = time.monotonic()
            checkpoints = list(Path(progress_root).glob("**/checkpoints/*.json")) if progress_root else []
            if len(checkpoints) != last_count:
                last_progress, last_count = now, len(checkpoints)
                last_activity = now
            log_bytes = log_path.stat().st_size
            if log_bytes != last_log_bytes:
                last_log_bytes, last_activity = log_bytes, now
            try:
                gpu = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=10).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                gpu = "unavailable"
            status = process.poll()
            if status is None and now - last_activity >= 300 and now - last_warning >= 300:
                print(f"WARNING: PID {process.pid} alive, no new log/checkpoint for {now-last_activity:.0f}s; inspect {log_path}", flush=True)
                last_warning = now
            event = dict(timestamp=datetime.datetime.now().astimezone().isoformat(), pid=process.pid,
                process_alive=status is None, exit_code=status, elapsed_seconds=now-started,
                completed_checkpoints=len(checkpoints), seconds_without_new_checkpoint=now-last_progress,
                gpu=gpu, log_bytes=log_bytes,
                note="No checkpoint during preflight/load/reporting is not by itself failure")
            events.write(json.dumps(event) + "\n")
            events.flush()
            if status is not None:
                print(f"EXIT {status}: {log_path}; health={health}", flush=True)
                return status
            try:
                process.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--progress-root", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command is required")
    raise SystemExit(run_monitored(command, args.log, args.progress_root))


if __name__ == "__main__":
    main()
