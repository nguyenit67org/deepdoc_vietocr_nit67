"""Lazy recognition registry. Selecting a backend imports only its dependencies."""
import importlib

_BACKENDS = {
    "easyocr_latin": (".easyocr_latin", "EasyOcrLatinRecognizer"),
    "trocr_duyle": (".candidates", "DuyleTrOcrRecognizer"),
    "vnhtr_jit": (".candidates", "VnhtrJitRecognizer"),
    "pytesseract_direct": (".pytesseract_direct", "PytesseractDirectRecognizer"),
    "nom_tesseract": (".nom_tesseract", "NomTesseractRecognizer"),
    "word_to_line": (".trocr_words", "WordToLineRecognizer"),
    "ocrdoc_onnx": (".ocrdoc", "OcrDocRecognizer"),
    "vietocr_onnx": (".vietocr", "VietOcrOnnxRecognizer"),
    "htr_convtext": (".htr_convtext", "HtrConvTextRecognizer"),
    "senocr": (".senocr", "SenOcrRecognizer"),
    "akaocr": (".akaocr", "AkaOcrRecognizer"),
    "vietocr_original": (".vietocr_original", "VietOcrOriginalRecognizer"),
}


def available_recognizers():
    return ("fastocr", *sorted(_BACKENDS))


def create_recognizer(config, device_id=0):
    options = dict(config)
    runtime = options.pop("runtime", None)
    if runtime is not None:
        from .process import ProcessRecognizer
        return ProcessRecognizer(options, runtime, device_id)
    backend = options.pop("backend", "fastocr")
    if backend == "fastocr":
        from ..engine import TextRecognizer
        return TextRecognizer(device_id=device_id, **options)
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown recognizer {backend!r}; available: {available_recognizers()}")
    module, name = _BACKENDS[backend]
    cls = getattr(importlib.import_module(module, __name__), name)
    return cls(device_id=device_id, **options)
