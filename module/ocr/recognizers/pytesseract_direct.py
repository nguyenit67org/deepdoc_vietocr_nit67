"""Direct CPU pytesseract recognizer, with immutable, policy-keyed raw caching."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import tempfile

from PIL import ImageOps

from .base import BatchedRecognizer, RecognitionResult
from .nom_tesseract import raw_cache_identity


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_options(lang, psm, oem, border_px, workers):
    if lang != "vie":
        raise ValueError("Vietnamese traineddata is vie, not vi/vn; no language fallback")
    if psm not in (6, 7, 13) or oem != 1:
        raise ValueError("This experiment supports PSM 6/7/13 and LSTM OEM 1 only")
    if type(border_px) is not int or border_px < 0 or type(workers) is not int or workers < 1:
        raise ValueError("Invalid border/workers")


class PytesseractDirectRecognizer(BatchedRecognizer):
    has_native_confidence = False

    def __init__(self, model_dir, raw_cache, lang="vie", psm=7, oem=1,
                 border_px=10, workers=4, max_batch_size=32, timeout_seconds=60, device_id=0):
        super().__init__(max_batch_size)
        validate_options(lang, psm, oem, border_px, workers)
        import pytesseract
        self.api = pytesseract
        self.root = Path(model_dir).resolve()
        self.cache = Path(raw_cache).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        manifest = json.loads((self.root / "download_manifest.json").read_text())
        verified = {}
        for relative, info in manifest["artifacts"].items():
            if relative.startswith(("runtime/", "tessdata/")):
                actual = digest(self.root / relative)
                if actual != info["sha256"]:
                    raise ValueError(f"Pinned Tesseract asset changed: {relative}")
                verified[relative] = actual
        os.environ["OMP_THREAD_LIMIT"] = "1"
        pytesseract.pytesseract.tesseract_cmd = str(self.root / "runtime/usr/bin/tesseract")
        available = pytesseract.get_languages(config=f'--tessdata-dir "{self.root / "tessdata"}"')
        if lang not in available:
            raise ValueError(f"Missing language {lang}; installed: {available}")
        self.policy = dict(backend="pytesseract_direct",version=1,lang=lang,psm=psm,oem=oem,
            border_px=border_px,preprocess="RGB plus white border only; no resize/threshold/deskew",
            spell_correction=False,output_processing="strip only; preserve raw text separately",
            tesseract_version=str(pytesseract.get_tesseract_version()),
            pytesseract_version=importlib.metadata.version("pytesseract"),
            assets=verified,omp_thread_limit=1,workers=workers)
        self.config = f'--oem {oem} --psm {psm} --tessdata-dir "{self.root / "tessdata"}"'
        self.lang, self.border, self.workers, self.timeout = lang, border_px, workers, timeout_seconds

    def _one(self, image):
        key, image_hash = raw_cache_identity(image, self.policy)
        path = self.cache / f"{key}.json"
        hit = path.exists()
        if hit:
            record = json.loads(path.read_text())
            if record["image_hash"] != image_hash or record["policy"] != self.policy or hashlib.sha256(record["raw_text"].encode()).hexdigest() != record["text_sha256"]:
                raise ValueError("Raw pytesseract cache fingerprint mismatch")
        else:
            prepared = ImageOps.expand(image, border=self.border, fill="white") if self.border else image
            started = time.perf_counter()
            raw = self.api.image_to_string(prepared, lang=self.lang, config=self.config, timeout=self.timeout)
            elapsed = time.perf_counter() - started
            record = dict(raw_text=raw,text_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                image_hash=image_hash,policy=self.policy,ocr_seconds=elapsed)
            # Identical crops can occur in a threaded batch: never overwrite a different result.
            with tempfile.NamedTemporaryFile(mode="w",dir=self.cache,suffix=".tmp",delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    json.dump(record,handle,ensure_ascii=False)
                    handle.flush()
                    os.link(temporary,path)
                except FileExistsError:
                    if json.loads(path.read_text())["text_sha256"] != record["text_sha256"]:
                        raise ValueError("Concurrent Tesseract output changed for identical inputs")
                finally:
                    temporary.unlink(missing_ok=True)
        return RecognitionResult(record["raw_text"].strip(), metadata=dict(
            raw_text_verbatim=record["raw_text"],raw_cache_key=key,raw_cache_hit=hit,
            raw_cache_path=str(path),original_call_seconds=record["ocr_seconds"],
            psm=self.policy["psm"],lang=self.lang,oem=1,post_correct=False,device="cpu",
            timing_note="Original image_to_string call wall time, reused on cache hits; parallel calls overlap"))

    def _recognize_batch(self, images):
        # Deduplicate identical image/policy inputs before parallel execution.
        keys = [raw_cache_identity(image,self.policy)[0] for image in images]
        unique = dict(zip(keys,images))
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            results = dict(zip(unique,executor.map(self._one,unique.values())))
        return [results[key] for key in keys]
