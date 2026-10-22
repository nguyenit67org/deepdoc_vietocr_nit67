"""Five reproducible 1..20-page PDF samples, inside a network-disabled container.

Requires Docker permission. Evidence stays outside the image and source dataset.
"""
import argparse
import json
import os
from pathlib import Path
import random
import re
import secrets
import subprocess
import time


def docker(*args, **kwargs):
    return subprocess.check_output(["docker", *args], **kwargs).decode()


def select_samples(root, seed):
    candidates = []
    for path in sorted(root.rglob("*.pdf")):
        try:
            info = subprocess.check_output(["pdfinfo", str(path)], stderr=subprocess.DEVNULL, timeout=15).decode()
            pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M)[1])
        except (subprocess.SubprocessError, TypeError, ValueError):
            continue
        if 1 <= pages <= 20:
            candidates.append((path.resolve(), pages))
    rng = random.Random(seed)
    selected = []
    for low, high in ((1, 4), (5, 8), (9, 12), (13, 16), (17, 20)):
        bucket = [item for item in candidates if low <= item[1] <= high]
        if bucket:
            selected.append(rng.choice(bucket))
    remaining = [item for item in candidates if item not in selected]
    rng.shuffle(remaining)
    selected.extend(remaining[:max(0, 5 - len(selected))])
    if len(selected) != 5:
        raise ValueError("Need at least five distinct PDF files with 1..20 pages")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="deepdoc-uat:cpu")
    parser.add_argument("--seed", type=int, default=20261022)
    args = parser.parse_args()
    # Fail before creating evidence if Docker cannot be reached.
    docker("info", "--format", "{{.OSType}}/{{.Architecture}}")
    selected = select_samples(args.dataset, args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {"seed": args.seed, "image": args.image,
                "scope": "Five samples, 1..20 pages only; not a 353-page qualification",
                "samples": [{"path": str(path), "pages": pages} for path, pages in selected]}
    (args.output / "samples.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    name = "deepdoc-uat-smoke-" + secrets.token_hex(4)
    env = dict(os.environ, VOCR_API_KEY=secrets.token_urlsafe(32))
    results = []
    created = False
    try:
        docker("run", "--detach", "--name", name, "--network", "none", "--memory", "8g",
               "--memory-swap", "8g", "--cpus", "4", "--pids-limit", "256", "--init",
               "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=1073741824,mode=1777",
               "--env", "VOCR_API_KEY", args.image, env=env)
        created = True
        deadline = time.monotonic() + 300
        health = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).read().decode())"
        while True:
            try:
                if json.loads(docker("exec", name, "python", "-c", health, stderr=subprocess.DEVNULL))["model_loaded"]:
                    break
            except (subprocess.CalledProcessError, ValueError):
                if time.monotonic() > deadline or docker("inspect", "--format", "{{.State.Running}}", name).strip() != "true":
                    raise RuntimeError("Container failed readiness; see container.log")
            time.sleep(2)
        for index, (path, pages) in enumerate(selected, 1):
            remote = f"/tmp/sample-{index}.pdf"
            subprocess.run(["docker", "cp", str(path), name + ":" + remote], check=True, capture_output=True)
            code = f'''import json, os, pathlib, urllib.request
boundary = "uat-smoke-boundary"
data = ("--"+boundary+'\\r\\nContent-Disposition: form-data; name="file"; filename="sample.pdf"\\r\\nContent-Type: application/pdf\\r\\n\\r\\n').encode()+pathlib.Path({remote!r}).read_bytes()+('\\r\\n--'+boundary+'--\\r\\n').encode()
req = urllib.request.Request("http://127.0.0.1:8000/api/v1/ocr/pdf", data=data, headers={{"Authorization":"Bearer "+os.environ["VOCR_API_KEY"], "Content-Type":"multipart/form-data; boundary="+boundary}})
with urllib.request.urlopen(req, timeout=3700) as response:
    print(json.dumps({{"status": response.status, "prediction": json.load(response)}}, ensure_ascii=False))
pathlib.Path({remote!r}).unlink()
'''
            started = time.monotonic()
            response = json.loads(docker("exec", name, "python", "-c", code, timeout=3800))
            assert response["status"] == 200
            assert len(response["prediction"]["information"]) == 1
            assert len(response["prediction"]["information"][0]) == 13
            response["path"], response["pages"] = str(path), pages
            response["wall_seconds"] = round(time.monotonic() - started, 3)
            # cgroup peak includes all processes and tmpfs; cumulative since startup.
            response["container_peak_bytes_since_start"] = int(docker("exec", name, "cat", "/sys/fs/cgroup/memory.peak").strip())
            results.append(response)
            (args.output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print(f"PASS {index}/5 pages={pages} seconds={response['wall_seconds']} peak_bytes={response['container_peak_bytes_since_start']}", flush=True)
        state = json.loads(docker("inspect", name))[0]
        assert not state["State"]["OOMKilled"] and state["State"]["Running"]
        docker("exec", name, "python", "-c",
               "from pathlib import Path; assert not Path('/tmp/ocr-unused-output').exists(); assert not list(Path('/tmp').glob('ocr-request-*'))")
        report = {"passed": True, "network_mode": state["HostConfig"]["NetworkMode"],
                  "memory_limit": state["HostConfig"]["Memory"], "memory_swap": state["HostConfig"]["MemorySwap"],
                  "nano_cpus": state["HostConfig"]["NanoCpus"], "image_id": state["Image"],
                  "image_bytes": int(docker("image", "inspect", "--format", "{{.Size}}", args.image)),
                  "note": "RAM peaks are cumulative cgroup peaks, not independent per-file peaks. Review results.json OCR values manually."}
        (args.output / "summary.json").write_text(json.dumps(report, indent=2))
    finally:
        if created:
            (args.output / "container.log").write_text(docker("logs", name, stderr=subprocess.STDOUT))
            subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)


if __name__ == "__main__":
    main()
