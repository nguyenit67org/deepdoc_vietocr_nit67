import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import torch
from PIL import Image

from module.corrector import get_corrector_backend
from module.corrector.protonx import ProtonXCorrectorBackend
from module.pipeline.document_pipeline import DocumentPipeline
from module.pipeline.config import PipelineConfig


class _Batch(dict):
    def to(self, _device):
        return self


class _FakeTokenizer:
    def __init__(self):
        self._word_to_id = {}
        self._id_to_word = {}

    def _id(self, word):
        if word not in self._word_to_id:
            token_id = len(self._word_to_id) + 3
            self._word_to_id[word] = token_id
            self._id_to_word[token_id] = word
        return self._word_to_id[word]

    def encode(self, text, add_special_tokens=True):
        ids = [self._id(word) for word in text.split()]
        return [1, *ids, 2] if add_special_tokens else ids

    def __call__(self, texts, return_tensors, padding, truncation):
        assert return_tensors == "pt"
        assert padding is True
        assert truncation is False
        encoded = [self.encode(text) for text in texts]
        width = max(len(ids) for ids in encoded)
        input_ids = torch.tensor([ids + [0] * (width - len(ids)) for ids in encoded])
        attention_mask = (input_ids != 0).long()
        return _Batch(input_ids=input_ids, attention_mask=attention_mask)

    def batch_decode(self, sequences, skip_special_tokens=True):
        assert skip_special_tokens is True
        return [
            " ".join(self._id_to_word[int(token)] for token in row if int(token) > 2)
            for row in sequences
        ]


class _IdentityModel:
    def generate(self, input_ids, **_kwargs):
        return input_ids


class _UpperCorrector:
    def correct_batch(self, texts):
        return [text.upper() for text in texts]


def _fake_backend(**overrides):
    backend = ProtonXCorrectorBackend.__new__(ProtonXCorrectorBackend)
    backend._torch = torch
    backend._tokenizer = _FakeTokenizer()
    backend._model = _IdentityModel()
    backend._device = torch.device("cpu")
    backend._lock = threading.Lock()
    backend.target_input_tokens = overrides.get("target_input_tokens", 6)
    backend.max_input_tokens = overrides.get("max_input_tokens", 8)
    backend.max_new_tokens = 8
    backend.batch_size = overrides.get("batch_size", 2)
    backend.num_beams = 1
    backend.preserve_numbers = overrides.get("preserve_numbers", True)
    return backend


class CorrectorTests(unittest.TestCase):
    def test_disabled_factory_does_not_load_a_backend(self):
        self.assertIsNone(get_corrector_backend({}))
        self.assertIsNone(get_corrector_backend({"corrector": {"enabled": False}}))

    def test_long_text_is_chunked_and_reassembled(self):
        backend = _fake_backend()
        text = "mot hai ba bon nam sau bay tam chin muoi"

        chunks = backend._split_line(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(backend._token_count(chunk) <= backend.max_input_tokens for chunk in chunks))
        self.assertEqual(backend.correct_batch([text]), [text])

    def test_newlines_and_blank_lines_are_preserved(self):
        backend = _fake_backend()
        text = "CONG HOA XA HOI\n\nDia chi van phong"

        self.assertEqual(backend.correct_batch([text]), [text])

    def test_numeric_changes_are_rejected(self):
        backend = _fake_backend(preserve_numbers=True)

        self.assertEqual(
            backend._accept("Dieu 10 nam 2026", "Điều 11 năm 2026"),
            "Dieu 10 nam 2026",
        )

    def test_pipeline_phase_four_corrects_only_text_blocks(self):
        image = Image.new("RGB", (10, 10), "white")
        layout = Mock()
        layout.detect_batch.return_value = [[]]
        pipeline = DocumentPipeline(
            layout=layout,
            ocr=Mock(),
            table_processor=Mock(),
            config=PipelineConfig.from_conf({}),
            corrector=_UpperCorrector(),
        )
        pre_page = SimpleNamespace(img=image, crop_offset=(0.0, 0.0), timings={})
        prepared = SimpleNamespace(
            img=image,
            dt_boxes_reuse=None,
            prerecognized_reuse=None,
        )
        assembled = [
            {"content_type": "text", "content": "raw ocr"},
            {"content_type": "table", "content": "| raw table |"},
            {"content_type": "skip", "content": None},
        ]

        with (
            patch.object(pipeline, "_prepare_page_pre_orientation", return_value=pre_page),
            patch.object(pipeline, "_prepare_page_orientation", return_value=prepared),
            patch.object(pipeline, "_build_table_skeleton", return_value=([], [])),
            patch("module.pipeline.document_pipeline.prepare_ocr_page", return_value=(object(), [])),
            patch("module.pipeline.document_pipeline.finish_ocr_page", return_value=[]),
            patch.object(pipeline, "_process_page_after_layout", return_value=assembled),
        ):
            pages_blocks, _, _ = pipeline._process_pages_batch([image], debug_dir=None)

        self.assertEqual(pages_blocks[0][0]["content"], "RAW OCR")
        self.assertEqual(pages_blocks[0][1]["content"], "| raw table |")


if __name__ == "__main__":
    unittest.main()
