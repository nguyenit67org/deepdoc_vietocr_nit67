import logging
import threading

logger = logging.getLogger(__name__)


def _clean(v: str) -> str:
    return " ".join(v.split()).strip()


class GLiNER2ExtractBackend:
    """Wraps `gliner2.GLiNER2` (https://github.com/fastino-ai/GLiNER2) for
    schema-driven entity extraction over OCR'd markdown/text. Ported from
    the standalone extract_entity.py prototype."""

    def __init__(self, model_name: str = "fastino/gliner2-multi-v1", device: str | None = None):
        from gliner2 import GLiNER2

        kwargs = {"device": device} if device else {}
        self._model = GLiNER2.from_pretrained(model_name, **kwargs)
        logger.info("[device] Extract (GLiNER2 %s): device=%s", model_name, device or "auto")
        # Shared across every request the server handles concurrently -- same
        # caution as every other model in this project (module/layout,
        # module/ocr, module/table): not assumed thread-safe unless proven so.
        self._lock = threading.Lock()

    def __call__(self, text: str, schema: dict[str, str]) -> dict[str, list[str]]:
        with self._lock:
            raw = self._model.extract_entities(text, schema)
        return {
            k: [_clean(v) for v in vals if _clean(v)]
            for k, vals in raw.get("entities", {}).items()
        }
