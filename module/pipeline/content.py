import re

from ..layout import LayoutLabelSchema
from .types import PageBlock

# ── Ghép nội dung block: nối dòng bằng " " + tự nhận diện list item ────────
#
# Nhận diện 1 dòng là "list item" nếu nó bắt đầu bằng marker kiểu:
#   a) b) c)  /  a. b. c.  /  1) 2) 3)  /  1. 2. 3.
# (chữ cái đơn hoặc số, theo sau bởi ')' hoặc '.', rồi đến khoảng trắng)
ALPHA_ITEM_RE = re.compile(r"^\s*[a-zđ][\.\)]\s+")  # a) b) c) đ)...
# CHỈ chữ THƯỜNG -- nếu cho phép cả chữ HOA, tiêu đề mục La Mã kiểu
# 'I. Người sử dụng đất...' (1 ký tự HOA + dấu chấm) sẽ bị nhận NHẦM thành
# marker list 'alpha', kéo theo mọi dòng thường phía sau bị fix
# nối-dòng-word-wrap nuốt chung thành 1 khối text liên tục.
NUM_ITEM_RE = re.compile(r"^\s*\d+[\.\)]\s+")  # 1. 2. 3)...
MIN_LIST_ITEMS = 2
# cần ÍT NHẤT bấy nhiêu dòng list-item LIÊN TIẾP, CÙNG NHÓM (cùng là chữ
# cái, hoặc cùng là số) trong CÙNG 1 block mới được bọc <ul><li>. Marker
# khác nhóm (số xen chữ cái) hoặc chỉ có 1 dòng lẻ -> giữ nguyên text
# thường, KHÔNG bọc <ul> -- tránh hiện bullet giả khiến nhiều dòng/block
# không liên quan trông như 1 danh sách liên tục.


def _list_item_type(line: str) -> str | None:
    """Trả về 'alpha' nếu khớp marker chữ cái (a) b) c)...), 'num' nếu khớp
    marker số (1. 2. 3)...), None nếu không phải list item."""
    if NUM_ITEM_RE.match(line):
        return "num"
    if ALPHA_ITEM_RE.match(line):
        return "alpha"
    return None


def build_block_content(line_texts: list[str], preserve_breaks: bool = False) -> str:
    """
    Ghép các "hàng" (mỗi hàng = 1 dòng chữ thật, đã gom theo tb_rows) thành
    1 chuỗi content dạng HTML-trong-Markdown:
      - Các dòng THƯỜNG liên tiếp -> nối bằng ' ' (space) thành 1 đoạn văn
        liên tục -- dòng OCR chỉ là chỗ bị ngắt do word-wrap theo khổ trang
        gốc, không phải ranh giới đoạn thật, nên không giữ thành xuống dòng
        cứng trong output. Trừ khi `preserve_breaks=True` (dùng cho block
        title/header -- xem document_pipeline.py's call site): ở đó mỗi
        dòng THƯỜNG là 1 đơn vị hiển thị có chủ đích (vd tên công ty 1
        dòng, địa chỉ 1 dòng khác), nên nối bằng '<br>\n' để giữ xuống dòng
        thay vì gộp.
      - Các dòng LIST ITEM liên tiếp, CÙNG NHÓM marker (toàn 'alpha' hoặc
        toàn 'num') -> gom thành 1 khối <ul>, mỗi dòng là 1 <li>...</li> --
        chỉ khi số dòng liên tiếp cùng nhóm >= MIN_LIST_ITEMS.
      - Nếu marker đổi nhóm giữa chừng (ví dụ '1. ...' rồi 'a) ...') ->
        đóng khối list hiện tại (theo đúng rule MIN_LIST_ITEMS ở trên) và
        mở khối MỚI cho nhóm marker khác, KHÔNG gộp chung 1 <ul>.
      - Nếu chỉ có 1 dòng lẻ khớp marker (dù đứng riêng hay bị đổi nhóm
        ngay sau đó), coi như text thường, không bọc <ul>.
      - 1 khối <ul> vẫn nối với text-run liền kề bằng '\n' (ranh giới
        block-level HTML thật sự, không thể gộp bằng space/<br>) -- chỉ 2
        text-run liền kề nhau mới áp dụng rule ' ' hoặc '<br>\n' ở trên.
    """
    plain_sep = "<br>\n" if preserve_breaks else " "
    segments = []  # list các đoạn HTML đã hoàn chỉnh (text-run hoặc <ul>)
    buffer = []  # dòng thường đang gom (chưa flush)
    list_buffer = []  # dòng list-item đang gom (chưa flush)
    list_type = None  # 'alpha' hoặc 'num' -- nhóm marker của list_buffer hiện tại

    def flush_buffer():
        if buffer:
            segments.append(("text", plain_sep.join(buffer)))
            buffer.clear()

    def flush_list():
        nonlocal list_type
        if len(list_buffer) >= MIN_LIST_ITEMS:
            items = "\n".join(f"<li>{t}</li>" for t in list_buffer)
            segments.append(("ul", f"<ul>\n{items}\n</ul>"))
        elif len(list_buffer) == 1:
            segments.append(("text", list_buffer[0]))
        list_buffer.clear()
        list_type = None

    for line in line_texts:
        t = _list_item_type(line)
        if t is not None:
            if list_buffer and t != list_type:
                # marker đổi nhóm (num <-> alpha) -- đóng khối cũ, mở khối mới
                flush_list()
            if not list_buffer:
                flush_buffer()  # chuyển từ text-mode sang list-mode
            list_buffer.append(line)
            list_type = t
        else:
            if list_buffer:
                # dòng không có marker nhưng đang ở GIỮA 1 danh sách
                # (list_buffer chưa flush) -- coi đây là phần bị NGẮT XUỐNG
                # DÒNG (word-wrap) của CHÍNH item cuối cùng, nối tiếp vào
                # item đó thay vì bẻ gãy danh sách.
                list_buffer[-1] = list_buffer[-1] + " " + line
            else:
                buffer.append(line)
    flush_buffer()
    flush_list()

    if not segments:
        return ""

    result = segments[0][1]
    for i in range(1, len(segments)):
        prev_kind, _ = segments[i - 1]
        cur_kind, cur_content = segments[i]
        sep = "\n" if (prev_kind == "ul" or cur_kind == "ul") else plain_sep
        result += sep + cur_content
    return result


# ── JSON / Markdown builders ──────────────────────────────────────────────────


def build_json(
    file_label: str,
    pages_blocks: list[list[PageBlock]],
    crop_offsets: list[tuple[float, float]] | None = None,
    page_image_urls: list[str] | None = None,
) -> dict:
    """`crop_offsets[pn]` is the (x0, y0) top-left corner of that page's
    whitespace-crop IN THE ORIGINAL (uncropped, freshly-rendered-at-pdf.dpi)
    page image -- see crop_whitespace_before_layout. (0, 0) when no crop
    happened. Exposed per-page as "crop_offset" so a client rendering its OWN
    copy of the original page (e.g. via pdf.js, without re-running this
    pipeline) can add it back to every block's bbox to realign an overlay --
    otherwise bbox coords (relative to the CROPPED image) would be offset
    from an uncropped re-render. Defaults to all-(0,0) so existing callers
    that don't have this handy (there are none left in this codebase, but
    keeps the signature non-breaking) still get a valid response.

    `page_image_urls[pn]`, if given, is a URL to the EXACT image layout/OCR
    ran on for that page -- every block's bbox is relative to THIS image
    directly, no crop_offset math needed. Only process_pdf() (the /ocr/pdf
    route) supplies this (see its docstring for why); other callers leave it
    None and every page's "page_image" comes back null."""
    if crop_offsets is None:
        crop_offsets = [(0.0, 0.0)] * len(pages_blocks)
    return {
        "file": file_label,
        "pages": [
            {
                "page": pn + 1,
                "crop_offset": [round(v, 1) for v in crop_offsets[pn]],
                "page_image": page_image_urls[pn] if page_image_urls else None,
                "blocks": [
                    {
                        "id": j + 1,
                        "type": b["type"],
                        "bbox": [round(v, 1) for v in b["bbox"]],
                        "score": round(b.get("score", 0), 4),
                        "content_type": b["content_type"],
                        "content": b.get("content"),
                    }
                    for j, b in enumerate(blocks)
                ],
            }
            for pn, blocks in enumerate(pages_blocks)
        ],
    }


def build_markdown(pages_blocks: list[list[PageBlock]], label_schema: LayoutLabelSchema) -> str:
    """
    Mỗi block là 1 khối Markdown riêng (heading / paragraph / table) nên
    PHẢI nối bằng dòng trống ('\n\n'), không phải 1 '\n' -- nếu chỉ nối
    bằng 1 '\n', nhiều trình render Markdown sẽ gộp 2 block liền kề thành
    cùng 1 dòng hiển thị.
    """
    lines = []
    for pn, blocks in enumerate(pages_blocks):
        lines.append(f"<!-- Page {pn + 1} -->")
        for b in blocks:
            if b["content_type"] == "skip":
                continue
            content = (b.get("content") or "").strip()
            if not content:
                continue
            btype = b["type"].lower()
            if b["content_type"] == "table":
                lines.append(content)
            elif btype in label_schema.title_types:
                lines.append(f"# {content}")
            elif btype in label_schema.h2_types:
                lines.append(f"## {content}")
            else:
                lines.append(content)
    return "\n\n".join(lines)
