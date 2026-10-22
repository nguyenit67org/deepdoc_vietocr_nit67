# Experimental layout-guided red removal

Enable `remove_red.enabled` in pipeline configuration (default: false).
The shared page-chunk path supports PDF, PDF-group and image-group routes.
Layout runs on the original preprocessed image. No extra layout pass or PDF
rewrite is performed. Every page is scanned for red; only merged red ROIs
are detected/recognized before the normal table/page OCR stages.

## Conservative V1 policy

- Small/faint red is scanned independently of layout and V5 recovery thresholds.
- Probe limits apply per page; skipped ROIs remain unchanged.
- Urgency/security phrases, role/name-like text, unreadable and uncertain
  regions remain unchanged. No filename, name dictionary or GT lookup is used.
- Cleanup is only authorized by the current heuristic for compact `seal`
  regions with recognized organization text and no sensitive/name-like text.
  This is NOT proof of legal-stamp semantics. OCR/layout errors can still
  cause classification errors; keep disabled until full-inference A/B review.
- Non-organization OCR lines crossing an authorized region are protected.
- The opaque-image V5 BGR/HSV/Lab cleaner and dense-stroke recovery produce a
  candidate image. Final writes are restricted to cleanup mask minus keep
  mask, AFTER recovery. Input pixels and image geometry are never mutated.
- Any processing error preserves original images and orientation OCR caches.
  Changed pages invalidate those caches; unchanged pages reuse them.

## Configuration and diagnostics

`max_regions_per_page`, `max_probe_area_ratio` bound additional OCR work;
`padding` expands ROIs/protected lines. `dense_threshold`, `dark_red_max`,
`min_black_neighbors` control V5 recovery, not semantic protection.

Debug mode saves `page_N_red_before.png`, `page_N_red_after.png`, keep/cleanup
mask PNGs and a JSON report. Structured debug exposes reports with ROI
decisions, original probe text/coordinates, red/changed pixel and crop counts.
The `seconds` report is a scan-to-output wall span including shared batch
work, NOT additive exclusive per-page CPU/GPU time. Use full pipeline
wall-clock/resource measurements for A/B performance comparisons.

Run unit/integration tests via:

```bash
uv run --no-project .venv/bin/python -m unittest discover -s test -p 'test_red_removal.py'
```

Pixel-parity tests use the standalone source when available. Full inference
validation must use separate baseline/candidate artifacts, unchanged GT,
and the current `docs/ocr_pipeline_benchmark_metrics.md` contract. No extraction
rules, API schema or ground truth are changed by this feature.
