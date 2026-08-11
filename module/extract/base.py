from typing import Protocol, runtime_checkable


@runtime_checkable
class ExtractBackend(Protocol):
    """Contract a swappable entity-extraction backend must satisfy: OCR'd
    text/markdown + a {field_name: field_description} schema in, extracted
    values per field out. Backend owns its own model lifetime/thread-safety
    (same pattern as LayoutBackend/OCREngine/TableProcessor)."""

    def __call__(self, text: str, schema: dict[str, str]) -> dict[str, list[str]]: ...
