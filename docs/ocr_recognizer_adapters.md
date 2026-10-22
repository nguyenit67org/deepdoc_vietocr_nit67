# Swappable OCR recognition backends

## Scope

Recognition is independent of detection and crop geometry. FastOCR remains the default. Four opt-in adapters share the `TextRecognitionBackend` protocol in `module/ocr/base.py`:

```text
list[BGR uint8 HWC crop] -> (list[(text, pipeline_score)], elapsed_seconds)
```

One result per crop, in input order, including empty text. No detector calls, bbox recropping, field-specific rules, spelling correction or GT input. Adapter-specific resizing/normalization is recorded, not shared across incompatible models.

`module/ocr/recognizers/__init__.py` is the lazy factory/registry. Each backend has its own module; optional dependencies load only when selected. `BatchedRecognizer` centralizes validation, locking, score policy, order-preserving CUDA OOM splitting and legacy predictor compatibility.

## Backends and licensing

| Backend | Checkpoint | Runtime | License note |
|---|---|---|---|
| `fastocr` | Existing VGG-Seq2Seq | Existing PyTorch | Existing baseline, unchanged default |
| `ocrdoc_onnx` | OcrDoc Run 6 `recognition.onnx` | ONNX CUDA; CPU optional | Card declares weights Apache-2.0 |
| `vietocr_onnx` | vudang449 handwriting encoder/decoder | ONNX CUDA; CPU optional | Card declares Apache-2.0 |
| `htr_convtext` | `hands-vnondb.pth`, EMA weights | PyTorch CUDA, isolated optional timm dependencies | HF card says Apache-2.0, GitHub LICENSE says GPL-3.0; clarification pending |
| `senocr` | SenOCR-Vi merged FP32 | PyTorch CUDA, isolated Transformers 5.0 worker | Apache-2.0 according to card/LICENSE |

All four candidates are approved for swap-and-play internal testing. Do not label HTR-ConvText commercially cleared or bundle its upstream sources/weights into a shared distribution until the license conflict is resolved. Public weights do not settle training-data rights. License notes are not legal clearance.

## Download and optional runtime setup

Run from the repository root using its existing `.venv` via `uv run python`. Weights/source revisions are pinned in `conf/recognizers/catalog.json`; third-party weights and cloned sources stay under ignored `scratch/ocr-recognizers/`.

```bash
uv run python scripts/download_recognizer_models.py
uv pip install --python .venv/bin/python --target scratch/ocr-recognizers/python-deps --no-deps -r conf/recognizers/requirements-htr.txt
uv pip install --python .venv/bin/python --target scratch/ocr-recognizers/senocr-deps -r conf/recognizers/requirements-senocr.txt
```

Do not upgrade baseline Transformers to install SenOCR. Its config starts a persistent **local** worker with the separate dependency directory on `PYTHONPATH`; the parent pipeline keeps baseline dependencies. No external inference API is used. JSONL IPC sends lossless temporary crop PNG paths and receives raw recognition details. The worker is closed on success/error/process exit; timeout/errors are explicit, not silent model fallback.

The downloader creates `download_manifest.json` with revision, license note, file hashes and byte sizes. Actual inference sources:

- OcrDoc: ONNX graph, charset and published preprocessing. Export output has 230 classes: CTC blank + 228 dictionary characters + appended space. Height 48, fixed width 640 in the experiment config, aspect-preserving resize capped at width, normalized zero padding. Verify color/preprocessing assumptions before attributing model errors, especially on colored stamps; model card does not fully specify a reference Python preprocessing pipeline.
- VietOCR: published ONNX graphs and vocabulary, native-width per-image resize to height 32, greedy autoregressive decoding. No unvalidated encoder padding across images. Raw confidence and token-limit flags are retained.
- HTR: pinned HF source, vocabulary extracted from its dataset file as data, strict EMA state loading. Checkpoint is loaded with `weights_only=True` plus explicit NumPy metadata allowlist, not unrestricted pickle loading. Upstream generic `model` package is namespaced; one absolute import is translated to relative **in memory**, leaving downloaded source unchanged. Height 64, max width 512, grayscale and white padding follow upstream evaluation.
- SenOCR: native Transformers 5.0 implementation, not incompatible legacy custom model Python from the model repository. Loading fails on missing/mismatched weights. FP32, fixed `OCR:` prompt, deterministic greedy generation and KV cache. Baseline environment remains Transformers 4.57. On this Turing GPU/runtime, `TORCH_DISABLE_NATIVE_JIT=1` is scoped to the worker to avoid an unsupported JIT/compiler path; CUDA execution remains enabled.

Reference sources cloned for inspection and their commits are recorded in `conf/recognizers/sources.json`. The OcrDoc project URL in its model card returned GitHub API 404; its public weights, dictionary and model card were downloaded successfully. Do not claim that unavailable project source was cloned.

## Plug into the current engine

Use the full JSON options from one file under `conf/recognizers/` as `ocr.recognizer` in the effective pipeline config. Example:

```yaml
ocr:
  det_backend: onnx
  recognizer:
    backend: ocrdoc_onnx
    model_dir: scratch/ocr-recognizers/models/ocrdoc
    device: cuda
    max_batch_size: 16
    width: 640
```

`get_ocr_engine(conf)` forwards this to `OCR(recognizer_config=...)`; detection and crop options remain separate. Omitting `ocr.recognizer` preserves the original FastOCR constructor and behavior. Do not change the shared default YAML merely to run a candidate benchmark.

Adapters also expose the existing `.detector.predict_batch(PIL_images)` / `.predict()` compatibility hook used by table and orientation code. Native confidences across families are not calibrated. SenOCR has no native confidence and `get_ocr_engine` rejects confidence-based page orientation for it. Table/orientation behavior with candidates is not validated by the cached benchmark, whose effective config disables these features. Use appropriate separate validation before enabling them.

## Scores, text and errors

- `__call__`: neutral `1.0` scores for every result, same as the FastOCR wrapper; downstream still filters empty text. This isolates recognizer identity from confidence-threshold changes.
- `last_details`: raw text, native confidence (`null` if unavailable), assembly text, pipeline score, truncation and preprocessing/decode metadata for the last call.
- Only CR/LF is joined to spaces for line assembly; raw output stays intact. No field-based cleanup or Unicode/benchmark normalization in adapters.
- No crop errors are discarded. Unknown inference errors and singleton OOM fail loudly; completed diagnostic documents have checkpoints for a verified resume.
- Token-limit hits remain visible in results. Native confidence thresholds, different decoding settings, precision changes or preprocessing variants must be labeled as separate experimental configurations.

## Control and candidate commands

Read `docs/ocr_pipeline_benchmark_metrics.md` and the end-to-end plan in `docs/ai-sessions/2026-10-15-ocr-recognizer-ab-plan.md` first. Do not run full inference over 2.249 pages for this experiment.

After interface changes, create a new full FastOCR control with the fixed cache. `--allow-recognizer-integration` permits only the three approved old OCR interface/factory files to differ from the prior cache run, records old/new hashes, and never permits extraction/assembly drift:

```bash
uv run python scripts/check_cached_ocr_equivalence.py \
  ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015 \
  ocr-collab/artifacts/<new_control> \
  --crop-cache ocr-collab/artifacts/cached_ocr_equivalence_20261015 \
  --allow-recognizer-integration
```

Candidates require a completed exactly equivalent FastOCR control with matching current OCR/pipeline code and GT. Model identity may differ; source cache geometry, hashes and the FastOCR source weight guard still remain checked.

```bash
uv run python scripts/check_cached_ocr_equivalence.py \
  ocr-collab/artifacts/evidence_full_inference_title_footnote_fix_20261015 \
  ocr-collab/artifacts/<new_candidate> \
  --crop-cache ocr-collab/artifacts/cached_ocr_equivalence_20261015 \
  --integration-control ocr-collab/artifacts/<completed_control> \
  --recognizer-config conf/recognizers/ocrdoc.json
```

Start with the five mandatory smoke documents in the plan using repeated `--document-id`, then run all 100 documents / 183 pages / 6.619 crops if contract checks pass. Candidates are allowed to differ in text/KIE; a smoke pass does not mean better quality.

The sequential runner automates these gates without competing GPU jobs:

```bash
uv run python scripts/run_recognizer_ab.py ocr-collab/artifacts/recognizer_ab_20261015 --stage all
```

After completed candidate runs, use `scripts/summarize_recognizer_ab.py <control_dir> <new_comparison_dir> --candidate <candidate_dir>` (repeat `--candidate`) for the experiment log, all changed cells, review-pending regressions/improvements, resource timing tables and field-level metadata strata. Metadata strata are not line-level handwriting/stamp labels or recognition CER.

Use background jobs for long runs and avoid concurrent model jobs on the same GPU when measuring latency. `--resume` accepts only an incomplete output directory with a matching fingerprint of code, model/config/cache manifests, GT and package versions. It restores completed per-document checkpoints, not partially processed pages. Do not edit code/config/dependencies underneath an active run. Changed fingerprints require a new output directory.

### Timing per file and average per page

User clarified that the requirement is **average OCR time per page**, not measuring individual pages. No extra inference/profiling pass is needed. Preserve primary cross-page batching and use the existing measured recognition-adapter wall time in `cache/<document_id>/diagnostic.json`:

- Per file: measured document recognition seconds; mean seconds/page = document recognition seconds / selected pages in that document.
- Per model: mean seconds/page = **sum document recognition seconds / sum selected pages**, not the unweighted mean of file ratios. For a complete run the denominator is 183 pages, not all 2.249 PDF pages.
- Report model load separately. Recognition-adapter time excludes initial model load and source page-cache decode, but includes adapter preprocessing/postprocessing and IPC where applicable; it is not isolated GPU kernel time.
- These page figures are throughput-style averages from batching, not measured individual-page latency. Primary-run cold-start effects remain in the measured document times; no separate warmup is claimed.

```bash
uv run python scripts/summarize_recognizer_timing.py \
  ocr-collab/artifacts/recognizer_ab_20261015 \
  ocr-collab/artifacts/recognizer_ab_20261015/timing_summary
```

Outputs: `primary_file_timing.csv` and `model_timing_summary.csv`, with document/page/crop counts, absolute recognition times, page averages, crop throughput and model-load time. The exporter reads completed runs only, supports repeated `--model`, never loads models and never changes inference artifacts. During an ongoing experiment its manifest states exactly which completed models were exported; rerun into a new output directory after all models finish.

The previously proposed separate page-call profiling pass was cancelled after this clarification; do not launch it.

Artifacts are **hybrid diagnostics**, not full inference: non-selected pages retain baseline OCR. The output keeps recognition/assembly evidence per page, raw recognizer details, diagnostic predictions, comparisons and scored `evaluation/{baseline,reassembly,candidate}/` tables. Source traces are provenance only; old full-inference resource measurements are not assigned to the new run. Recognition latency includes adapter/IPC work, not pure GPU kernel time. Evaluation reports do not create recognition CER without transcription GT.

Tests:

```bash
uv run python -m unittest discover -s test -p test_recognizer_adapters.py
uv run python -m unittest discover -s test -p test_cached_ocr_equivalence.py
```

## Add or update a recognizer

1. Implement a separate `BatchedRecognizer` subclass with model-native preprocessing and ordered `RecognitionResult` output.
2. Add a lazy registry entry, pinned downloadable assets, a config and optional isolated runtime requirements.
3. Add CPU/mock contract tests and real GPU smoke; record sources, license, precision, prompt/decoding and any compatibility transformations.
4. Revalidate FastOCR control after shared code changes; benchmark new configuration in a fresh artifact directory.

Do not modify extraction, GT or model-specific rules to make a recognizer appear better. Routing, annotation, fine-tuning and detector changes require separate experimental scope.

## Nôm Tesseract with optional Vietnamese spell correction

For the newer direct-pytesseract **selected-pages-only** experiment, see the
section below; the historical hybrid scope does not apply to that runner.

Approved source wrapper is `nom.doc.stages.OCR` at Nôm revision
`2c99458ff55d7aa6b8c97398e2f0b1282efbcb73`. The documented
`nom.doc.ocr.TesseractOCR` was absent from both the inspected source and PyPI
wheel; the user explicitly approved the actual stage wrapper instead.

- `nom_tesseract` lazy backend: `module/ocr/recognizers/nom_tesseract.py`.
- Configurations: `conf/recognizers/nom_tesseract_{raw,spell}.json`.
- Tesseract 5.5.1 CPU, `vie` from pinned `tessdata_best`, PSM 6 / OEM 1,
  OpenMP thread cap 1. Each crop invokes one native process; parent batching
  is not native Tesseract GPU batching. No external deskew/resize/fallback.
- Raw branch calls `OCR.run(Context(...))`. The corrected branch is forbidden
  to re-run OCR and reads identical image/policy/text-hashed cached raw strings.
- Spell branch uses upstream `HFDiacriticModel.predict_batch`, checkpoint
  `nrl-ai/vn-spell-correction-base` revision
  `ba1e57fc3bacdfb22bfa20b19db7182a6d1b0b6b`, CUDA FP32, batch cap 16,
  greedy beams 1, input/output length cap 512, native heading retry enabled.
  Input truncation is recorded. Generated EOS/token IDs are not exposed by
  upstream, so output truncation is not independently observable.
- Both return neutral assembly score 1.0 and preserve empty crops, raw OCR,
  corrected text, original OCR time and amortized correction batch time.
  No field-specific spelling protection, confidence gates, GT corrections,
  word splitting or production default changes are introduced.
- Source, model and rootless native runtime live under
  `scratch/ocr-recognizers/models/nom_tesseract/`; isolated pytesseract 0.3.13
  is under `scratch/ocr-recognizers/nom-deps/`. Baseline dependencies and system
  packages remain unchanged. The source export must exist before running
  `scripts/download_nom_tesseract.py`; its asset manifest verifies subsequent
  reuse and inference.

Run `scripts/run_nom_recognizer_ab.py <new_root>` for a fresh exact FastOCR
control, mandatory five-document smoke, raw/corrected full runs and reporting.
`scripts/monitor_recognizer_job.py` supervises commands with live process,
checkpoint/log and GPU health records every 40 seconds. Failures stop the
runner rather than silently changing config or falling back to another model.

`scripts/report_nom_recognizer_ab.py` verifies all 6,619 paired raw inputs,
exports crop-level text changes and file/page timing, and writes `REPORT.md`.
The corrected harness run measures correction **only**, including cache/IPC;
report raw OCR and correction separately and sum them explicitly for the
two-stage cost. That sum is not separately measured fused online latency.

## Direct pytesseract, full PSM sweep, selected pages only

`pytesseract_direct` in `module/ocr/recognizers/pytesseract_direct.py` uses
`pytesseract.image_to_string` directly, not Nôm. Config:
`conf/recognizers/pytesseract_vie.json`. It reuses the pinned rootless Tesseract
5.5.1 and `tessdata_best/vie` assets, but no correction model or spelling stage.
`vie` is the installed Vietnamese traineddata name; `vi`/`vn` are not alternate
models. OEM 1 selects LSTM; full PSM configurations are 6 (text block),
7 (single line), and 13 (raw line). All three configurations run every fixed
crop, not a pilot-selected winner.

Preprocessing: convert to RGB and add a 10px white border, without resizing,
thresholding, deskew, red removal, field-aware routing, or text correction.
Each batch dispatches up to four native CPU calls with `OMP_THREAD_LIMIT=1`.
Ordered neutral-score outputs and raw strings are preserved. Memoization is
keyed by input pixels and the complete policy, including PSM and pinned assets;
cache hits and original call times are recorded separately. Parallel call-time
sums are not wall times.

The dedicated runner deliberately **does not use the historical hybrid
harness**. It supplies KIE with blocks from only the 183 selected physical pages,
leaving all unselected page slots empty to preserve physical indices. No OCR or
blocks from the other PDF pages are supplied to extraction. FastOCR and Nôm raw
controls replay their saved selected-page blocks under this same scope. Previous
hybrid scores must not be compared directly against these scores.

```bash
uv run python scripts/monitor_recognizer_job.py \
  --log /tmp/opencode/pytesseract-full-psm6713-20261020.log \
  --progress-root ocr-collab/artifacts/pytesseract_selected_pages_20261020 \
  -- uv run python scripts/run_pytesseract_selected_pages.py \
  ocr-collab/artifacts/pytesseract_selected_pages_20261020
```

Resume is automatic only for matching fingerprints, including code, config,
GT, selection, source caches and runtime assets; no silent fingerprint bypass.
Do not edit these dependencies during a run. Per-document recognition-adapter
wall times come from the actual full configuration run, not extra timing-only
passes. Weighted time/page uses 183 selected pages, not the full PDF page count.

Completed 2026-10-20: `ocr-collab/artifacts/pytesseract_selected_pages_20261020/REPORT.md`.
All three PSM runs cover 100 documents / 183 selected pages / 6,619 parent crops.
Document Pass: PSM6 19/100, PSM7 20/100, PSM13 11/100. Same-scope saved-block
controls: FastOCR 40/100, Nôm raw 17/100. These scores are selected-pages-only,
not reused historical hybrid predictions. PSM13 has the highest documentDate
F1 among these three (60.93%), despite the lowest overall Document Pass.
Actual adapter wall seconds/selected page: 2.704 / 2.530 / 2.292 for PSM6/7/13.
Each run recorded six cross-batch raw-cache hits, plus within-batch deduplication;
these are memoized-adapter throughput figures, not independent uncached latency.
`validation.json` verifies five cohorts, 500 unique per-document trace paths,
selected-only physical-page evidence, and 1,061 unchanged protected inputs.
