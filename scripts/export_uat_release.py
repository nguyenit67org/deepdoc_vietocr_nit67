"""Export only a successfully tested, unchanged image; never include real secrets."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def verify_runtime_sources(repo, image):
    files = []
    for folder in ("module", "utils", "fastocr"):
        files.extend(path for path in (repo / folder).rglob("*")
                     if path.is_file() and not any(part in ("__pycache__", "weight") for part in path.parts)
                     and path.suffix != ".pyc" and not path.name.startswith(".env"))
    files.extend(repo / rel for rel in ("server/__init__.py", "server/schemas.py", "server/security.py",
                                       "server/uat.py", "conf/uat.yaml"))
    expected = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    code = '''import hashlib,json,pathlib
def digest(path):
    result=hashlib.sha256()
    with path.open("rb") as stream:
        while chunk:=stream.read(1024*1024): result.update(chunk)
    return result.hexdigest()
paths = ''' + repr(list(expected)) + '''
actual={rel:digest(pathlib.Path("/app")/rel) for rel in paths}
manifest_path=pathlib.Path("/app/models/manifest.json")
manifest=json.loads(manifest_path.read_text())
for rel,info in manifest.items():
    assert digest(pathlib.Path("/app")/rel)==info["sha256"],rel
print(json.dumps({"sources":actual,"models_manifest_sha256":digest(manifest_path)}))
'''
    actual = json.loads(subprocess.check_output(["docker", "run", "--rm", "--network", "none",
                        "--read-only", "--memory", "256m", "--cpus", "1", "--entrypoint", "python", image, "-c", code]))
    if actual["sources"] != expected:
        raise ValueError("Image runtime sources differ from the deployment worktree")
    return actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    report = json.loads((args.evidence / "summary.json").read_text())
    if not report.get("passed"):
        raise ValueError("Cannot export an unqualified image")
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image]))[0]
    if image["Id"] != report["image_id"]:
        raise ValueError("Image tag changed after testing; repeat tests before export")
    provenance = verify_runtime_sources(repo, args.image)
    args.output.mkdir(parents=True, exist_ok=False)
    variant = args.image.split(":")[-1]
    name = "deepdoc-uat-" + variant + ".tar.gz"
    partial = args.output / (name + ".partial")
    process = subprocess.Popen(["docker", "save", args.image], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with partial.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=1, mtime=0) as compressed:
            shutil.copyfileobj(process.stdout, compressed, 4 * 1024 * 1024)
        error = process.stderr.read().decode()
        if process.wait() != 0:
            raise RuntimeError("docker save failed: " + error)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            process.wait()
        raise
    partial.rename(args.output / name)
    shutil.copy2(repo / "deploy/compose.yaml", args.output / "compose.yaml")
    template = (repo / "deploy/.env.example").read_text().replace("deepdoc-uat:py310-cpu", args.image)
    (args.output / ".env.example").write_text(template)
    shutil.copy2(repo / "deploy/UAT_VI.md", args.output / "DEPLOY.md")
    shutil.copy2(repo / "deploy/README.md", args.output / "TECHNICAL.md")
    shutil.copy2(args.evidence / "summary.json", args.output / "validation-summary.json")
    metadata = {"image": args.image, "image_id": image["Id"], "reported_image_bytes": image["Size"],
                "archive": name, "archive_bytes": (args.output / name).stat().st_size,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip(),
                "runtime_source_sha256": provenance["sources"],
                "models_manifest_sha256": provenance["models_manifest_sha256"],
                "qualification": "primary: five PDFs" if report["sample_count"] == 5 else "backup: one PDF smoke test"}
    (args.output / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
    sums = []
    for path in sorted(args.output.iterdir()):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(4 * 1024 * 1024):
                    digest.update(chunk)
            sums.append(f"{digest.hexdigest()}  {path.name}")
    (args.output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
