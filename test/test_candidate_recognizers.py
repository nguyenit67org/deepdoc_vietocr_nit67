"""Contract and preprocessing tests for the candidate cohort (no downloads)."""
from pathlib import Path

import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

from module.ocr.recognizers.candidates import VnhtrJitRecognizer, decode_vnhtr, vnhtr_vocab, vnhtr_weight_prefix


def check_vocab_literal_does_not_execute(tmp_path):
    source = tmp_path / "tools.py.txt"
    source.write_text("raise RuntimeError('must not run')\nclass Tokenizer:\n def __init__(self):\n  vocab = ['a', 'Đ', ' ']\n")
    vocab = vnhtr_vocab(source)
    assert vocab == ["pad", "<sos>", "<eos>", "<unk>", "a", "Đ", " "]
    assert decode_vnhtr([1, 4, 3, 6, 5, 2, 4], vocab) == "a Đ"


def check_invalid_vocab_rejected(tmp_path):
    source = tmp_path / "tools.py.txt"
    source.write_text("class Tokenizer:\n def __init__(self):\n  vocab = ['too long']\n")
    with unittest.TestCase().assertRaisesRegex(ValueError, "vocabulary"):
        vnhtr_vocab(source)


def check_vgg_native_geometry_and_right_crop():
    model = object.__new__(VnhtrJitRecognizer)
    model.variant, model.device = "vgg", "cpu"
    pixels = model._pixels([Image.new("RGB", (100, 32), "black"), Image.new("RGB", (1000, 32), "white")])
    assert tuple(pixels.shape) == (2, 3, 32, 768)
    assert pixels[0, :, :, :100].max().item() == 0
    assert pixels[0, :, :, 100:].min().item() == 1
    assert pixels[1].min().item() == 1


def check_registry_has_new_backends():
    from module.ocr.recognizers import available_recognizers
    assert {"trocr_duyle", "vnhtr_jit"}.issubset(available_recognizers())


def check_candidate_configs_use_isolated_workers():
    import json
    root = Path(__file__).resolve().parents[1]
    for name in ("trocr_duyle", "vnhtr_vgg", "vnhtr_trocr", "vnhtr_vgg_base", "vnhtr_trocr_base"):
        config = json.loads((root / f"conf/recognizers/{name}.json").read_text())
        assert config["runtime"]["env"]["TORCH_DISABLE_NATIVE_JIT"] == "1"
        assert config["max_batch_size"] > 0


def check_vnhtr_four_distinct_cases():
    import json
    root = Path(__file__).resolve().parents[1]
    directories = set()
    for family in ("vgg", "trocr"):
        for suffix in ("", "_base"):
            config = json.loads((root / f"conf/recognizers/vnhtr_{family}{suffix}.json").read_text())
            assert config["variant"] == family
            assert config.get("rethinking_head", True) == (suffix == "")
            directories.add(config["model_dir"])
    assert len(directories) == 4


class CandidateRecognizerTests(unittest.TestCase):
    def test_literal_vocab(self):
        with tempfile.TemporaryDirectory() as folder:
            check_vocab_literal_does_not_execute(Path(folder))

    def test_invalid_vocab(self):
        with tempfile.TemporaryDirectory() as folder:
            check_invalid_vocab_rejected(Path(folder))

    def test_geometry(self):
        check_vgg_native_geometry_and_right_crop()

    def test_registry(self):
        check_registry_has_new_backends()

    def test_configs(self):
        check_candidate_configs_use_isolated_workers()

    def test_vnhtr_four_distinct_cases(self):
        check_vnhtr_four_distinct_cases()

    def test_vnhtr_prefix_maps_four_cases(self):
        self.assertEqual(vnhtr_weight_prefix("vgg", False), "vt")
        self.assertEqual(vnhtr_weight_prefix("vgg", True), "vta")
        self.assertEqual(vnhtr_weight_prefix("trocr", False), "tr")
        self.assertEqual(vnhtr_weight_prefix("trocr", True), "tra")
        with self.assertRaises(ValueError):
            vnhtr_weight_prefix("trocr", "false")

    def test_ranged_download_verifies_content(self):
        import hashlib
        import io
        from scripts.download_candidate_recognizers import download_lfs
        body = b"verified model data"
        response = io.BytesIO(body)
        response.status = 206
        response.headers = {"Content-Range": f"bytes 0-{len(body)-1}/{len(body)}"}
        with tempfile.TemporaryDirectory() as folder, patch("urllib.request.urlopen", return_value=response):
            path = Path(folder) / "weights.pt"
            download_lfs("https://example.invalid/model", path, hashlib.sha256(body).hexdigest(), len(body))
            self.assertEqual(path.read_bytes(), body)

    def test_ranged_download_rejects_truncation(self):
        import io
        from scripts.download_candidate_recognizers import download_lfs

        def truncated(*args, **kwargs):
            response = io.BytesIO(b"short")
            response.status = 206
            response.headers = {"Content-Range": "bytes 0-9/10"}
            return response

        with tempfile.TemporaryDirectory() as folder, patch("urllib.request.urlopen", side_effect=truncated), patch("time.sleep"):
            path = Path(folder) / "weights.pt"
            with self.assertRaisesRegex(ValueError, "Truncated"):
                download_lfs("https://example.invalid/model", path, "unused", 10)
            self.assertFalse(path.exists())
