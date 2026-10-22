"""Shared compatibility layer; model-specific preprocessing stays in adapters."""
from dataclasses import asdict, dataclass, field
import threading
import time

import cv2
import numpy as np
from PIL import Image
from ...cancellation import check_cancelled


@dataclass
class RecognitionResult:
    raw_text: str
    confidence: float | None = None
    truncated: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def text(self):
        return self.raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def as_rgb(image):
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) == 0:
        raise ValueError("Recognizer expects a nonempty uint8 HWC BGR crop or PIL image")
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


class BatchedRecognizer:
    """Neutral pipeline scores; native confidence remains available for audit.

    `.detector.predict_batch(PIL_images)` is the legacy table/orientation hook.
    Its probabilities are native, uncalibrated, or 1.0 if unavailable; confidence-
    dependent orientation must not be enabled for backends without confidence.
    """

    has_native_confidence = True

    def __init__(self, max_batch_size=16):
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")
        self.max_batch_size = max_batch_size
        self.last_details = []
        self.last_oom_retries = 0
        self._lock = threading.RLock()
        self.detector = self

    def _recognize_batch(self, images):
        raise NotImplementedError

    def _checked_batch(self, images):
        try:
            results = self._recognize_batch(images)
        except Exception as error:
            # Never swallow arbitrary errors or drop failed crops.
            import torch
            if not isinstance(error, torch.cuda.OutOfMemoryError) or len(images) <= 1:
                raise
            self.last_oom_retries += 1
            torch.cuda.empty_cache()
            middle = len(images) // 2
            return self._checked_batch(images[:middle]) + self._checked_batch(images[middle:])
        if len(results) != len(images) or any(not isinstance(r, RecognitionResult) or not isinstance(r.raw_text, str) for r in results):
            raise ValueError("Recognizer violated ordered one-result-per-crop contract")
        return results

    def recognize(self, images):
        with self._lock:
            self.last_details = []
            self.last_oom_retries = 0
            results = []
            for start in range(0, len(images), self.max_batch_size):
                check_cancelled()
                results.extend(self._checked_batch([as_rgb(image) for image in images[start:start + self.max_batch_size]]))
                check_cancelled()
            self.last_details = [{**asdict(r), "text": r.text, "pipeline_score": 1.0} for r in results]
            return results

    def __call__(self, img_list):
        started = time.perf_counter()
        with self._lock:
            results = self.recognize(img_list)
            return [(r.text, 1.0) for r in results], time.perf_counter() - started

    def predict_batch(self, images):
        return [(r.text, r.confidence if r.confidence is not None else 1.0) for r in self.recognize(images)]

    def predict(self, image, return_prob=False):
        text, score = self.predict_batch([image])[0]
        return (text, score) if return_prob else text
