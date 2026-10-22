import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PIL import Image

from module.ocr.recognizers.base import BatchedRecognizer
from module.ocr.recognizers.nom_tesseract import NomTesseractRecognizer, raw_cache_identity


class NomTesseractTests(unittest.TestCase):
    def reader(self, folder, corrected=False):
        reader = NomTesseractRecognizer.__new__(NomTesseractRecognizer)
        BatchedRecognizer.__init__(reader, 2)
        reader.raw_cache = Path(folder)
        reader.policy = {"version": "test", "psm": 6}
        reader.post_correct = corrected
        reader.max_input_tokens = 512
        reader.corrector = None
        reader.context_class = lambda **kwargs: SimpleNamespace(**kwargs)
        reader.ocr = Mock()
        reader.ocr.run.return_value = SimpleNamespace(text="Hà Nọi")
        return reader

    def test_raw_cache_identity_includes_pixels_and_policy(self):
        image = Image.new("RGB", (20, 10), "white")
        self.assertNotEqual(raw_cache_identity(image, {"psm": 6})[0], raw_cache_identity(image, {"psm": 7})[0])
        self.assertNotEqual(raw_cache_identity(image, {})[0], raw_cache_identity(Image.new("RGB", (20, 10), "black"), {})[0])

    def test_corrected_branch_uses_same_raw_without_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.new("RGB", (20, 10), "white")
            raw = self.reader(folder)
            output, _ = raw([image])
            self.assertEqual(output, [("Hà Nọi", 1.0)])
            corrected = self.reader(folder, True)
            corrected.corrector = SimpleNamespace(_tok=SimpleNamespace(encode=lambda *args, **kwargs: [1, 2]),
                predict_batch=lambda texts, batch_size: ["Hà Nội" for text in texts])
            output, _ = corrected([image])
            self.assertEqual(output, [("Hà Nội", 1.0)])
            corrected.ocr.run.assert_not_called()
            metadata = corrected.last_details[0]["metadata"]
            self.assertEqual(metadata["raw_ocr_text"], "Hà Nọi")
            self.assertTrue(metadata["raw_cache_hit"])
            self.assertTrue(metadata["post_correct_changed"])

    def test_missing_raw_is_error_not_silent_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.reader(folder, True)
            with self.assertRaisesRegex(ValueError, "must never re-run OCR"):
                reader._raw(Image.new("RGB", (20, 10), "white"))
            reader.ocr.run.assert_not_called()

    def test_corrupt_raw_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.new("RGB", (20, 10), "white")
            self.reader(folder)._raw(image)
            path = next(Path(folder).glob("*.json"))
            record = json.loads(path.read_text())
            record["text"] = "tampered"
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                self.reader(folder, True)._raw(image)

    def test_nondeterministic_raw_rerun_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.new("RGB", (20, 10), "white")
            reader = self.reader(folder)
            reader._raw(image)
            reader.ocr.run.return_value = SimpleNamespace(text="different")
            with self.assertRaisesRegex(ValueError, "rerun changed text"):
                reader._raw(image)

    def test_order_blank_and_one_result_per_crop(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.reader(folder)
            reader.ocr.run.side_effect = [SimpleNamespace(text="first"), SimpleNamespace(text="")]
            output, _ = reader([Image.new("RGB", (20, 10), "white"), Image.new("RGB", (30, 10), "white")])
            self.assertEqual(output, [("first", 1.0), ("", 1.0)])

    def test_input_truncation_flag_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.new("RGB", (20, 10), "white")
            self.reader(folder)._raw(image)
            reader = self.reader(folder, True)
            reader.corrector = SimpleNamespace(_tok=SimpleNamespace(encode=lambda *args, **kwargs: list(range(513))),
                predict_batch=lambda texts, batch_size: texts)
            reader([image])
            self.assertTrue(reader.last_details[0]["truncated"])


if __name__ == "__main__":
    unittest.main()
