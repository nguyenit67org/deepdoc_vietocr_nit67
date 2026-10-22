# CPU UAT: build, transfer, run

## Contract and limits

- `POST /api/v1/ocr/pdf`: multipart file field `file`, Bearer `VOCR_API_KEY`.
- Response remains the current 13-field VBHC API; `receiverDate` is always empty.
- `GET /health`: no credentials, only `status`, `model_loaded`, `busy`.
- One Uvicorn worker and one admitted PDF request, including upload. Busy requests
  receive 503 and `Retry-After: 10`. Health remains available while processing.
- Maximum file size 100 MiB; total multipart body maximum 100 MiB + 64 KiB.
  Upload idle timeout 60 seconds, total upload deadline 300 seconds;
  inference cancellation requested after 3600 seconds.
- Cancellation is cooperative at render windows, layout chunks, detector pages and
  recognition batches. A native operation already running cannot be stopped instantly.
  The slot and temporary file remain owned until that operation exits. Render windows
  have a 120-second Poppler timeout. There is no job queue, persistence or resume API.
- Models stay loaded between requests. No tables, correction model, GLiNER, debug UI
  or retained output. Text inside detected table regions is omitted.
- Full PDF text/layout results accumulate in memory even though images are windowed.
  Upload size and page count do not guarantee bounded memory for abnormal page sizes.
- 8 GiB hard container memory limit (including /tmp tmpfs), swap disabled, 4 vCPU
  quota, 1 GiB tmpfs, 256 PIDs. OOM can terminate the OCR container; it is not configured
  to restart in a loop. These limits reduce, not eliminate, shared-host risk.

## 1. Existing model provenance

The original worktree is expected at `/home/nguyen/projects/deepdoc_vietocr_dh`.
`scripts/prepare_uat_context.py` verifies every artifact against the saved upstream
manifest before exporting. It copies only these runtime assets:

- `scratch/ocr-recognizers/models/vietocr_original_transformer`: checkpoint, config,
  pinned upstream source and its license. Manifest weight URL:
  `https://vocr.vn/data/vietocr/vgg_transformer.pth`.
- `onnx/det.onnx`.
- `~/.paddlex/official_models/PP-DocLayout_plus-L/inference.{json,pdiparams,yml}`.

The existing `fastocr/weight/transformerocr.pth` is NOT the same checkpoint: local
comparison found 134 vs 302 state-dict keys and unequal shared tensors. It is not used.
Upstream uses greedy decoding, FP32, original resize/vocabulary, max decode length
128. Only device and batching are deployment choices; `cnn.pretrained=False` avoids
an unnecessary ImageNet download since the full checkpoint contains the CNN.
Do not describe this as universally best accuracy. Retain source/checkpoint license
notices and verify distribution terms before sharing outside the approved company scope.

## 2. Prepare and build on WSL, not UAT

Run from the deploy worktree `/tmp/opencode/deepdoc-uat-cpu`. Paths below are for this
machine; substitute your own if cloning elsewhere. The original worktree and assets
must remain available. Git alone does not supply the external model assets.

```bash
uv run --no-project --python /home/nguyen/projects/deepdoc_vietocr_dh/.venv/bin/python python scripts/prepare_uat_context.py \
  --assets-root /home/nguyen/projects/deepdoc_vietocr_dh \
  --layout-dir /home/nguyen/.paddlex/official_models/PP-DocLayout_plus-L \
  --output /tmp/opencode/deepdoc-uat-build
```

The output must be a NEW directory; the script never deletes an existing context.
Build context was measured around 288 MB before final code changes, not image size.
Actual Windows drive D free space is about 39 GB; do not trust WSL's virtual 753 GB.
Check available real space during build/export. Never prune unrelated images/cache.

```bash
docker build --progress=plain -f /tmp/opencode/deepdoc-uat-build/deploy/Dockerfile \
  -t deepdoc-uat:cpu /tmp/opencode/deepdoc-uat-build
```

If Docker requires sudo, prefix Docker commands with `sudo`. Do not make its socket
world-writable. Docker access is effectively root access.

Dependencies are locked in `deploy/requirements.lock`, with CPU Torch/torchvision
explicitly installed from the CPU index. The image has no CUDA, MinerU, Surya or
GLiNER dependencies. Build-time network access is required; runtime must not need it.

## 3. Verify before export

Fast safety tests (fake inference; these do NOT prove real model inference):

```bash
uv run --no-project --python /home/nguyen/projects/deepdoc_vietocr_dh/.venv/bin/python python -m unittest discover -s test -p test_uat.py -v
```

Real offline integration tests, once Docker works:

```bash
uv run --no-project --python /home/nguyen/projects/deepdoc_vietocr_dh/.venv/bin/python python scripts/test_uat_image.py \
  --dataset /home/nguyen/projects/deepdoc_vietocr_dh/data/benchmark_demo/raw \
  --output /tmp/opencode/deepdoc-uat-evidence
```

The script creates and removes only its own uniquely named test container. It uses
`--network none`, the same resource limits, and samples five PDFs with seed 20261022,
trying one from each four-page bucket in 1..20. Empty buckets are filled from remaining
eligible files. It stores sample paths, responses, times, cumulative cgroup memory
peaks, image identity/size, and container logs outside the image/repo. Review OCR
values manually for obvious empty/garbled results. These are smoke tests, not an
accuracy benchmark. PDFs over 20 pages, including 353-page PDFs, are NOT qualified.

A summary is written only if all requests and cleanup checks succeed. Do not proceed
on OOM, container exit, missing model, attempted runtime download or schema failure.
If restarting a test, use a new evidence output directory.

## 4. Export and transfer

Only after tests pass, create a release directory on a drive with sufficient space:

```bash
mkdir -p /mnt/d/ocr-uat-release
docker image inspect deepdoc-uat:cpu --format '{{.Size}}'
set -o pipefail
docker save deepdoc-uat:cpu | gzip -1 > /mnt/d/ocr-uat-release/deepdoc-uat-cpu.tar.gz
cp deploy/compose.yaml deploy/.env.example /mnt/d/ocr-uat-release/
sha256sum /mnt/d/ocr-uat-release/deepdoc-uat-cpu.tar.gz
```

Save the printed checksum separately. Check both uncompressed image size and compressed
archive size before transfer: UAT has only about 14 GB free on the shared root disk.
Leave at least 4 GB free after loading; do not proceed if archive + image + this reserve
cannot fit. Existing Docker layers can share storage, but do not assume savings.
Do not keep a separate uncompressed `.tar` or transfer a venv/dataset.

Use WinSCP to transfer the archive, `compose.yaml`, and `.env.example` from Windows
`D:\ocr-uat-release` to a new UAT directory such as `/home/app/ocr-uat`.

## 5. UAT preflight and startup

On UAT, from `/home/app/ocr-uat`:

```bash
df -h / /home/app
sudo ss -ltnp 'sport = :8000'
sha256sum deepdoc-uat-cpu.tar.gz
sudo docker load -i deepdoc-uat-cpu.tar.gz
df -h /
```

Checksum must match WSL; port 8000 must be unused. Do not stop another service or
change its port to make room. The archive may be removed after successful load and
verification to reclaim space; keep the WSL release copy.

Create the key locally on UAT (do not send it to chat or commit it):

```bash
umask 077
cp .env.example .env
openssl rand -hex 32
nano .env
```

Replace `REPLACE_WITH_RANDOM_TOKEN` with the generated token. Then:

```bash
sudo docker compose -p deepdoc-uat -f compose.yaml config --quiet
sudo docker compose -p deepdoc-uat -f compose.yaml up -d --pull never
sudo docker compose -p deepdoc-uat -f compose.yaml ps
sudo docker compose -p deepdoc-uat -f compose.yaml logs --tail 80
curl --fail http://127.0.0.1:8000/health
sudo docker stats --no-stream
```

Health should report `ready`, `model_loaded: true`, `busy: false`. Docker health may
take one check interval to update. Verify the OCR container's 8 GiB limit and monitor
the existing services during the first short PDF. Stop OCR on OOM, repeated failures
or unexpected host pressure; do not automatically restart or enlarge limits.

## 6. Windows SSH tunnel and Postman

Enable the company's approved network/firewall access first. In Windows PowerShell:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18000:127.0.0.1:8000 app@IP_UAT
```

Keep that terminal open. Add `-p SSH_PORT` if needed. No OCR port is opened to the
network. If forwarding is administratively prohibited, request approval from the SSH
administrator; do not edit sshd/firewall policy on your own.

Postman:
1. `GET http://127.0.0.1:18000/health`.
2. `POST http://127.0.0.1:18000/api/v1/ocr/pdf`.
3. Authorization: Bearer Token, enter the UAT key.
4. Body: form-data, key `file`, type **File**, select a 1..2-page PDF.
5. Let Postman set Content-Type and boundary. Set request timeout high enough for
   CPU inference; use 0/no timeout for the initial controlled test and cancel manually
   if needed. Cancellation can wait for a native batch/render operation to finish.
6. Expect 200 + JSON, 401 for invalid key, 503 + Retry-After for a second busy request,
   413 for oversize, 422 for unreadable PDF. Do not blindly retry a long-running POST.

Direct access by company applications is a separate, later step: approve routing,
allowed clients, TLS and firewall policy before changing the loopback binding.

## 7. Stop, update, rollback

```bash
sudo docker compose -p deepdoc-uat -f compose.yaml stop
```

This stops only this Compose project. No prune, global Docker restart or other-service
changes are needed. Before an update, retain the previous image tag/ID and deployment
files and verify enough disk space. Use a unique version tag rather than overwriting
the only known-good tag. Set `OCR_IMAGE` in `.env` to that tag, then `up -d --pull never`.
Rollback by restoring the prior `OCR_IMAGE` and Compose/config files and running the
same command. Do not remove the previous image until the replacement is verified.
