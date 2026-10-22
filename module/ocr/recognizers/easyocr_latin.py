"""Pinned EasyOCR Latin Gen2 recognition, without detection or downloads."""
import math
from pathlib import Path

import cv2
import numpy as np

from .base import BatchedRecognizer, RecognitionResult


class EasyOcrLatinRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=16):
        super().__init__(max_batch_size)
        import torch
        import easyocr
        if device not in ("cuda", "cpu"):
            raise ValueError("Unsupported EasyOCR device")
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA required; no CPU fallback")
        if easyocr.__version__ != "1.7.2":
            raise ValueError("Only pinned EasyOCR 1.7.2 is validated")
        root = Path(model_dir).resolve()
        self.reader = easyocr.Reader(["vi", "en"], gpu=f"cuda:{device_id}" if device == "cuda" else False,
            model_storage_directory=str(root), user_network_directory=str(root / "user_network"),
            recog_network="latin_g2", detector=False, recognizer=True, download_enabled=False,
            quantize=False, cudnn_benchmark=False, verbose=False)

    def _recognize_batch(self, images):
        results = []
        for image in images:
            gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
            rows = self.reader.recognize(gray, horizontal_list=None, free_list=None, decoder="greedy",
                batch_size=1, workers=0, detail=1, paragraph=False, rotation_info=None,
                contrast_ths=0.1, adjust_contrast=0.5, filter_ths=0.003, reformat=False)
            if len(rows) != 1:
                raise ValueError("EasyOCR must produce exactly one result for each cached crop")
            box, text, confidence = rows[0]
            confidence = float(confidence)
            results.append(RecognitionResult(text, confidence if math.isfinite(confidence) else None,
                metadata={"implementation": "EasyOCR 1.7.2 Reader.recognize",
                    "model_kind": "Latin Gen2 pretrained; NOT VietDoc fine-tuned",
                    "detector_enabled": False, "decoder": "greedy", "native_batch_size": 1,
                    "quantize": False, "native_confidence_nonfinite": not math.isfinite(confidence),
                    "truncation_observable": False, "native_box": np.asarray(box).tolist()}))
        return results
