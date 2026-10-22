"""Lazy recognition registry. Selecting a backend imports only its dependencies."""
import importlib

_BACKENDS = {
    "vietocr_original": (".vietocr_original", "VietOcrOriginalRecognizer"),
}


def available_recognizers():
    return ("fastocr", *sorted(_BACKENDS))


def create_recognizer(config, device_id=0):
    options = dict(config)
    runtime = options.pop("runtime", None)
    if runtime is not None:
        raise ValueError("Separate recognizer workers are not part of the CPU UAT deployment")
    backend = options.pop("backend", "fastocr")
    if backend == "fastocr":
        from ..engine import TextRecognizer
        return TextRecognizer(device_id=device_id, **options)
    if backend not in _BACKENDS:
        raise ValueError(f"Unknown recognizer {backend!r}; available: {available_recognizers()}")
    module, name = _BACKENDS[backend]
    cls = getattr(importlib.import_module(module, __name__), name)
    return cls(device_id=device_id, **options)
