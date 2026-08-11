from .base import ExtractBackend


def get_extract_backend(conf: dict) -> ExtractBackend:
    # Concrete backends imported lazily, INSIDE this function -- same
    # circular-import reasoning as module/table/__init__.py's
    # get_table_processor (this package is imported from server/main.py,
    # which also builds the OCR pipeline; keeping heavy model imports out of
    # module-level code here avoids paying for/risking that import order).
    extract_conf = conf.get("extract", {})
    backend = extract_conf.get("backend", "gliner2")
    if backend == "gliner2":
        from .gliner2 import GLiNER2ExtractBackend
        return GLiNER2ExtractBackend(
            model_name=extract_conf.get("model_name", "fastino/gliner2-multi-v1"),
            device=extract_conf.get("device"),
        )
    raise ValueError(f"Unknown extract backend: {backend!r}")


def get_default_schema(conf: dict) -> dict[str, str]:
    """Reads extract.schema (a list of {key, desc} in conf/pipeline_conf.yaml,
    list-of-dicts rather than a plain mapping so key ORDER is preserved and
    stays stable for the UI) into a {key: desc} dict."""
    rows = conf.get("extract", {}).get("schema", [])
    return {row["key"]: row.get("desc", "") for row in rows}


__all__ = [
    "ExtractBackend",
    "get_extract_backend",
    "get_default_schema",
]
