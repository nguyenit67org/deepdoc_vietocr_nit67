from .base import OCREngine, TextRecognitionBackend
from .engine import OCR, TextDetector, TextRecognizer, load_model, loaded_models


def get_ocr_engine(conf: dict) -> OCR:
    ocr_conf = conf.get("ocr", {})
    engine = OCR(
        model_dir=ocr_conf.get("model_dir"),
        fastocr_weight_path=ocr_conf.get("fastocr_weight_path"),
        fastocr_base_config=ocr_conf.get("fastocr_base_config"),
        crop_pad_px_h=ocr_conf.get("crop_pad_px_h", 3.0),
        crop_pad_px_w=ocr_conf.get("crop_pad_px_w", 0.0),
        det_backend=ocr_conf.get("det_backend", "onnx"),
        det_max_batch_size=ocr_conf.get("max_batch_size", 8),
        fastocr_max_batch_size=ocr_conf.get("fastocr_max_batch_size", 64),
        recognizer_config=ocr_conf.get("recognizer"),
    )
    if conf.get("page_orientation", {}).get("enabled") and any(
        not getattr(rec, "has_native_confidence", True) for rec in engine.text_recognizer
    ):
        raise ValueError("Selected recognizer has no native confidence; confidence-based page orientation is unsupported")
    return engine


__all__ = [
    "OCR",
    "TextDetector",
    "TextRecognizer",
    "load_model",
    "loaded_models",
    "OCREngine",
    "TextRecognitionBackend",
    "get_ocr_engine",
]
