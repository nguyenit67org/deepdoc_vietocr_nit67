import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from module.ocr.recognizers.word_segment import WhitespaceWordSegmenter
from module.ocr.recognizers.trocr_words import WordToLineRecognizer
from module.ocr.recognizers.base import BatchedRecognizer, RecognitionResult


class WordRecognizerTests(unittest.TestCase):
    def test_split_preserves_order_height_accents_and_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            pixels = np.full((40, 110, 3), 255, dtype=np.uint8)
            pixels[12:30, 5:30] = 0
            pixels[2:5, 10:15] = 0
            pixels[12:30, 60:100] = 0
            image = Image.fromarray(pixels)
            splitter = WhitespaceWordSegmenter(root)
            words, first = splitter.segment(image)
            cached, second = splitter.segment(image)
            self.assertEqual(len(words), 2)
            self.assertTrue(second["cache_hit"])
            self.assertFalse(first["cache_hit"])
            self.assertEqual(first["boxes"], second["boxes"])
            self.assertTrue(all(word.height == 40 for word in words))
            self.assertTrue(np.array_equal(words[0], cached[0]))
            self.assertTrue((np.asarray(words[0])[2:5] == 0).any())

    def test_blank_is_explicit_no_segments_not_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            words, data = WhitespaceWordSegmenter(root).segment(Image.new("RGB", (100, 30), "white"))
            self.assertEqual(words, [])
            self.assertTrue(data["blank"])

    def test_policy_changes_cache_identity(self):
        with tempfile.TemporaryDirectory() as root:
            image = Image.new("RGB", (100, 30), "white")
            a = WhitespaceWordSegmenter(root, .22).segment(image)[1]
            b = WhitespaceWordSegmenter(root, .3).segment(image)[1]
            self.assertNotEqual(a["cache_key"], b["cache_key"])

    def test_invalid_policy(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                WhitespaceWordSegmenter(root, 0)

    def test_composite_restores_parent_order_and_neutral_scores(self):
        with tempfile.TemporaryDirectory() as root:
            model = WordToLineRecognizer.__new__(WordToLineRecognizer)
            BatchedRecognizer.__init__(model, 16)
            model.segmenter = WhitespaceWordSegmenter(root)
            model.word_backend, model.word_batch_size = "mock", 2
            pixels = np.full((40, 100, 3), 255, dtype=np.uint8)
            pixels[10:30, 5:20] = 0
            pixels[10:30, 60:80] = 0
            def recognize(words):
                return [RecognitionResult(" từ ", .5) for _ in words]
            with patch.object(model, "_read_words", side_effect=recognize):
                results, _ = model([Image.fromarray(pixels), Image.new("RGB", (100, 40), "white")])
            self.assertEqual(results, [("từ từ", 1.0), ("", 1.0)])
            self.assertTrue(model.last_details[1]["metadata"]["no_segments"])


if __name__ == "__main__":
    unittest.main()
