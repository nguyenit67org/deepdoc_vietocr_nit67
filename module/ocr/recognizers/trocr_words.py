"""Composite whitespace segmentation + word recognition + ordered line assembly."""
import time
import json
from pathlib import Path

from .base import BatchedRecognizer, RecognitionResult
from .word_segment import WhitespaceWordSegmenter


class WordToLineRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, segmentation_cache, word_backend="trocr", device_id=0,
                 device="cuda", max_batch_size=16, word_batch_size=8, max_new_tokens=64,
                 gap_height_ratio=0.18, pad_px=1, dtype="float32"):
        super().__init__(max_batch_size)
        if word_backend not in ("trocr", "fastocr") or device not in ("cuda", "cpu"):
            raise ValueError("Unsupported composite backend/device")
        if type(word_batch_size) is not int or word_batch_size < 1 or max_new_tokens < 1:
            raise ValueError("Batch/token limits must be positive")
        import torch
        self.device = torch.device(f"cuda:{device_id}" if device == "cuda" else "cpu")
        self.segmenter = WhitespaceWordSegmenter(segmentation_cache, gap_height_ratio, pad_px)
        self.word_backend = word_backend
        self.word_batch_size = word_batch_size
        self.max_new_tokens = max_new_tokens
        self.dtype = dtype
        if dtype != "float32":
            raise ValueError("Only validated FP32 is enabled for this ablation")
        if word_backend == "fastocr":
            from ..engine import TextRecognizer
            self.reader = TextRecognizer(weight_path=str(Path(model_dir) / "vgg_seq2seq.pth"),
                base_config_name="vgg_seq2seq", device_id=device_id, max_batch_size=word_batch_size)
            if device != "cuda" or not torch.cuda.is_available():
                raise ValueError("FastOCR word control requires CUDA for this cohort")
        else:
            from transformers import AutoTokenizer, TrOCRProcessor, ViTImageProcessor, VisionEncoderDecoderModel
            root = str(Path(model_dir).resolve())
            # Upstream saved a unified processor config and tokenizer.json only.
            # Read the exact image settings; slow Roberta would require absent vocab/merges.
            settings = json.loads((Path(root) / "processor_config.json").read_text())["image_processor"]
            self.processor = TrOCRProcessor(ViTImageProcessor(**settings),
                AutoTokenizer.from_pretrained(root, local_files_only=True, use_fast=True))
            self.model, info = VisionEncoderDecoderModel.from_pretrained(root, local_files_only=True,
                torch_dtype=torch.float32, attn_implementation="eager", output_loading_info=True)
            if info.get("missing_keys") or info.get("mismatched_keys") or info.get("error_msgs"):
                raise ValueError(f"Incomplete TrOCR checkpoint: {info}")
            self.model.to(self.device).eval()

    def _read_words(self, words):
        import torch
        if self.word_backend == "fastocr":
            return [RecognitionResult(text, float(prob)) for text, prob in self.reader.detector.predict_batch(words)]
        pixels = self.processor(images=words, return_tensors="pt").pixel_values.to(self.device)
        with torch.inference_mode():
            sequences = self.model.generate(pixels, max_new_tokens=self.max_new_tokens,
                num_beams=1, do_sample=False, use_cache=True)
        texts = self.processor.batch_decode(sequences, skip_special_tokens=True)
        eos = self.model.generation_config.eos_token_id
        eos_ids = [eos] if isinstance(eos, int) else (eos or [])
        return [RecognitionResult(text, truncated=not any(int(t) in eos_ids for t in ids[1:]),
                    metadata={"token_ids": ids.tolist()}) for text, ids in zip(texts, sequences)]

    def _recognize_batch(self, images):
        words, spans, details = [], [], []
        for image in images:
            pieces, metadata = self.segmenter.segment(image)
            spans.append((len(words), len(words) + len(pieces)))
            words.extend(pieces)
            details.append(metadata)
        predictions = []
        started = time.perf_counter()
        for start in range(0, len(words), self.word_batch_size):
            predictions.extend(self._read_words(words[start:start + self.word_batch_size]))
        elapsed = time.perf_counter() - started
        if len(predictions) != len(words):
            raise ValueError("Word decoder lost crop indices")
        results = []
        for (start, end), metadata in zip(spans, details):
            selected = predictions[start:end]
            # Fixed one-space assembly, no GT/text-dependent punctuation repair.
            text = " ".join(result.text.strip() for result in selected if result.text.strip())
            metadata.update(word_backend=self.word_backend, word_batch_size=self.word_batch_size,
                words_raw=[dict(raw_text=r.raw_text, confidence=r.confidence, truncated=r.truncated, **r.metadata) for r in selected],
                batch_word_recognition_seconds=elapsed, batch_parent_count=len(images),
                assembly="strip each decoded word; omit empty words; join with one ASCII space",
                no_segments=not selected)
            results.append(RecognitionResult(text, truncated=any(r.truncated for r in selected), metadata=metadata))
        return results
