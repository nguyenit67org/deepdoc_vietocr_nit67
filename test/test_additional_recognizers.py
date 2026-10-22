import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch

from module.ocr.recognizers.akaocr import AkaOcrRecognizer
from module.ocr.recognizers.base import BatchedRecognizer
from module.ocr.recognizers.source_utils import source_package
from module.ocr.recognizers.vietocr_original import VietOcrOriginalRecognizer


class AdditionalRecognizerTests(unittest.TestCase):
    def test_akaocr_restores_bgr_and_retains_neutral_and_native_scores(self):
        adapter = object.__new__(AkaOcrRecognizer)
        BatchedRecognizer.__init__(adapter)
        adapter.providers = ["CPUExecutionProvider"]
        adapter.recognizer = Mock(return_value=[("một", 0.7), ("", 0.0)])
        crop = np.full((4, 8, 3), [7, 11, 241], np.uint8)
        result, _ = adapter([crop, crop])
        np.testing.assert_array_equal(adapter.recognizer.call_args.args[0][0], crop)
        self.assertEqual(result, [("một", 1.0), ("", 1.0)])
        self.assertEqual(adapter.last_details[0]["confidence"], 0.7)
        self.assertEqual(adapter([])[0], [])

    def test_akaocr_none_and_missing_results_fail_instead_of_dropping_crops(self):
        adapter = object.__new__(AkaOcrRecognizer)
        BatchedRecognizer.__init__(adapter)
        adapter.providers = []
        for output in (None, []):
            adapter.recognizer = Mock(return_value=output)
            with self.assertRaisesRegex(ValueError, "one-result-per-crop"):
                adapter([Image.new("RGB", (3, 4))])

    def upstream_adapter(self):
        adapter = object.__new__(VietOcrOriginalRecognizer)
        BatchedRecognizer.__init__(adapter, 16)
        adapter.config = {"dataset": {"image_height": 32, "image_min_width": 1, "image_max_width": 512}}
        adapter.device = torch.device("cpu")
        adapter.model = Mock()
        adapter.max_seq_length = 128
        def process(image, *args):
            return torch.full((1, 3, 32, image.width), float(image.getpixel((0, 0))[0]))
        def translate(batch, model, **kwargs):
            identifiers = batch[:, 0, 0, 0].int().tolist()
            return np.array([[1, 4 + value, 2] for value in identifiers]), np.full(len(identifiers), 0.8)
        adapter.upstream = SimpleNamespace(process_input=process, translate=Mock(side_effect=translate))
        adapter.vocab = SimpleNamespace(decode=lambda tokens: chr(ord("A") + tokens[1] - 4))
        return adapter

    def test_upstream_width_buckets_restore_original_crop_order(self):
        adapter = self.upstream_adapter()
        images = [Image.new("RGB", (width, 10), (i, 0, 0)) for i, width in enumerate([20, 5, 20, 10])]
        result, _ = adapter(images)
        self.assertEqual(result, [(letter, 1.0) for letter in "ABCD"])
        self.assertEqual(adapter.upstream.translate.call_count, 3)
        self.assertEqual([r["metadata"]["resized_width"] for r in adapter.last_details], [20, 5, 20, 10])
        self.assertTrue(all(not r["truncated"] for r in adapter.last_details))

    def test_upstream_undefined_empty_confidence_and_truncation_are_explicit(self):
        adapter = self.upstream_adapter()
        adapter.upstream.translate = Mock(return_value=(np.array([[1, 4, 4]]), np.array([float("nan")])))
        adapter([Image.new("RGB", (3, 4))])
        self.assertIsNone(adapter.last_details[0]["confidence"])
        self.assertTrue(adapter.last_details[0]["truncated"])
        self.assertTrue(adapter.last_details[0]["metadata"]["native_confidence_nonfinite"])

    def test_optional_source_reuses_only_identical_package_code(self):
        name = "_test_additional_optional_package"
        old_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as temp:
                roots = [Path(temp) / "first", Path(temp) / "second"]
                for root in roots:
                    (root / name).mkdir(parents=True)
                    (root / name / "__init__.py").write_text("VALUE = 1\n")
                first = source_package(roots[0], name)
                self.assertIs(source_package(roots[1], name), first)
                (roots[1] / name / "__init__.py").write_text("VALUE = 2\n")
                with self.assertRaisesRegex(RuntimeError, "different"):
                    source_package(roots[1], name)
        finally:
            sys.path[:] = old_path
            sys.modules.pop(name, None)

    def test_staged_adapter_works_through_existing_factory_without_editing_registry(self):
        from module.ocr import recognizers
        from module.ocr.engine import OCR
        before = dict(recognizers._BACKENDS)
        new = {"akaocr": (".akaocr", "AkaOcrRecognizer"),
               "vietocr_original": (".vietocr_original", "VietOcrOriginalRecognizer")}
        with patch.dict(recognizers._BACKENDS, new), \
             patch("module.ocr.recognizers.akaocr.AkaOcrRecognizer") as adapter, \
             patch("module.ocr.engine.TextDetector"), patch("module.ocr.engine.PARALLEL_DEVICES", []):
            engine = OCR(recognizer_config={"backend": "akaocr", "model_dir": "synthetic"})
            adapter.assert_called_once_with(device_id=0, model_dir="synthetic")
            self.assertIs(engine.text_recognizer[0], adapter.return_value)
        self.assertEqual(recognizers._BACKENDS, before)


if __name__ == "__main__":
    unittest.main()
