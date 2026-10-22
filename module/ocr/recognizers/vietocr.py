"""VietOCR handwriting ONNX encoder/AR decoder, published vocabulary/order."""
from pathlib import Path
import numpy as np
from PIL import Image

from .base import BatchedRecognizer, RecognitionResult
from .onnx_utils import session


class VietOcrOnnxRecognizer(BatchedRecognizer):
    def __init__(self, model_dir, device_id=0, device="cpu", max_batch_size=1, max_new_tokens=256):
        # Native-width per-image inference avoids unvalidated encoder-padding effects.
        super().__init__(max_batch_size)
        if type(max_new_tokens) is not int or max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        self.max_new_tokens = max_new_tokens
        root = Path(model_dir)
        self.vocab = (root / "vocab.txt").read_text(encoding="utf-8").splitlines()
        self.encoder = session(root / "encoder_fp16.onnx", device, device_id)
        self.decoder = session(root / "decoder_fp16.onnx", device, device_id)

    def _recognize_batch(self, images):
        results = []
        for image in images:
            width = max(32, int(round(32 * image.width / image.height)))
            x = np.asarray(image.resize((width, 32), Image.Resampling.BICUBIC), dtype=np.float32)
            x = (x / 255.0).transpose(2, 0, 1)[None]
            encoder_input = self.encoder.get_inputs()[0]
            if encoder_input.type == "tensor(float16)":
                x = x.astype(np.float16)
            memory = self.encoder.run(None, {encoder_input.name: x})[0]
            ids, scores, finished = [1], [], False
            for _ in range(self.max_new_tokens):
                inputs = self.decoder.get_inputs()
                logits = self.decoder.run(None, {inputs[0].name: np.array(ids, np.int64)[:, None],
                                                  inputs[1].name: memory})[0][0].astype(np.float64)
                if not np.isfinite(logits).all():
                    raise ValueError("Non-finite VietOCR decoder logits")
                token = int(logits.argmax())
                if token == 2:
                    finished = True
                    break
                ids.append(token)
                probs = np.exp(logits - logits.max())
                scores.append(float(probs[token] / probs.sum()))
            text = "".join(self.vocab[i] for i in ids[1:] if i >= 4)
            results.append(RecognitionResult(text, float(np.mean(scores)) if scores else 0.0,
                           truncated=not finished, metadata={"input_width": width, "decode": "greedy"}))
        return results
