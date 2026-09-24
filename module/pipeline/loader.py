from PIL import Image

from pdf2image import convert_from_path, pdfinfo_from_path


def load_pdf_pages(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """Render every PDF page, in physical page order.

    Page-window selection is intentionally out of scope for the rule-based
    baseline: the downstream extractor needs the complete ordered document
    to find the first VBHC closing/signature page before any attachments.
    ``pdf2image`` preserves the inclusive 1..N order in its returned list.
    """
    return convert_from_path(pdf_path, dpi=dpi)


def load_pdf_page_count(pdf_path: str) -> int:
    """Return the PDF page count without rendering any page."""
    return int(pdfinfo_from_path(pdf_path)["Pages"])


def load_pdf_page_window(
    pdf_path: str, dpi: int = 200, start: int = 0, limit: int | None = None
) -> list[Image.Image]:
    """Render a consecutive page window, in physical page order.

    ``start`` is 0-based; ``limit`` caps how many pages are rendered
    (None/<=0 means to the end of the document). Concatenating every
    window covers the full ordered document exactly once, so callers that
    stream windows only bound peak RAM -- extraction still sees the
    complete document in order.
    """
    kwargs: dict = {}
    if start > 0:
        kwargs["first_page"] = start + 1
    if limit is not None and limit > 0:
        kwargs["last_page"] = start + limit
    return convert_from_path(pdf_path, dpi=dpi, **kwargs)
