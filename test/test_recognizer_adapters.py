import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.ocr.base import TextRecognitionBackend
from module.ocr.recognizers import available_recognizers, create_recognizer
from module.ocr.recognizers.base import BatchedRecognizer, RecognitionResult, as_rgb
from module.ocr.recognizers.onnx_utils import ctc_decode
from module.ocr.recognizers.ocrdoc import OcrDocRecognizer
from module.ocr.recognizers.htr_convtext import HtrConvTextRecognizer
from module.ocr.recognizers.vietocr import VietOcrOnnxRecognizer
from types import SimpleNamespace


class FakeRecognizer(BatchedRecognizer):
    def _recognize_batch(self, images):
        return [RecognitionResult(str(image.getpixel((0, 0))[0]), 0.23) for image in images]


class RecognizerTests(unittest.TestCase):
    def test_registry_and_protocol(self):
        self.assertTrue({"fastocr", "ocrdoc_onnx", "vietocr_onnx", "htr_convtext", "senocr"}.issubset(available_recognizers()))
        self.assertIsInstance(FakeRecognizer(), TextRecognitionBackend)
        with self.assertRaisesRegex(ValueError, "Unknown recognizer"):
            create_recognizer({"backend": "typo"})

    def test_bgr_rgb_empty_and_ordered_batch_contract(self):
        recognizer = FakeRecognizer(max_batch_size=2)
        crops = [np.full((3, 7, 3), [5, 0, i], np.uint8) for i in range(5)]
        result, elapsed = recognizer(crops)
        self.assertEqual(result, [(str(i), 1.0) for i in range(5)])
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual([d["confidence"] for d in recognizer.last_details], [0.23] * 5)
        self.assertEqual(recognizer([])[0], [])
        self.assertEqual(recognizer.last_details, [])

    def test_pil_legacy_hook_retains_native_confidence(self):
        recognizer = FakeRecognizer()
        self.assertEqual(recognizer.detector.predict_batch([Image.new("RGB", (1, 1), (7, 2, 3))]), [("7", 0.23)])
        self.assertEqual(recognizer.predict(Image.new("RGB", (1, 1), (7, 2, 3)), return_prob=True), ("7", 0.23))

    def test_raw_text_preserved_newlines_joined_only_for_assembly(self):
        result = RecognitionResult("Đặng\r\nVăn\n A", None, True)
        self.assertEqual(result.text, "Đặng Văn  A")
        self.assertEqual(result.raw_text, "Đặng\r\nVăn\n A")

    def test_bad_input_and_cardinality_fail_loudly(self):
        with self.assertRaises(ValueError):
            as_rgb(np.zeros((0, 1, 3), np.uint8))
        recognizer = FakeRecognizer()
        with patch.object(recognizer, "_recognize_batch", return_value=[]):
            with self.assertRaisesRegex(ValueError, "one-result-per-crop"):
                recognizer([Image.new("RGB", (1, 1))])

    def test_oom_split_preserves_order_and_other_errors_propagate(self):
        import torch
        recognizer = FakeRecognizer(max_batch_size=4)
        original = recognizer._recognize_batch
        def run(images):
            if len(images) > 1:
                raise torch.cuda.OutOfMemoryError("simulated")
            return original(images)
        with patch.object(recognizer, "_recognize_batch", side_effect=run):
            result, _ = recognizer([Image.new("RGB", (1, 1), (i, 0, 0)) for i in range(4)])
        self.assertEqual(result, [(str(i), 1.0) for i in range(4)])
        self.assertEqual(recognizer.last_oom_retries, 3)
        with patch.object(recognizer, "_recognize_batch", side_effect=RuntimeError("broken")):
            with self.assertRaisesRegex(RuntimeError, "broken"):
                recognizer([Image.new("RGB", (1, 1))])

    def test_ctc_blank_repeats_and_vocabulary_validation(self):
        probs = np.eye(3, dtype=np.float32)[np.array([[0, 1, 1, 0, 1, 2, 2]])]
        self.assertEqual(ctc_decode(probs, ["blank", "A", "đ"]), [("AAđ", 1.0)])
        with self.assertRaises(ValueError):
            ctc_decode(probs, ["wrong"])

    def test_native_preprocessors_keep_whole_crop(self):
        recognizer = object.__new__(OcrDocRecognizer)
        recognizer.width = 640
        array = recognizer.preprocess(Image.new("RGB", (20, 10), (255, 0, 0)))
        self.assertEqual(array.shape, (3, 48, 640))
        self.assertEqual(array[:, 0, 0].tolist(), [1, -1, -1])
        self.assertTrue((array[:, :, 96:] == 0).all())
        htr = HtrConvTextRecognizer.preprocess(Image.new("RGB", (20, 10), "black"))
        self.assertEqual(htr.shape, (1, 64, 512))
        self.assertTrue((htr[:, :, 128:] == 1).all())

    def test_engine_legacy_default_and_explicit_factory_injection(self):
        from module.ocr.engine import OCR
        with patch("module.ocr.engine.TextDetector"), patch("module.ocr.engine.TextRecognizer") as legacy, \
             patch("module.ocr.engine.PARALLEL_DEVICES", []), \
             patch("module.ocr.recognizers.create_recognizer") as factory:
            OCR(fastocr_weight_path="baseline", fastocr_base_config="vgg_seq2seq")
            legacy.assert_called_once()
            factory.assert_not_called()
            legacy.reset_mock()
            config = {"backend": "ocrdoc_onnx", "model_dir": "weights"}
            engine = OCR(recognizer_config=config)
            legacy.assert_not_called()
            factory.assert_called_once_with(config, device_id=0)
            self.assertEqual(engine.text_recognizer, [factory.return_value])

    def test_vietocr_decoder_eos_and_token_limit_are_auditable(self):
        recognizer = object.__new__(VietOcrOnnxRecognizer)
        BatchedRecognizer.__init__(recognizer)
        recognizer.max_new_tokens = 3
        recognizer.vocab = ["pad", "sos", "eos", "mask", "Đ"]
        recognizer.encoder = Mock()
        recognizer.encoder.get_inputs.return_value = [SimpleNamespace(name="image", type="tensor(float)")]
        recognizer.encoder.run.return_value = [np.zeros((2, 1, 256), np.float32)]
        recognizer.decoder = Mock()
        recognizer.decoder.get_inputs.return_value = [SimpleNamespace(name="tokens"), SimpleNamespace(name="memory")]
        recognizer.decoder.run.side_effect = [[np.array([[0, 0, 0, 0, 8]], np.float32)],
                                               [np.array([[0, 0, 8, 0, 0]], np.float32)]]
        self.assertEqual(recognizer([Image.new("RGB", (100, 10))])[0], [("Đ", 1.0)])
        self.assertFalse(recognizer.last_details[0]["truncated"])
        recognizer.decoder.run.side_effect = None
        recognizer.decoder.run.return_value = [np.array([[0, 0, 0, 0, 8]], np.float32)]
        self.assertEqual(recognizer([Image.new("RGB", (100, 10))])[0], [("ĐĐĐ", 1.0)])
        self.assertTrue(recognizer.last_details[0]["truncated"])

    def test_worker_load_failure_is_explicit_and_cleaned_up(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown recognizer"):
            create_recognizer({"backend": "does_not_exist", "runtime": {"timeout_seconds": 30}})


if __name__ == "__main__":
    unittest.main()
