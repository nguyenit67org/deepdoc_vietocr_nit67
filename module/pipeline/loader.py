from pdf2image import pdfinfo_from_path
from PIL import Image

from pdf2image import convert_from_path

# def load_pdf_pages(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
#     from pdf2image import convert_from_path
#     return convert_from_path(pdf_path, dpi=dpi)


def load_pdf_pages(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """Render only the first and last pages of a PDF (just the first page
    when the PDF has a single page).

    Uses pdfinfo_from_path to learn the total page count without rendering
    anything, then asks pdf2image to render each needed page separately via
    first_page / last_page -- far cheaper than converting the whole PDF and
    slicing in memory when the document is large (only 1-2 pages get rasterised
    instead of N). Mirrors load_pdf_pages' return shape so callers can swap
    the two freely.
    """
    info = pdfinfo_from_path(pdf_path)
    total = info["Pages"]
    if total <= 0:
        return []
    first = convert_from_path(
        pdf_path,
        dpi=dpi,
        first_page=1,
        last_page=1,
    )
    if total == 1:
        return first

    last = convert_from_path(
        pdf_path,
        dpi=dpi,
        first_page=total,
        last_page=total,
    )
    return first + last
