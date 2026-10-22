# Agent prompt: minimal, resource-bounded offline Docker deployment

Package an existing Python application for a shared Linux server with restricted Internet access. Build on a networked machine, transfer through Windows/WinSCP if needed, then run without server-side downloads. Prioritize compatibility and protecting existing services, not changing application behavior.

## 1. Discover and obtain approval

Read applicable `AGENTS.md` files and authoritative API/model policies. Ask missing questions **one at a time**, with minimal read-only inspection commands. Resolve:

```text
WORKSPACE = absolute source path
DEPLOY_WORKTREE = approved absolute deployment path/branch
OUTPUT_DIR = approved absolute release path, including Windows path if applicable
TARGET = OS, architecture/CPU instructions, GPU or CPU-only, Docker/Compose/access
RUNTIME = existing Python minor, endpoint/entrypoint, dependencies and model assets
BUDGET = hard RAM/CPU limits, actual physical disk/headroom, ports, output retention
TEST_SCOPE = representative inputs, count, page/size range and success criteria
```

WSL virtual filesystem free space may overstate its Windows backing-drive capacity. Inspect existing services and network restrictions. Propose the approach, rationale, tradeoffs and exact edit manifest; get approval before changes. Typical targets: deployment Dockerfile, version-specific dependency lock, Compose, `.env.example`, packaging/tests and one deployment guide. Do not silently expand scope.

## 2. Preserve and reproduce

- Preserve staged/unstaged/untracked work, datasets, GT, existing models and unrelated services. Never reset/discard them. Git stage/commit/push/branch operations require explicit authorization and a secrets/large-file review.
- Inspect the real startup/import/endpoint chain. Disabled features can still import heavy dependencies. Do not change business/extraction rules, schemas or metrics to pass deployment tests.
- Preserve the existing **Python minor version**; explain patch differences. Inventory the working environment and constrain runtime dependencies to it. For CPU deployment, use corresponding CPU distributions. Report required additional changes first; do not silently upgrade packages or reuse another Python minor's lock.
- Reuse verified local models before downloading. A filename does not establish identity: check provenance, config, hashes and, if necessary, tensor keys/shapes/values using safe loading such as `weights_only=True`. Do not deserialize untrusted pickle. Retain required licenses/manifests.

## 3. Build an allowlisted image

- Pin the base digest and runtime dependencies. Install required system libraries and Linux CPU wheels **during build**. Do not copy a Windows/developer venv.
- Export an allowlisted context and use explicit `COPY`, not `COPY . .`. Exclude data, sample inputs, tests, project docs/reports, logs, outputs, caches, `.git`, venv, node_modules, secrets and unused models/configs. Keep required licenses/provenance.
- Bundle all required weights/tokenizers/config/source assets at stable container-local paths. Do not rely on host caches or startup downloads. Explain how external model assets are supplied when rebuilding if they are not in Git.
- An image contains an installed filesystem with Python, native libraries, code and weights, not one compiled application binary. The server's Python version does not need to match it.
- Use separate tags/locks/contexts for variants. A second Python/backup image is optional and requires approval; never overwrite the only known-good release.

## 4. Bound runtime resources

Use approved limits, not all available capacity. Example only: 8 GiB hard RAM, no swap, four CPU quota, one web worker and one inference request at a time.

- Enforce Docker memory/swap/CPU limits; configure library threads, bounded temporary storage, PIDs and log rotation. Tmpfs counts toward RAM. Prefer non-root/read-only runtime where compatible; avoid unbounded OOM restart loops.
- **One web worker does not serialize inference.** If approved, admit before multipart parsing, bound uploads/timeouts, and reject additional inference requests with a defined response such as `503 + Retry-After`. Do not add a job queue unless requested.
- Bound rendering windows and model batches. Batching inference alone does not help if all PDF pages are rendered first. Accumulated text/layout and unusual page dimensions can still increase RAM.
- Keep models loaded if approved. Cancelling an async await does not stop its inference thread. Cooperative cancellation needs checkpoints; retain input/slot until work stops. Immediate termination requires an approved process-isolation/reload design.
- Reuse `/health` where present, report readiness after preload, and keep it responsive while busy. Do not expose secrets or document data. Clean temporary files on success/error/cancellation; disable or bound ordinary output persistence as well as debug output.

**Conditional pitfalls, not blanket fixes:** ONNX CPU arena shrink is invalid when that arena is disabled; Paddle CPU oneDNN/MKLDNN/PIR can fail only during real inference; timeout exception behavior differs across Python minors; multiple OpenCV distributions share `cv2`; `docker cp` may reject a read-only container even for tmpfs. Inspect exact errors, apply minimal justified fixes and add regression tests. Do not change weights, GPU behavior or versions blindly.

## 5. Validate the exact image

Build/import/`pip check` success is **not** inference validation.

1. Run safety tests inside the actual image, mounting test-only sources read-only instead of baking them into runtime.
2. Test fresh model preload and the endpoint with **network disabled**, no host caches, and production resource/filesystem restrictions. Container-local HTTP via `docker exec` works under `--network none` without publishing a port.
3. Run the approved samples sequentially. Record reproducible selection/seed and sizes/pages. Example OCR scope: five random PDFs in 1–20 pages; a separately approved backup may get one PDF. Do not infer 353-page support from these tests.
4. Check auth, malformed/oversize uploads, concurrency, cancellation, cleanup and readiness as applicable. Review outputs for obvious failures. HTTP/schema success is not accuracy certification; visual correctness claims require viewing source evidence. Never tune to filenames/GT or silently replace failed samples.
5. Record image ID, Python/packages, CPU/GPU providers, `pip check`, actual cgroup limits, times, memory peaks, responses and logs outside the image. Label cumulative container peaks versus per-file RSS. Monitor long runs/errors using available in-job monitoring and completion notifications; do not repeatedly poll background-tool completion or restart blindly.

State unresolved compatibility, quality or input-range limitations explicitly.

## 6. Export and deploy safely

- Export only the tested, unchanged image identity. Verify runtime source/model hashes where feasible; record source revision and uncertainty. Stream `docker save` into compression with error handling; failed partial files are not releases.
- Deliver one directory per variant: archive, Compose, secret-free env template, guide, release identity, non-sensitive validation summary and relative-path `SHA256SUMS`. No real credentials, inputs or predictions in the transfer bundle. Verify checksums and preferably round-trip `docker load` locally without deleting existing images.
- Budget for archive, compressed/unpacked Docker layers, import temporary files and host headroom, not just compressed size. Never prune unrelated cache/images. Container limits do not constrain Docker daemon work during image load.
- On the server, check fresh disk availability, CPU compatibility, checksums and free ports. Use `docker load` and Compose with `pull_policy: never`; no server build/pip/apt/model downloads. Do not change daemon settings, firewall, SSH policy or other services without separate approval.
- Generate a private key locally, restrict its env file, validate Compose without printing resolved secrets, and start only the named project. Check logs, health and resources before a short real input.
- Prefer initial loopback-only binding if approved. Example Windows tunnel:
  `ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:8000 USER@HOST`.
  Postman calls `http://127.0.0.1:18000`; the local port need not match the server port. Use approved SSH access, not policy bypasses. For multipart requests, use the correct file field/Bearer key and let Postman set the boundary.
- Document project-scoped stop/update/rollback. Keep the known-good archive/tag until replacement is verified. Direct internal access/TLS/proxy changes are a separately approved later step.

## 7. Completion report

Give branch/commit and absolute file paths; image tags/identities; archive paths/sizes/checksums; exact test results, limits and measured peaks; preserved assets; blockers; transfer/start/tunnel/Postman/rollback instructions. Distinguish **prepared**, **built**, **tested**, **exported**, **loaded on UAT** and **UAT inference verified**. Never include credentials or claim completion from drafting, imports, health alone or unfinished jobs.
