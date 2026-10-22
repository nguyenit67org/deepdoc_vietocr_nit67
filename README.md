# DeepDoc CPU UAT deployment

Deployment branch for `POST /api/v1/ocr/pdf`, using upstream VietOCR VGG Transformer,
ONNX text detection and PP-DocLayout_plus-L. No table processing or retained documents.

- Runtime: `server.uat:app`, one worker, one PDF in flight, Bearer authentication.
- Primary image: Python 3.10 CPU, `deploy/Dockerfile.py310`; separately tagged
  Python 3.11 CPU backup uses `deploy/Dockerfile`.
- Limits: 8 GiB memory including tmpfs, no swap, maximum 4 vCPU.
- Build and offline deployment instructions: [deploy/README.md](deploy/README.md).
- Authoritative extraction contract: [docs/ocr_pipeline_benchmark_metrics.md](docs/ocr_pipeline_benchmark_metrics.md).
- Dataset, benchmark reports and old model binaries are absent from this branch's
  current tree, but remain in Git history and in `feature/extract-entity`.
- Models are exported from existing local assets into a separate allowlisted Docker
  context. They are not committed to this branch. No Windows venv is transferred.

Unit safety checks do not qualify real inference or resource usage. Only successful
container tests described in the deployment guide establish that evidence.
