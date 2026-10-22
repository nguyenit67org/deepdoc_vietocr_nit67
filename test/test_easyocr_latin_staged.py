"""Recognizer-only EasyOCR contract tests, without downloads or model loading."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image

from module.ocr.recognizers.easyocr_latin import EasyOcrLatinRecognizer
from module.ocr.recognizers.base import BatchedRecognizer


class EasyOcrLatinTests(unittest.TestCase):
    def adapter(self, rows):
        model = object.__new__(EasyOcrLatinRecognizer)
        BatchedRecognizer.__init__(model)
        model.reader = SimpleNamespace(recognize=Mock(return_value=rows))
        return model

    def test_no_detection_one_whole_grayscale_crop(self):
        model = self.adapter([([[0, 0], [20, 0], [20, 10], [0, 10]], "tiếng Việt", 0.8)])
        result = model.recognize([Image.new("RGB", (20, 10), "white")])[0]
        self.assertEqual(result.raw_text, "tiếng Việt")
        args, options = model.reader.recognize.call_args
        self.assertEqual(args[0].shape, (10, 20))
        self.assertFalse(options["reformat"])
        self.assertEqual(options["batch_size"], 1)
        self.assertIsNone(options["horizontal_list"])
        self.assertFalse(result.metadata["detector_enabled"])
        self.assertEqual(model.last_details[0]["pipeline_score"], 1.0)

    def test_missing_result_not_swallowed(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.adapter([]).recognize([Image.new("RGB", (20, 10))])

    def test_nonfinite_confidence_is_explicit(self):
        model = self.adapter([([[0, 0]], "", float("nan"))])
        result = model.recognize([Image.new("RGB", (20, 10))])[0]
        self.assertIsNone(result.confidence)
        self.assertTrue(result.metadata["native_confidence_nonfinite"])

    def test_ordered_multiple_inputs(self):
        model = self.adapter([])
        model.reader.recognize.side_effect = [[([[0, 0]], "first", 0.5)], [([[0, 0]], "second", 0.7)]]
        output, _ = model([Image.new("RGB", (10, 10)), Image.new("RGB", (30, 10))])
        self.assertEqual([text for text, _ in output], ["first", "second"])
