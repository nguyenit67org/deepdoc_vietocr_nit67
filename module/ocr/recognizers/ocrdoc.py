"""OcrDoc Run 6 recognizer only, following its published preprocessing."""
from pathlib import Path
import math
import numpy as np
from PIL import Image

from .base import BatchedRecognizer, RecognitionResult
from .onnx_utils import session, ctc_decode


class OcrDocRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cpu", max_batch_size=16, width=640):
        super().__init__(max_batch_size)
        if width not in (320, 640):
            raise ValueError("OcrDoc model card supports width 320 or 640")
        self.width = width
        root = Path(model_dir)
        self.vocab = ["blank", *root.joinpath("charset.txt").read_text(encoding="utf-8").splitlines()]
        # Paddle CTC adds space after the dictionary; the exported head has 230 classes.
        if " " not in self.vocab:
            self.vocab.append(" ")
        self.model = session(root / "recognition.onnx", device, device_id)

    def preprocess(self, image):
        width = max(1, min(self.width, math.ceil(48 * image.width / image.height)))
        resized = np.asarray(image.resize((width, 48), Image.Resampling.BILINEAR), dtype=np.float32)
        normalized = (resized / 255.0 - 0.5) / 0.5
        output = np.zeros((3, 48, self.width), dtype=np.float32)
        output[:, :, :width] = normalized.transpose(2, 0, 1)
        return output

    def _recognize_batch(self, images):
        x = np.stack([self.preprocess(image) for image in images])
        output = self.model.run(None, {self.model.get_inputs()[0].name: x})[0]
        # Exported graph must include softmax; fail instead of interpreting logits as confidence.
        if not np.allclose(output.sum(-1), 1.0, atol=1e-3):
            shifted = output - output.max(-1, keepdims=True)
            output = np.exp(shifted) / np.exp(shifted).sum(-1, keepdims=True)
        return [RecognitionResult(text, score, metadata={"input_width": self.width})
                for text, score in ctc_decode(output, self.vocab)]
