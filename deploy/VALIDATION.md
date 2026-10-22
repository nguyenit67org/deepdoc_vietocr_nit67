# UAT image validation

## Python 3.11 backup: passed limited qualification

- Tag: `deepdoc-uat:py311-cpu`.
- Tested image identity: `sha256:db60e956a1d79451f51f036cefcb44e0ad7f97c4d274f7e7626a9e6e871d4997`.
- Python: 3.11.17. Torch 2.13.0+cpu, Paddle CPU 3.3.0; no CUDA runtime/providers.
- Startup and one two-page PDF completed with network disabled, read-only root and
  8 GiB/no-swap/four-CPU Docker limits. HTTP 200, one object with 13 fields.
- Wall time: 32.239 seconds. Whole-container peak since startup: 1,507,151,872 bytes
  (about 1.40 GiB), including the container-local HTTP test client and temp files.
- `pip check` passed. Temporary request directory and persistent output absence checked.
- 16 deployment safety tests passed inside this exact image, using a read-only test
  source mount, no network and the same resource limits. Tests are not baked into it.
- Evidence: `/tmp/opencode/deepdoc-uat-evidence-py311-v4/{summary.json,results.json,samples.json,container.log,pip-freeze.txt}`.
- Backup archive exported and SHA-256 verified at
  `D:\ocr-uat-release\py311-backup\deepdoc-uat-py311-cpu.tar.gz`: 1,132,564,934 bytes.
  The `/usr` and `/app` runtime directories alone occupy about 3.30 GB unpacked;
  the reported image/archive size is not the full Docker disk footprint.
- The backup archive was loaded back into local Docker successfully; its image
  identity remained exactly the tested identity above. No UAT access was involved.
- This is one-PDF smoke qualification only, not a five-file qualification or accuracy
  benchmark. OCR/extraction quality is not certified by HTTP/schema success.

Earlier failed test evidence is retained at `deepdoc-uat-evidence-py311`, `-v2`, `-v3`:
test file transfer into a read-only container was corrected, CPU MKLDNN was disabled
after a real Paddle PIR/oneDNN failure, and an invalid ONNX disabled-arena shrink request
was removed. No model weights, GT or extraction rules were changed for these fixes.

## Python 3.10 primary: passed five-file offline qualification

- Tag: `deepdoc-uat:py310-cpu`, Python 3.10.22 (developer venv: 3.10.12).
- Tested image identity: `sha256:531d41895ca94358d6e192393dfac6d61abb0fc5fe88a7f87d773bf6194223a7`.
- Runtime dependency versions constrained to existing venv versions, with GPU Torch/
  Torchvision and Paddle replaced by same-version CPU distributions.
- Five reproducible PDFs selected with seed 20261022: 2, 5, 9, 16 and 17 pages.
- All five returned HTTP 200 and the 13-field schema with meaningful, nonempty text.
  This is smoke qualification, not GT-based accuracy certification. PDFs longer than
  20 pages, including 353-page PDFs, remain unqualified.
- 16 deployment safety tests passed inside this exact image, with no network,
  read-only root and the same resource limits. No pytest/test sources are baked in.
- No CUDA Torch/Paddle or CUDA ONNX provider; `pip check` passed.
- Limits verified both in Docker configuration and actual cgroup v2 files:
  memory.max=8589934592, memory.swap.max=0, cpu.max="400000 100000".
- Temporary file cleanup and no persistent output directory verified after all files.
- Evidence: `/tmp/opencode/deepdoc-uat-evidence-py310/{summary.json,results.json,samples.json,container.log,pip-freeze.txt}`.
- The shared two-page sample returned identical 13-field values on Python 3.10 and
  Python 3.11. This single-case consistency check is not a broader accuracy claim.
- Reported image bytes: 1,099,507,108. `/usr` plus `/app` occupy about 3.16 GB unpacked;
  Docker may keep compressed layers as well. Budget for archive, extraction and
  Docker storage, not only the image size reported by its API.

| PDF pages | Wall seconds | Cumulative whole-container peak GiB |
| --- | --- | --- |
| 2 | 37.136 | 1.88 |
| 5 | 124.133 | 2.31 |
| 9 | 198.024 | 2.31 |
| 16 | 163.722 | 2.33 |
| 17 | 421.329 | 2.60 |

Total file-request wall time: 944.344 seconds. Maximum observed cgroup peak:
2,793,594,880 bytes (about 2.60 GiB), including the in-container HTTP test client.
Peaks are cumulative since startup, not independent per-file process RSS. Timings
are WSL measurements, not UAT performance guarantees. Startup time is separate.

## Source-level tests

The remaining deployment branch test suite passed on the existing developer venv:
117 tests and 35 subtests passed, one test skipped. This evidence is separate from
container-native tests and does not replace them.

## UAT status

No deployment or service/firewall/Docker-daemon modifications have been made on UAT.
UAT CPU instruction support, available disk at load time, native compatibility and
company SSH-forwarding policy must still be checked on that host.
