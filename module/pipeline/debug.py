import os
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .types import OCRBox, PageBlock
from ..layout.base import LayoutBlock

_BOX_COLOR = (255, 0, 0)
_LABEL_BG = (255, 255, 0)
_LABEL_FG = (0, 0, 0)
_LEGEND_LINE_HEIGHT = 20

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@dataclass
class PipelineDebugTrace:
    """Request-local references needed to build the structured debug response.

    The pipeline instance is shared by concurrent requests, so this collector
    is deliberately created inside ``process_pdf`` and passed down rather than
    stored on ``DocumentPipeline``.
    """

    layout_blocks: list[list[LayoutBlock]] = field(default_factory=list)
    ocr_lines: list[list[OCRBox]] = field(default_factory=list)


def _rounded_bbox(values: list[float] | tuple[float, ...]) -> list[float]:
    return [round(float(value), 1) for value in values]


def build_structured_debug(
    trace: PipelineDebugTrace,
    pages_blocks: list[list[PageBlock]],
    page_image_sizes: list[tuple[int, int]],
    page_image_urls: list[str],
    markdown: str,
    prediction: dict[str, Any],
    extraction_debug: dict[str, Any],
    *,
    document_id: str | None = None,
    source_filename: str | None = None,
    pdf_path: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe trace linking layout, OCR, blocks and extraction.

    ``page_image_sizes`` are (width, height) tuples -- only dimensions are
    reported, so callers need not retain page pixels after saving them.
    """

    pages = []
    for page_index, blocks in enumerate(pages_blocks):
        raw_layout = trace.layout_blocks[page_index]
        raw_ocr = trace.ocr_lines[page_index]
        page_width, page_height = page_image_sizes[page_index]

        line_id_by_object = {id(line): line_id for line_id, line in enumerate(raw_ocr, 1)}
        block_id_by_line_object: dict[int, int] = {}
        for block_id, block in enumerate(blocks, 1):
            for line in block.get("text_items", []):
                block_id_by_line_object[id(line)] = block_id

        debug_blocks = []
        for block_id, block in enumerate(blocks, 1):
            debug_blocks.append({
                "id": block_id,
                "type": str(block.get("type", "")),
                "score": round(float(block.get("score", 0.0)), 4),
                "content_type": str(block.get("content_type", "")),
                "content": block.get("content"),
                "bbox": _rounded_bbox(block.get("bbox", [0, 0, 0, 0])),
                "source_layout_id": block.get("source_layout_id"),
                "ocr_line_ids": [
                    line_id_by_object[id(line)]
                    for line in block.get("text_items", [])
                    if id(line) in line_id_by_object
                ],
            })

        pages.append({
            "page": page_index + 1,
            "width": page_width,
            "height": page_height,
            "image_url": page_image_urls[page_index],
            "layout_blocks": [
                {
                    "id": layout_id,
                    "type": str(block.get("type", "")),
                    "score": (
                        round(float(block["score"]), 4)
                        if block.get("score") is not None
                        else None
                    ),
                    "bbox": _rounded_bbox(block.get("bbox", [0, 0, 0, 0])),
                }
                for layout_id, block in enumerate(raw_layout, 1)
            ],
            "ocr_lines": [
                {
                    "id": line_id,
                    "text": str(line.get("text", "")),
                    "bbox": _rounded_bbox(line.get("bbox", [0, 0, 0, 0])),
                    "quad": [
                        [round(float(x), 1), round(float(y), 1)]
                        for x, y in line.get("quad", [])
                    ],
                    "block_id": block_id_by_line_object.get(id(line)),
                }
                for line_id, line in enumerate(raw_ocr, 1)
            ],
            "blocks": debug_blocks,
        })

    information = prediction.get("information", [{}])[0]
    raw_evidence = extraction_debug.get("evidence", {})
    fields = {}
    for field_name, field_data in information.items():
        value = str(field_data.get("value", ""))
        evidence = list(raw_evidence.get(field_name, []))
        if evidence:
            status = "matched"
        elif not value:
            status = "not_found"
        elif field_name in {"priority_level", "security_level"} and value == "0_BÌNH THƯỜNG":
            status = "default"
        else:
            status = "matched"
        fields[field_name] = {"value": value, "status": status, "evidence": evidence}

    return {
        "version": 2,
        "document_id": document_id,
        "source_filename": source_filename,
        "pdf_path": pdf_path,
        "markdown": markdown,
        "pages": pages,
        "extraction": {
            "document_start_page": extraction_debug.get("document_start_page"),
            "document_end_page": extraction_debug.get("document_end_page"),
            "next_document_start_page": extraction_debug.get("next_document_start_page"),
            "geometry_reliable": bool(extraction_debug.get("geometry_reliable", False)),
            "fields": fields,
        },
    }


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_tagged_box(draw: ImageDraw.ImageDraw, bbox: list[float], label: str, font) -> None:
    x0, y0, x1, y1 = [round(v) for v in bbox]
    draw.rectangle([x0, y0, x1, y1], outline=_BOX_COLOR, width=2)
    tag_w = draw.textlength(label, font=font)
    tag_y0 = max(0, y0 - _LEGEND_LINE_HEIGHT)
    draw.rectangle([x0, tag_y0, x0 + tag_w + 4, y0], fill=_LABEL_BG)
    draw.text((x0 + 2, tag_y0), label, fill=_LABEL_FG, font=font)


def save_input_image(img: Image.Image, out_dir: str, pn: int) -> None:
    """Saves the raw page image exactly as it's about to be fed into the layout model."""
    img.convert("RGB").save(os.path.join(out_dir, f"page_{pn + 1}_input.png"))


def save_layout_debug(img: Image.Image, raw_blocks: list[LayoutBlock], out_dir: str, pn: int) -> None:
    """Draws every layout bbox with its index + predicted type + confidence."""
    canvas = img.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = _load_font(16)
    for i, b in enumerate(raw_blocks):
        score = b.get("score")
        label = f"{i}:{b['type']}:{score:.2f}" if score is not None else f"{i}:{b['type']}"
        _draw_tagged_box(draw, b["bbox"], label, font)
    canvas.save(os.path.join(out_dir, f"page_{pn + 1}_layout.png"))


def save_table_crop(crop: Image.Image, out_dir: str, pn: int, tno: int, suffix: str = "") -> None:
    """Saves a table crop as fed into TSR, after deskewing. `suffix` (e.g.
    "_wire"/"_wireless") is appended to the filename when the caller already
    knows the wired-vs-wireless classification (mineru backend only -- tsr
    has no such concept, so it never passes one)."""
    crop.convert("RGB").save(os.path.join(out_dir, f"page_{pn + 1}_table_{tno}_deskewed{suffix}.png"))


def save_table_ocr_debug(crop: Image.Image, raw_ocr_crop: list, out_dir: str, pn: int, tno: int, suffix: str = "") -> None:
    """Draws every OCR bbox detected inside a table crop (the same 'raw'
    result fed into table_to_markdown), tagged with its index, plus a
    legend at the bottom mapping each index to its recognized text -- for
    debugging column/row mis-assignment in table parsing."""
    base = crop.convert("RGB")
    w, h = base.size
    font = _load_font(14)

    legend_h = 10 + _LEGEND_LINE_HEIGHT * len(raw_ocr_crop)
    canvas = Image.new("RGB", (w, h + legend_h), "white")
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)

    boxes_texts = [(box, text) for box, (text, _score) in raw_ocr_crop]

    for i, (box, _text) in enumerate(boxes_texts):
        x0 = min(p[0] for p in box)
        y0 = min(p[1] for p in box)
        x1 = max(p[0] for p in box)
        y1 = max(p[1] for p in box)
        _draw_tagged_box(draw, [x0, y0, x1, y1], str(i), font)

    y = h + 5
    for i, (_box, text) in enumerate(boxes_texts):
        draw.text((5, y), f"{i}: {text}", fill=(0, 0, 0), font=font)
        y += _LEGEND_LINE_HEIGHT

    canvas.save(os.path.join(out_dir, f"page_{pn + 1}_table_{tno}_ocr{suffix}.png"))


def save_table_backend_compare(mineru_content: str, tsr_content: str, out_dir: str, pn: int, tno: int) -> None:
    """Dumps the mineru (wireless) vs tsr content for the SAME table crop
    side by side, for manual quality comparison only -- never read back by
    the pipeline itself."""
    path = os.path.join(out_dir, f"page_{pn + 1}_table_{tno}_wireless_compare.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("## mineru (wireless)\n\n")
        f.write(mineru_content + "\n\n")
        f.write("## tsr\n\n")
        f.write(tsr_content + "\n")


def save_ocr_debug(img: Image.Image, ocr_boxes: list[OCRBox], out_dir: str, pn: int) -> None:
    """Draws every OCR bbox tagged with its index, plus a legend at the
    bottom of the image mapping each index to its recognized text."""
    base = img.convert("RGB")
    w, h = base.size
    font = _load_font(14)

    legend_h = 10 + _LEGEND_LINE_HEIGHT * len(ocr_boxes)
    canvas = Image.new("RGB", (w, h + legend_h), "white")
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)

    for i, b in enumerate(ocr_boxes):
        _draw_tagged_box(draw, b["bbox"], str(i), font)

    y = h + 5
    for i, b in enumerate(ocr_boxes):
        draw.text((5, y), f"{i}: {b['text']}", fill=(0, 0, 0), font=font)
        y += _LEGEND_LINE_HEIGHT

    canvas.save(os.path.join(out_dir, f"page_{pn + 1}_ocr.png"))
