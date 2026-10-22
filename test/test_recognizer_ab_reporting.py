import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_recognizer_ab import SMOKE_DOCUMENTS, smoke_is_valid
from scripts.summarize_recognizer_ab import in_field_scope, metrics_from_scored_cells
from scripts.summarize_recognizer_timing import primary_file_timings, summarize_models


class AbReportingTests(unittest.TestCase):
    def test_handwriting_and_stamp_are_independent_field_flags(self):
        record = {"metadata": {"handwritten_fields": {"value": ["code", "documentDate"]},
                               "stamp_affected_fields": {"value": ["documentDate", "signer"]}}}
        self.assertTrue(in_field_scope(record, "documentDate", "handwriting_and_stamp"))
        self.assertTrue(in_field_scope(record, "code", "handwriting_without_stamp"))
        self.assertTrue(in_field_scope(record, "signer", "stamp_without_handwriting"))
        self.assertTrue(in_field_scope(record, "title", "neither_labeled_flag"))
        self.assertFalse(in_field_scope({}, "title", "neither_labeled_flag"))

    def test_full_gate_requires_exact_smoke_set_config_code_and_gt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = dict(status="completed", is_recognizer_candidate=True, documents=list(SMOKE_DOCUMENTS))
            (root / "manifest.json").write_text(json.dumps(manifest))
            config = {"backend": "synthetic"}
            fingerprint = dict(recognizer_config=config, dependencies={"code": "hash"}, labels={doc: "GT" for doc in SMOKE_DOCUMENTS})
            (root / "run_fingerprint.json").write_text(json.dumps(fingerprint))
            self.assertTrue(smoke_is_valid(root, config, fingerprint))
            self.assertFalse(smoke_is_valid(root, {"backend": "changed"}, fingerprint))
            self.assertFalse(smoke_is_valid(root, config, {**fingerprint, "dependencies": {}}))
            manifest["documents"] = list(SMOKE_DOCUMENTS)[:-1]
            (root / "manifest.json").write_text(json.dumps(manifest))
            self.assertFalse(smoke_is_valid(root, config, fingerprint))

    def test_primary_file_timing_retains_total_and_labels_page_mean(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "fastocr_control"
            (folder / "cache/doc").mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps(dict(status="completed", documents=["doc"])))
            (folder / "preflight.json").write_text(json.dumps(dict(documents=[dict(document_id="doc", selected_pages_0based=[0, 253]) ])))
            (folder / "recognizer_config.json").write_text(json.dumps(dict(backend="fastocr")))
            (folder / "cache/doc/diagnostic.json").write_text(json.dumps(dict(crop_count=65, recognition_seconds=2.5)))
            (folder / "pipeline_config.json").write_text(json.dumps(dict(ocr=dict(fastocr_weight_path="weight", fastocr_base_config="vgg_seq2seq", fastocr_max_batch_size=128))))
            rows = primary_file_timings(root, ["fastocr_control", "not_completed"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["selected_pages"], 2)
            self.assertEqual(rows[0]["recognition_adapter_wall_seconds"], 2.5)
            self.assertEqual(rows[0]["mean_recognition_seconds_per_selected_page"], 1.25)
            self.assertNotIn("page_seconds", rows[0])
            self.assertFalse(rows[0]["includes_page_cache_decode"])
            self.assertFalse(rows[0]["includes_adapter_ipc"])

    def test_model_page_mean_is_weighted_by_selected_pages(self):
        rows = [dict(model="synthetic", selected_pages=1, crop_count=10, recognition_adapter_wall_seconds=10),
                dict(model="synthetic", selected_pages=9, crop_count=90, recognition_adapter_wall_seconds=9)]
        summary = summarize_models(rows)[0]
        self.assertEqual(summary["mean_recognition_seconds_per_selected_page"], 1.9)
        self.assertEqual(summary["mean_recognition_seconds_per_file"], 9.5)
        self.assertEqual(summary["selected_pages"], 10)

    def test_cached_cell_aggregation_matches_authoritative_benchmark(self):
        import benchmark as b
        records = [dict(document_id=str(i), ground_truth={"title": gt}, prediction={"title": pred})
                   for i, (gt, pred) in enumerate((("abc", "abc"), ("abc", "bad"), ("abc", ""),
                                                   ("", "invented"), ("", ""), ("N/A", "ignored")))]
        cells, fields = b.evaluate_records(records)
        selected = [row for row in cells if row["field_name"] == "title"]
        actual = metrics_from_scored_cells(selected)
        expected = next(row for row in fields if row["field_name"] == "title")
        for key, value in actual.items():
            self.assertEqual(value, expected[key], key)


if __name__ == "__main__":
    unittest.main()
