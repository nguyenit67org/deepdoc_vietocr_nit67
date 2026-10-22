"""Pinned Nôm OCR stage, optionally correcting the exact cached raw OCR text.

Tesseract is CPU-only. Spell correction uses Nôm's upstream HF wrapper on CUDA.
No field/GT-dependent rules, routing, normalization or correction guards are added.
"""
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np

from .base import BatchedRecognizer, RecognitionResult
from .source_utils import source_package


def raw_cache_identity(image, policy):
    rgb = np.asarray(image.convert("RGB"))
    image_hash = hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
    key = hashlib.sha256(json.dumps(dict(image_hash=image_hash, policy=policy), sort_keys=True).encode()).hexdigest()
    return key, image_hash


class NomTesseractRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, raw_cache, device_id=0, max_batch_size=16,
                 post_correct=False, lang="vie", psm=6, max_input_tokens=512,
                 num_beams=1, heading_retry=True):
        super().__init__(max_batch_size)
        if lang != "vie" or psm != 6:
            raise ValueError("This cohort qualifies only vie / PSM 6; new settings require a separate experiment")
        self.root = Path(model_dir).resolve()
        self.raw_cache = Path(raw_cache).resolve()
        self.raw_cache.mkdir(parents=True, exist_ok=True)
        self.post_correct = post_correct
        self.max_input_tokens = max_input_tokens
        manifest_hash = hashlib.sha256((self.root / "download_manifest.json").read_bytes()).hexdigest()
        self.policy = dict(manifest_sha256=manifest_hash, lang=lang, psm=psm, oem=1,
            wrapper="nom.doc.stages.OCR", normalization="upstream text.strip only", auto_preprocess=False)
        source_package(self.root / "source/src", "nom")
        from nom.doc.stages import OCR
        from nom.doc.pipeline import Context
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = str(self.root / "runtime/usr/bin/tesseract")
        # Explicit local traineddata, no implicit system language fallback.
        config = f'--psm {psm} --oem 1 --tessdata-dir "{self.root / "tessdata"}"'
        self.ocr = OCR(lang=lang, config=config)
        self.context_class = Context
        self.corrector = None
        if post_correct:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("Spell-correction cohort requests CUDA; no silent CPU fallback")
            from nom.text.diacritic_models import HFDiacriticModel
            self.corrector = HFDiacriticModel(model_id=str(self.root / "spell"),
                device=f"cuda:{device_id}", max_input_tokens=max_input_tokens,
                num_beams=num_beams, heading_retry=heading_retry)
            self.corrector._ensure_loaded()

    def _raw(self, image):
        key, image_hash = raw_cache_identity(image, self.policy)
        path = self.raw_cache / f"{key}.json"
        if self.post_correct:
            if not path.is_file():
                raise ValueError(f"Raw Tesseract output missing; corrected branch must never re-run OCR: {key}")
            record = json.loads(path.read_text())
            if (record["image_hash"] != image_hash or record["policy"] != self.policy
                    or hashlib.sha256(record["text"].encode()).hexdigest() != record["text_sha256"]):
                raise ValueError("Raw OCR cache fingerprint mismatch")
        else:
            started = time.perf_counter()
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            data = stream.getvalue()
            context = self.context_class(source=data, fmt="image", metadata={"bytes": data})
            text = self.ocr.run(context).text
            elapsed = time.perf_counter() - started
            record = dict(text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                image_hash=image_hash, policy=self.policy, ocr_seconds=elapsed)
            if path.is_file() and json.loads(path.read_text())["text"] != text:
                raise ValueError("Tesseract rerun changed text for the identical crop/policy")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(path)
        return record, dict(raw_cache_key=key, raw_cache_path=str(path),
            raw_cache_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), raw_cache_hit=self.post_correct)

    def _recognize_batch(self, images):
        records, provenance = [], []
        for image in images:
            record, metadata = self._raw(image)
            records.append(record)
            provenance.append(metadata)
        raw = [record["text"] for record in records]
        started = time.perf_counter()
        if self.corrector is not None:
            token_lengths = [len(self.corrector._tok.encode(text, add_special_tokens=True, truncation=False)) for text in raw]
            texts = self.corrector.predict_batch(raw, batch_size=self.max_batch_size)
        else:
            token_lengths = [None] * len(raw)
            texts = raw
        correction_seconds = time.perf_counter() - started if self.corrector is not None else 0.0
        if len(texts) != len(raw):
            raise ValueError("Nôm correction lost input order/cardinality")
        return [RecognitionResult(text, truncated=length is not None and length > self.max_input_tokens,
            metadata=dict(**metadata, raw_ocr_text=record["text"], raw_ocr_seconds=record["ocr_seconds"],
                post_correct=self.post_correct, post_correct_changed=text != record["text"],
                correction_input_tokens=length, input_truncated=length is not None and length > self.max_input_tokens,
                correction_device=getattr(self.corrector, "device", None),
                correction_dtype=str(getattr(getattr(self.corrector, "_model", None), "dtype", None)),
                output_truncation_observable=False,
                truncation_note="Input truncation is measured; upstream wrapper does not expose generated EOS/token IDs",
                correction_seconds_amortized=correction_seconds / len(images),
                correction_timing="batch correction wall time divided equally among its parent crops; sum is measured batch total",
                raw_policy=self.policy, no_ocr_rerun=self.post_correct))
            for text, length, record, metadata in zip(texts, token_lengths, records, provenance)]
