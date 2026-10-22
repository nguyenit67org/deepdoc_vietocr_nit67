"""Pinned upstream VietOCR inference, for original and DungHugging checkpoints.

Unlike the FastOCR fork, upstream groups identical resized widths rather than
right-padding mixed widths. Keep upstream model/preprocess/decode unchanged.
"""
from collections import defaultdict
import importlib
import math
from pathlib import Path

import numpy as np

from .base import BatchedRecognizer, RecognitionResult
from .source_utils import source_package
from ...cancellation import check_cancelled


class VietOcrOriginalRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cuda", max_batch_size=16, max_seq_length=128):
        super().__init__(max_batch_size)
        if type(max_seq_length) is not int or max_seq_length < 1:
            raise ValueError("max_seq_length must be positive")
        if device not in ("cpu", "cuda"):
            raise ValueError("VietOCR device must be cpu or cuda")
        import torch
        import yaml
        root = Path(model_dir).resolve()
        source_package(root / "source", "vietocr")
        self.upstream = importlib.import_module("vietocr.tool.translate")
        self.config = yaml.safe_load((root / "config.yml").read_text())
        self.config["device"] = f"cuda:{device_id}" if device == "cuda" else "cpu"
        # The complete OCR checkpoint supplies CNN weights; avoid ImageNet downloads.
        self.config["cnn"]["pretrained"] = False
        if self.config["predictor"].get("beamsearch"):
            raise ValueError("This adapter qualifies upstream greedy decoding only; beam search is a separate variant")
        self.model, self.vocab = self.upstream.build_model(self.config)
        weights = torch.load(root / "weights.pth", map_location="cpu", weights_only=True)
        self.model.load_state_dict(weights, strict=True)
        self.model.eval()
        self.device = torch.device(self.config["device"])
        self.max_seq_length = max_seq_length

    def _recognize_batch(self, images):
        import torch
        dataset = self.config["dataset"]
        buckets = defaultdict(list)
        for index, image in enumerate(images):
            tensor = self.upstream.process_input(image, dataset["image_height"],
                dataset["image_min_width"], dataset["image_max_width"])
            buckets[tensor.shape[-1]].append((index, tensor))
        results = [None] * len(images)
        with torch.inference_mode():
            for width, bucket in buckets.items():
                check_cancelled()
                tensor = torch.cat([tensor for _, tensor in bucket], 0).to(self.device)
                ids, probabilities = self.upstream.translate(tensor, self.model, max_seq_length=self.max_seq_length)
                for (index, _), sequence, probability in zip(bucket, ids, probabilities):
                    tokens = sequence.tolist()
                    probability = float(probability)
                    results[index] = RecognitionResult(self.vocab.decode(tokens),
                        probability if math.isfinite(probability) else None, truncated=2 not in tokens,
                        metadata={"implementation": "pbcquoc/vietocr pinned upstream", "decoder": "greedy",
                            "resized_width": int(width), "max_seq_length": self.max_seq_length,
                            "native_confidence_nonfinite": not math.isfinite(probability)})
        if any(result is None for result in results):
            raise ValueError("Upstream VietOCR lost crop indices during width-bucket restore")
        return results
