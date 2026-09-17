from PIL import Image

from pdf2image import convert_from_path


def load_pdf_pages(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """Render every PDF page, in physical page order.

    Page-window selection is intentionally out of scope for the rule-based
    baseline: the downstream extractor needs the complete ordered document
    to find the first VBHC closing/signature page before any attachments.
    ``pdf2image`` preserves the inclusive 1..N order in its returned list.
    """
    return convert_from_path(pdf_path, dpi=dpi)
