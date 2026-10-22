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

## Python 3.10 primary: pending real-image validation

- Planned tag: `deepdoc-uat:py310-cpu`, Python 3.10.22 (developer venv: 3.10.12).
- Runtime dependency versions constrained to existing venv versions, with GPU Torch/
  Torchvision and Paddle replaced by same-version CPU distributions.
- Five reproducible PDFs selected with seed 20261022: 2, 5, 9, 16 and 17 pages.
- No statement of successful deployment, inference or RAM peak for this image until
  its own container tests have completed. PDFs longer than 20 pages are not qualified.

## Source-level tests

The remaining deployment branch test suite passed on the existing developer venv:
117 tests and 35 subtests passed, one test skipped. This evidence is separate from
container-native tests and does not replace them.

## UAT status

No deployment or service/firewall/Docker-daemon modifications have been made on UAT.
UAT CPU instruction support, available disk at load time, native compatibility and
company SSH-forwarding policy must still be checked on that host.
