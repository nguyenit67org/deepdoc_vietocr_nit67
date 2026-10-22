"""Recognition-only adapter for AkaOCR's public bundled ONNX checkpoint.

Default vocabulary lacks many Vietnamese tone letters. This is an additional
reference baseline, not a claim about proprietary AkaOCR Vietnamese models.
"""
import importlib
from pathlib import Path

import cv2
import numpy as np

from .base import BatchedRecognizer, RecognitionResult
from .source_utils import source_package


class AkaOcrRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=32, max_wh_ratio=None):
        super().__init__(max_batch_size)
        if device not in ("cpu", "cuda"):
            raise ValueError("AkaOCR device must be cpu or cuda")
        if device == "cuda" and device_id != 0:
            raise ValueError("Public AkaOCR helper does not expose CUDA device_id; only GPU 0 is supported")
        root = Path(model_dir).resolve()
        model, vocab = root / "recognition.onnx", root / "vocab.txt"
        if not model.is_file() or not vocab.is_file():
            raise ValueError("Explicit AkaOCR model/vocab required; bundled-path fallback is forbidden")
        source_package(root / "source", "akaocr")
        # Bypass TextEngine's broad exception handler; errors must propagate.
        cls = importlib.import_module("akaocr.recog.center.engines").Recognitor
        self.recognizer = cls(model_path=str(model), vocab_path=str(vocab), use_space_char=True,
            batch_sizes=max_batch_size, model_shape=[3, 48, 320], max_wh_ratio=max_wh_ratio,
            device="gpu" if device == "cuda" else "cpu")
        self.providers = self.recognizer.predictor.get_providers()
        if device == "cuda" and "CUDAExecutionProvider" not in self.providers:
            raise RuntimeError("AkaOCR silently fell back from requested CUDA")

    def _recognize_batch(self, images):
        # Upstream recognition preprocessing consumes OpenCV BGR, not PIL RGB.
        results = self.recognizer([cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR) for image in images])
        if results is None or len(results) != len(images):
            raise ValueError("AkaOCR failed one-result-per-crop contract")
        return [RecognitionResult(text, float(confidence), metadata={
            "source": "akaocr 2.1.6 bundled recognizer", "providers": self.providers,
            "channel_order": "BGR", "vocabulary_warning": "Default vocab lacks many Vietnamese diacritics"})
            for text, confidence in results]
