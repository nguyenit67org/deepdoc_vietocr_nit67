"""Deterministic VBHC metadata extraction from OCR/layout page blocks.

This module deliberately has no model dependency.  It consumes the ordered
``PageBlock`` objects produced by :mod:`module.pipeline.document_pipeline`
and applies the anchors/relative layout rules documented in
``docs/vbhc_administrative_layout_rules.md``.

Matching uses folded text (NFKC, case-insensitive, accent-insensitive) so
common OCR accent errors do not hide anchors.  Returned values always come
from the original OCR text, apart from the required date/enum canonical forms
and the inferred ``Công văn`` type.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from ..pipeline.types import PageBlock


TEXT_FIELDS = (
    "type",
    "title",
    "code",
    "documentDate",
    "officeSender",
    "recipients",
    "signer",
    "priority_level",
    "security_level",
    "first_recipients",
    "signer_title",
    "province",
    "receiverDate",
)

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BULLET_RE = re.compile(r"(?:^|\s)[\-–—•]\s+")
_LONG_DATE_RE = re.compile(
    r"ng[aà]y\s*[:.]?\s*(\d{1,2})\s*th[aá]ng\s*(\d{1,2})\s*n[aă]m\s*(\d{4})",
    re.IGNORECASE,
)
_SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{4})(?!\d)")
_CODE_RE = re.compile(
    r"(?:^|\n|\b)\s*S[oố]\s*[:：.]?\s*([0-9A-Za-zÀ-ỹĐđ./\-]+(?:(?!\s*(?:ng[aà]y|v/v|k[ií]nh|n[oơ]i|c[oộ]ng))\s+[0-9A-Za-zÀ-ỹĐđ./\-]+)*)",
    re.IGNORECASE | re.MULTILINE,
)
_INLINE_TYPE_CODE_RE = re.compile(
    r"(?:^|\n|\b)\s*(?:LUẬT|NGHỊ\s+ĐỊNH|NGHỊ\s+QUYẾT|QUYẾT\s+ĐỊNH|"
    r"THÔNG\s+TƯ|CHỈ\s+THỊ)\s+S[oố]\s*[:：.]?\s*"
    r"([0-9]*[A-Za-zÀ-ỹĐđ0-9./\-]+(?:\s*[/\-.]\s*[0-9A-Za-zÀ-ỹĐđ]+)*)",
    re.IGNORECASE | re.MULTILINE,
)
_VV_RE = re.compile(r"(?<!\w)V\s*/\s*v\s*:?")
_FIRST_RECIPIENT_RE = re.compile(r"K[ií]nh\s+g[uử]i\s*[:：]?", re.IGNORECASE)
_RECIPIENT_RE = re.compile(r"N[oơ]i\s+nh[aậ]n\s*[:：]?", re.IGNORECASE)
_SAVE_RE = re.compile(r"(?:^|[;\n])\s*(?:[-–—•]\s*)?L[uư]u\b\s*[:：]?", re.IGNORECASE)

# Longest values first so QUYẾT ĐỊNH LIÊN TỊCH wins over QUYẾT ĐỊNH.
_DOCUMENT_TYPES = (
    "QUYẾT ĐỊNH LIÊN TỊCH",
    "CÔNG BỐ THÔNG TIN BẤT THƯỜNG",
    "NGHỊ QUYẾT LIÊN TỊCH",
    "NGHỊ ĐỊNH",
    "NGHỊ QUYẾT",
    "QUYẾT ĐỊNH",
    "THÔNG TƯ",
    "THÔNG BÁO",
    "CHỈ THỊ",
    "CÔNG ĐIỆN",
    "KẾ HOẠCH",
    "BÁO CÁO",
    "TỜ TRÌNH",
    "LUẬT",
)
_TYPE_RE = re.compile(
    r"(?:^|\n)\s*(" + "|".join(re.escape(v) for v in _DOCUMENT_TYPES) + r")\b",
    re.IGNORECASE,
)
_AUTHORITY_RE = re.compile(
    r"\b(?:TM\.|KT\.|TL\.|TUQ\.|Q\.|CHỦ\s+TỊCH|PHÓ\s+CHỦ\s+TỊCH|"
    r"GIÁM\s+ĐỐC|PHÓ\s+GIÁM\s+ĐỐC|BỘ\s+TRƯỞNG|THỨ\s+TRƯỞNG|"
    r"THỦ\s+TƯỚNG|PHÓ\s+THỦ\s+TƯỚNG|CỤC\s+TRƯỞNG|PHÓ\s+CỤC\s+TRƯỞNG|"
    r"CHÁNH\s+VĂN\s+PHÒNG|PHÓ\s+CHÁNH\s+VĂN\s+PHÒNG|CHỦ\s+NHIỆM|PHÓ\s+CHỦ\s+NHIỆM|"
    r"TỔNG\s+GIÁM\s+ĐỐC|NGƯỜI\s+ĐẠI\s+DIỆN|NGƯỜI\s+ỦY\s+QUYỀN|"
    r"NGƯỜI\s+THỰC\s+HIỆN\s+CÔNG\s+BỐ\s+THÔNG\s+TIN)\b",
    re.IGNORECASE,
)
_ORG_RE = re.compile(
    r"\b(?:ỦY\s+BAN|UỶ\s+BAN|BỘ|SỞ|CỤC|VỤ|BAN|PHÒNG|VĂN\s+PHÒNG|CHÍNH\s+PHỦ|"
    r"QUỐC\s+HỘI|HỘI\s+ĐỒNG|TÒA\s+ÁN|VIỆN\s+KIỂM\s+SÁT|TRUNG\s+TÂM|"
    r"NGÂN\s+HÀNG|CÔNG\s+TY|TỔNG\s+CÔNG\s+TY)\b",
    re.IGNORECASE,
)
_TITLE_WORDS_FOLDED = {
    "tm",
    "kt",
    "tl",
    "tuq",
    "q",
    "chu",
    "tich",
    "pho",
    "giam",
    "doc",
    "bo",
    "truong",
    "nguoi",
    "dai",
    "dien",
    "uy",
    "quyen",
    "ban",
    "hoi",
    "dong",
    "tong",
    "thuc",
    "hien",
    "cong",
    "thong",
    "tin",
    "cuc",
    "chanh",
    "nhiem",
}


@dataclass(frozen=True)
class _Block:
    page: int
    index: int
    type: str
    content_type: str
    text: str
    folded: str
    bbox: tuple[float, float, float, float]
    bbox_pixels: tuple[float, float, float, float]
    source_layout_id: int | None
    geometry_reliable: bool

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


def _plain_text(value: str | None) -> str:
    """Remove internal HTML wrappers without otherwise normalizing output."""
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return _SPACE_RE.sub(" ", value).strip()


def _canonical_date(day: str, month: str, year: str) -> str:
    try:
        parsed = date(int(year), int(month), int(day))
    except ValueError:
        return ""
    return parsed.strftime("%d/%m/%Y")


def _find_date(text: str) -> str:
    for regex in (_LONG_DATE_RE, _SLASH_DATE_RE):
        for match in regex.finditer(unicodedata.normalize("NFKC", text)):
            value = _canonical_date(*match.groups())
            if value:
                return value
    return ""


def _normalise_code(value: str) -> str:
    # 1. Bỏ whitespace đầu/cuối.
    val = value.strip()
    # 2. Xóa toàn bộ dấu `.`.
    val = val.replace(".", "")
    # 3. Rút nhiều whitespace thành một dấu cách.
    val = re.sub(r"\s+", " ", val)
    # 4. Xóa whitespace quanh `/` và `-`.
    val = re.sub(r"\s*([/\-])\s*", r"\1", val)
    # 5. Đổi whitespace còn lại thành `-`.
    val = val.replace(" ", "-")
    # 6. Rút nhiều dấu `-` liên tiếp thành một dấu `-`.
    val = re.sub(r"-+", "-", val)
    # 7. Bỏ `;`, `,`, `:` thừa ở cuối.
    return val.rstrip(";,:")


def _field(value: str) -> dict[str, str]:
    return {"value": value, "type": "string"}


def _zone(block: _Block, *, x0: float = 0.0, x1: float = 1.0, y0: float = 0.0, y1: float = 1.0) -> bool:
    # When crop/rotation transforms cannot be mapped back reliably, anchors
    # remain authoritative and geometry must not hard-reject a candidate.
    if not block.geometry_reliable:
        return True
    return block.x1 >= x0 and block.x0 <= x1 and block.y1 >= y0 and block.y0 <= y1


def _make_blocks(
    pages_blocks: list[list[PageBlock]],
    original_page_sizes: list[tuple[int, int]],
    processed_page_sizes: list[tuple[int, int]],
    crop_offsets: list[tuple[float, float]],
    geometry_reliable: bool,
) -> list[list[_Block]]:
    pages: list[list[_Block]] = []
    for page_index, blocks in enumerate(pages_blocks):
        original_w, original_h = original_page_sizes[page_index]
        processed_w, processed_h = processed_page_sizes[page_index]
        offset_x, offset_y = crop_offsets[page_index]
        converted: list[_Block] = []
        for block_index, block in enumerate(blocks):
            text = _plain_text(block.get("content"))
            if not text:
                continue
            # A signature image can include stamp fragments after the title.
            # Only isolate authority lines when the existing parser found no name;
            # never replace a recognized signer using a partial OCR line.
            if (
                str(block.get("type", "")).lower() == "image"
                and _has_authority_anchor(text)
                and not _split_signature(text)[1]
            ):
                items = sorted(block.get("text_items", []), key=lambda item: (item["bbox"][1], item["bbox"][0]))
                authority_lines = []
                for item in items:
                    line = str(item.get("text", "")).strip()
                    if _has_authority_anchor(line):
                        authority_lines.append(line)
                    elif authority_lines:
                        break
                if authority_lines:
                    text = "\n".join(authority_lines)
            raw_bbox = block.get("bbox", [0.0, 0.0, 0.0, 0.0])
            if geometry_reliable:
                denom_w, denom_h = max(original_w, 1), max(original_h, 1)
                bbox = (
                    (raw_bbox[0] + offset_x) / denom_w,
                    (raw_bbox[1] + offset_y) / denom_h,
                    (raw_bbox[2] + offset_x) / denom_w,
                    (raw_bbox[3] + offset_y) / denom_h,
                )
            else:
                denom_w, denom_h = max(processed_w, 1), max(processed_h, 1)
                bbox = (
                    raw_bbox[0] / denom_w,
                    raw_bbox[1] / denom_h,
                    raw_bbox[2] / denom_w,
                    raw_bbox[3] / denom_h,
                )
            converted.append(
                _Block(
                    page=page_index,
                    index=block_index,
                    type=str(block.get("type", "")).lower(),
                    content_type=str(block.get("content_type", "")),
                    text=text,
                    folded=_fold(text),
                    bbox=bbox,
                    bbox_pixels=tuple(float(value) for value in raw_bbox),
                    source_layout_id=block.get("source_layout_id"),
                    geometry_reliable=geometry_reliable,
                )
            )
        pages.append(converted)
    return pages


def _header_score(blocks: Iterable[_Block]) -> int:
    score = 0
    folded = "\n".join(block.folded for block in blocks if _zone(block, y1=0.45))
    if "cong hoa xa hoi chu nghia viet nam" in folded:
        score += 2
    if "doc lap - tu do - hanh phuc" in folded or "doc lap tu do hanh phuc" in folded:
        score += 1
    if any(_CODE_RE.search(block.text) for block in blocks if _zone(block, y1=0.35)):
        score += 1
    if any(_LONG_DATE_RE.search(block.text) for block in blocks if _zone(block, y1=0.35)):
        score += 1
    if any((_TYPE_RE.search(block.text) or _VV_RE.search(block.text)) for block in blocks if _zone(block, y1=0.45)):
        score += 1
    return score


def _document_start(pages: list[list[_Block]]) -> int:
    for page_index, blocks in enumerate(pages):
        if _header_score(blocks) >= 2:
            return page_index
    return 0


def _next_document_start(pages: list[list[_Block]], start: int) -> int | None:
    for page_index in range(start + 1, len(pages)):
        blocks = pages[page_index]
        folded = "\n".join(block.folded for block in blocks if _zone(block, y1=0.45))
        has_country = "cong hoa xa hoi chu nghia viet nam" in folded
        if has_country and _header_score(blocks) >= 3:
            return page_index
    return None


def _looks_like_person_name(value: str) -> bool:
    value = value.strip(" ,.;:-")
    words = value.split()
    if not 2 <= len(words) <= 6:
        return False
    folded_words = {_fold(word).strip(".") for word in words}
    if folded_words & _TITLE_WORDS_FOLDED:
        return False
    folded = _fold(value)
    if any(token in folded for token in ("trung tam", "cong ty", "uy ban", "chung khoan")):
        return False
    titled = sum(bool(re.match(r"^[A-ZÀ-ỸĐ][a-zà-ỹ]+$", word)) for word in words)
    uppercase = sum(bool(re.match(r"^[A-ZÀ-ỸĐ]{2,}$", word)) for word in words)
    return titled == len(words) or (len(words) >= 3 and uppercase == len(words))


def _has_authority_anchor(value: str) -> bool:
    if _AUTHORITY_RE.search(value):
        return True
    folded = _fold(value)
    # Frequent OCR merge/one-character corruption in the long disclosure
    # title, e.g. "NGƯỜI THỰGHIỆN CÔNG BỐ THÔNG TIN".
    return bool(re.search(r"nguoi\s+thu\w*\s+cong\s+bo\s+thong\s+tin", folded))


def _split_signature(text: str) -> tuple[str, str]:
    """Return (title, signer) while keeping the OCR spelling/punctuation."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        for index in range(len(lines) - 1, -1, -1):
            if _looks_like_person_name(lines[index]):
                return " ".join(lines[:index]).strip(), lines[index].strip()

    if _has_authority_anchor(text):
        organization = re.search(
            r"\b(?:TR\w*NG\s+T[AÂ]M\s+)?L[ƯU]U\s+K[ÝY]\s+CH[ỨU]NG\s+KHO[AÁ]N\b",
            text,
            re.IGNORECASE,
        )
        if organization:
            return " ".join(text[: organization.start()].split()).strip(), ""

    # Layout sometimes merges the entire signature image into one line.
    words = text.strip().split()
    for width in range(min(6, len(words)), 1, -1):
        suffix = " ".join(words[-width:]).strip(" ,.;:-")
        if _looks_like_person_name(suffix):
            title = " ".join(words[:-width]).strip()
            return title, suffix
    return (" ".join(text.split()).strip(), "") if _has_authority_anchor(text) else ("", "")


def _signature_candidates(blocks: Iterable[_Block]) -> list[tuple[_Block, str, str]]:
    candidates = []
    for block in blocks:
        if block.geometry_reliable:
            width = block.x1 - block.x0
            # Signature/authority blocks are compact and centred in the
            # right column.  They can occur high on a sparse closing page, so
            # vertical position is deliberately not a hard constraint.
            # Rectangle overlap is too permissive here:
            # a full-width body paragraph mentioning a minister/chairperson
            # otherwise becomes a convincing false signature.
            if block.cx < 0.55 or width > 0.62:
                continue
        if len(block.text) > 350:
            continue
        title, signer = _split_signature(block.text)
        has_authority = _has_authority_anchor(block.text)
        visual_signature = (
            block.type in {"image", "seal"}
            and signer
            and (block.x1 - block.x0) >= 0.15
            and block.x0 < 0.88
            # All-uppercase suffixes cut out of a company seal are commonly
            # organization-name fragments, not the signer's printed name.
            and not (_ORG_RE.search(block.text) and signer.isupper())
        )
        # A person-like suffix in an ordinary body paragraph is not enough:
        # require an authority/title anchor, or visual signature/seal layout.
        if has_authority or visual_signature:
            candidates.append((block, title, signer))
    return candidates


def _closing_page(pages: list[list[_Block]], start: int, limit: int) -> int:
    for page_index in range(start, limit + 1):
        blocks = pages[page_index]
        recipients = [block for block in blocks if _RECIPIENT_RE.search(block.text) and _zone(block, x1=0.62, y0=0.45)]
        signatures = _signature_candidates(blocks)
        right_seal = any(block.type in {"seal", "image"} and _zone(block, x0=0.40, y0=0.40) for block in blocks)
        strong_signature = any(
            title and signer and (not block.geometry_reliable or block.y0 >= 0.40 or block.type in {"image", "seal"})
            for block, title, signer in signatures
        )
        if (recipients and (signatures or right_seal)) or strong_signature:
            return page_index
        # ``Nơi nhận`` is itself a strong closing anchor when it is in the
        # lower-left zone; many scans do not OCR the signature reliably.
        if recipients:
            return page_index
    return limit


def _evidence(block: _Block, rule: str, value: str) -> dict[str, Any]:
    return {
        "page": block.page + 1,
        "block": block.index + 1,
        "block_id": block.index + 1,
        "block_type": block.type,
        "source_layout_id": block.source_layout_id,
        "rule": rule,
        "value": value,
        "source_text": block.text,
        "bbox": [round(v, 1) for v in block.bbox_pixels],
        "bbox_normalized": [round(v, 4) for v in block.bbox],
        "geometry_reliable": block.geometry_reliable,
    }


def _is_address_or_noise(text: str) -> bool:
    folded = _fold(text)
    if any(token in folded for token in ("dia chi", "tru so", "dien thoai", "website", "email", "fax", "dt:", "tel:")):
        return True
    # Street / ward / house number patterns indicating postal addresses
    if re.search(r"\b(?:cmt8|đường|duong|ngõ|ngo|ngách|ngach|hẻm|hem|ấp|ap|khu phố|khu pho)\b", text, re.IGNORECASE):
        return True
    # "Số <digits>" followed by comma or address words (e.g. "Số 1253, CMT8" or "Số 10 đường")
    if re.search(r"(?:s[oố]\s+\d+\s*,|s[oố]\s+\d+\s+(?:đường|duong|phố|pho))\b", text, re.IGNORECASE):
        return True
    return False


def _is_valid_code_value(raw: str) -> bool:
    val = raw.strip(" ;,:")
    if not val or len(val) < 2:
        return False
    if "," in val:
        return False
    # All statutory Vietnamese administrative codes contain a slash '/'
    # (e.g. 12/QĐ-UBND, 03/NQ-ĐHCĐ, 4977/BVHTTDL-VP, /TB-QLNY, 36/2026/QH16)
    if "/" in val:
        return True
    # If no slash, must contain digits AND uppercase letters, not just plain numbers
    has_alpha = bool(re.search(r"[A-Za-zÀ-ỸĐđ]", val))
    has_digit = bool(re.search(r"\d", val))
    return has_alpha and has_digit


def _extract_code(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, _Block | None]:
    # Relative layout anchors in header
    country_blocks = [
        b for b in blocks
        if _zone(b, y1=0.35) and (
            "cong hoa xa hoi chu nghia viet nam" in b.folded
            or "doc lap - tu do - hanh phuc" in b.folded
            or "doc lap tu do hanh phuc" in b.folded
        )
    ]
    country_block = country_blocks[0] if country_blocks else None

    # Resolve the upper-left issuing authority relative to the country/header
    # before testing code text. This keeps body references and Công báo numbers
    # out of the candidate region even when their strings match the regex.
    office_blocks = [
        block
        for block in blocks
        if _zone(block, y1=0.30)
        and _ORG_RE.search(block.text)
        and (not block.geometry_reliable or block.cx <= 0.52)
        and (not block.geometry_reliable or country_block is None or block.cx < country_block.cx)
        and "cong bao" not in block.folded
    ]
    office_block = min(office_blocks, key=lambda block: (block.y0, block.x0)) if office_blocks else None

    date_blocks = [
        b for b in blocks
        if _zone(b, x0=0.40, y1=0.40) and "ngay" in b.folded
    ]
    date_block = date_blocks[0] if date_blocks else None

    # Filter candidate blocks by relative region and exclusion rules
    candidates: list[_Block] = []
    for block in blocks:
        if block.geometry_reliable:
            # Code region: upper portion of page, left/center column
            if block.cx > 0.60 or block.y0 > 0.35:
                continue
            if country_block and block.x0 >= country_block.cx:
                continue
            if date_block and block.x0 >= date_block.x0 + 0.15:
                continue
        # Exclusion rules: ignore citations, body articles, cong bao, addresses
        if "cong bao" in block.folded or block.folded.startswith("can cu") or "căn cứ" in block.text.lower():
            continue
        if block.folded.startswith("xet ") or block.folded.startswith("dieu ") or re.search(r"\bdieu\s+\d+", block.folded):
            continue
        match = _CODE_RE.search(block.text)
        if _is_address_or_noise(block.text):
            continue
        candidates.append(block)

    # Prefer candidates below the identified issuing-authority region. Keep
    # other header candidates as a fallback because OCR/layout may merge or
    # vertically overlap the authority and code blocks.
    candidates.sort(
        key=lambda block: (
            0
            if office_block is None
            or block.index == office_block.index
            or block.y0 >= office_block.y1 - 0.04
            else 1,
            block.y0,
            block.x0,
        )
    )

    # Pass 1: Primary regex: Line starts with Số / Số: (highest priority)
    line_start_code_re = re.compile(
        r"(?:^|\n)\s*S[oố]\s*[:：.]?\s*([0-9A-Za-zÀ-ỹĐđ./\-]+(?:(?!\s*(?:ng[aà]y|v/v|k[ií]nh|n[oơ]i|c[oộ]ng))\s+[0-9A-Za-zÀ-ỹĐđ./\-]+)*)",
        re.IGNORECASE,
    )
    for block in candidates:
        match = line_start_code_re.search(block.text)
        if match:
            raw_val = match.group(1).strip()
            if _is_valid_code_value(raw_val):
                value = _normalise_code(raw_val)
                evidence["code"].append(_evidence(block, "number-anchor", value))
                return value, block

    # Pass 2: Inline document type code (e.g. QUỐC HỘI Nghị quyết số: 36/2026/QH16)
    for block in blocks:
        if block.geometry_reliable and block.y0 > 0.42:
            continue
        if (
            "cong bao" in block.folded
            or block.folded.startswith("can cu")
            or block.folded.startswith("xet ")
            or block.folded.startswith("v/v")
            or block.folded.startswith("ve viec")
        ):
            continue
        match = _INLINE_TYPE_CODE_RE.search(block.text)
        if match:
            raw_val = match.group(1).strip()
            if _is_valid_code_value(raw_val):
                value = _normalise_code(raw_val)
                evidence["code"].append(_evidence(block, "document-type-number-anchor", value))
                return value, block

    # Pass 3: General Số regex inside candidates (not preceded by address/noise)
    for block in candidates:
        match = _CODE_RE.search(block.text)
        if match:
            prefix = block.text[: match.start()]
            if not _is_address_or_noise(prefix):
                raw_val = match.group(1).strip()
                if _is_valid_code_value(raw_val):
                    value = _normalise_code(raw_val)
                    evidence["code"].append(_evidence(block, "number-anchor", value))
                    return value, block

    # Pass 4: Fallback for geometry_reliable=False
    if any(not b.geometry_reliable for b in blocks[:10]):
        for block in blocks[:10]:
            if "cong bao" in block.folded or block.folded.startswith("can cu") or block.folded.startswith("xet "):
                continue
            if _is_address_or_noise(block.text):
                continue
            match = _CODE_RE.search(block.text) or _INLINE_TYPE_CODE_RE.search(block.text)
            if match:
                raw_val = match.group(1).strip()
                if _is_valid_code_value(raw_val):
                    value = _normalise_code(raw_val)
                    evidence["code"].append(_evidence(block, "fallback-text-code-anchor", value))
                    return value, block

    return "", None


def _extract_date_province(
    blocks: list[_Block],
    code_block: _Block | None,
    evidence: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    for block in blocks:
        if block.geometry_reliable and (block.cx < 0.56 or block.y0 > 0.24):
            continue
        if code_block and block.geometry_reliable and block.y0 < code_block.y0 - 0.04:
            continue
        if "ngay" not in block.folded:
            continue
        issuance_text = re.split(
            r"(?:CÔNG\s+VĂN|VĂN\s+BẢN)?\s*ĐẾN\b",
            block.text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        value = _find_date(issuance_text)
        if not value:
            continue
        evidence["documentDate"].append(_evidence(block, "issuance-date", value))
        match = re.search(r"^\s*(.+?)\s*,\s*ng[aà]y\b", issuance_text, re.IGNORECASE)
        province = match.group(1).strip() if match else ""
        if province:
            evidence["province"].append(_evidence(block, "place-before-date", province))
        return value, province
    # OCR can damage every digit/keyword in the issuance date while leaving
    # the leading place intact.  Keep province independently when a short
    # place-like prefix remains at the start of a top metadata block.
    for block in blocks:
        if block.geometry_reliable and block.y0 > 0.32:
            continue
        if code_block and block.geometry_reliable and block.y0 < code_block.y0 - 0.04:
            continue
        match = re.match(r"^\s*([A-ZÀ-ỸĐ][^,\n]{1,40})\s*,", block.text)
        if not match:
            continue
        province = match.group(1).strip()
        if any(token in _fold(province) for token in ("dia chi", "website", "fax", "dien thoai", "dt:")):
            continue
        if 1 <= len(province.split()) <= 6 and not _ORG_RE.search(province):
            evidence["province"].append(_evidence(block, "place-prefix-date-unreadable", province))
            return "", province
    return "", ""


def _clean_office_sender_text(text: str) -> str:
    # Strip any inline code anchor if merged in same block
    code_m = _CODE_RE.search(text)
    if code_m:
        text = text[: code_m.start()].strip()
    # Layout may merge the issuing authority with the first-recipient block.
    text = _FIRST_RECIPIENT_RE.split(text, maxsplit=1)[0].strip()
    # Strip any document type
    text = re.sub(
        r"\b(?:" + "|".join(re.escape(v) for v in _DOCUMENT_TYPES) + r")\b.*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    # Strip address lines
    lines = []
    for line in text.splitlines():
        if _is_address_or_noise(line):
            break
        lines.append(line)
    return " ".join(" ".join(lines).split())


def _extract_office_sender(
    blocks: list[_Block],
    code_block: _Block | None,
    evidence: dict[str, list[dict[str, Any]]],
) -> str:
    max_y = (code_block.y0 + 0.03) if code_block and code_block.geometry_reliable else 0.25
    candidates = []
    for block in blocks:
        if block.geometry_reliable and (block.cx > 0.52 or block.y1 > max_y):
            continue
        if "cong hoa xa hoi chu nghia viet nam" in block.folded:
            continue
        if any(token in block.folded for token in ("ky boi", "thoi gian ky", "sao y", "cong bao")):
            continue
        if block.type == "header":
            continue
        if _ORG_RE.search(block.text):
            candidates.append(block)

    if candidates:
        # Sort candidates top-to-bottom by y0 to preserve reading order
        candidates = sorted(candidates, key=lambda b: (b.y0, b.x0))
        cluster: list[_Block] = []
        for c in candidates:
            if not cluster or (c.y0 - cluster[-1].y1 <= 0.06):
                cluster.append(c)
            else:
                break

        parts: list[tuple[str, _Block]] = []
        for b in cluster:
            cleaned = _clean_office_sender_text(b.text)
            if cleaned:
                parts.append((cleaned, b))

        if parts:
            val = " ".join(p[0] for p in parts)
            for _, b in parts:
                evidence["officeSender"].append(_evidence(b, "upper-left-organization", val))
            return val

    # Corporate letterheads commonly center the issuing company rather than using statutory left column
    for block in blocks:
        if block.geometry_reliable and block.y1 > max_y:
            continue
        if block.type == "header":
            continue
        if "cong hoa xa hoi chu nghia viet nam" in block.folded:
            continue
        if any(token in block.folded for token in ("ky boi", "thoi gian ky", "sao y", "dia chi", "cong bao")):
            continue
        if _ORG_RE.search(block.text):
            cleaned = _clean_office_sender_text(block.text)
            if cleaned:
                evidence["officeSender"].append(_evidence(block, "upper-left-organization", cleaned))
                return cleaned

    for block in blocks:
        match = re.search(r"\bT[eê]n\s+c[oô]ng\s+ty\s*[:：]\s*(.+)$", block.text, re.IGNORECASE)
        if match:
            raw_val = match.group(1).strip()
            clean_val = " ".join(raw_val.split())
            evidence["officeSender"].append(_evidence(block, "company-name-anchor", clean_val))
            return clean_val

    if code_block:
        match = _CODE_RE.search(code_block.text) or _INLINE_TYPE_CODE_RE.search(code_block.text)
        if match:
            prefix = code_block.text[: match.start()].strip()
            prefix = re.sub(
                r"\b(?:" + "|".join(re.escape(v) for v in _DOCUMENT_TYPES) + r")\b.*$",
                "",
                prefix,
                flags=re.IGNORECASE,
            ).strip()
            if prefix and _ORG_RE.search(prefix):
                clean_val = " ".join(prefix.split())
                evidence["officeSender"].append(
                    _evidence(code_block, "organization-above-code-in-same-block", clean_val)
                )
                return clean_val
    return ""


def _extract_type_title(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    # Use the earliest structural cue: a named heading wins when it precedes
    # ``V/v``; otherwise ``V/v`` identifies a Công văn and remains in title.
    first_vv: tuple[int, re.Match[str]] | None = None
    for block_index, block in enumerate(blocks):
        if _zone(block, y0=0.14, y1=0.52):
            vv_match = _VV_RE.search(block.text)
            if vv_match:
                first_vv = (block_index, vv_match)
                break

    for block_index, block in enumerate(blocks):
        if not _zone(block, y0=0.14, y1=0.52):
            continue
        match = _TYPE_RE.search(block.text)
        if not match:
            continue
        if first_vv and (
            first_vv[0] < block_index or (first_vv[0] == block_index and first_vv[1].start() < match.start())
        ):
            break
        document_type = match.group(1).strip()
        tail = block.text[match.end() :].strip(" \n:-–—")
        if re.fullmatch(r"s[oố]\s*[:.]?\s*[0-9A-Za-zÀ-ỹĐđ./\-\s]+", tail, re.IGNORECASE):
            tail = ""
        title = tail
        title_evidence: list[tuple[_Block, str, str]] = []
        if title:
            title_evidence.append((block, "text-after-document-type", title))
        if not title:
            following: list[str] = []
            for candidate in blocks[max(0, block_index - 2) : block_index]:
                vv_match = _VV_RE.search(candidate.text)
                if vv_match:
                    candidate_value = candidate.text[vv_match.start() :].strip()
                    following.append(candidate_value)
                    title_evidence.append((candidate, "v-v-title-before-document-type", candidate_value))
            for candidate in blocks[block_index + 1 : block_index + 5]:
                if _FIRST_RECIPIENT_RE.search(candidate.text):
                    break
                if candidate.y0 - block.y1 > 0.14:
                    break
                if re.fullmatch(r"\d+", candidate.text.strip()):
                    continue
                if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                    continue
                if candidate.type in {"doc_title", "paragraph_title", "text"} and _zone(
                    candidate, x0=0.16, x1=0.88, y1=0.58
                ):
                    following.append(candidate.text)
                    title_evidence.append((candidate, "title-continuation", candidate.text))
            title = "\n".join(following).strip()
        evidence["type"].append(_evidence(block, "named-document-type", document_type))
        for title_block, rule, matched_value in title_evidence:
            evidence["title"].append(_evidence(title_block, rule, matched_value))
        return document_type, title

    for block in blocks:
        if not _zone(block, y0=0.14, y1=0.52):
            continue
        match = _VV_RE.search(block.text)
        if match:
            title = block.text[match.start() :].strip()
            evidence["type"].append(_evidence(block, "v-v-structure", "Công văn"))
            evidence["title"].append(_evidence(block, "v-v-title-preserved", title))
            return "Công văn", title
    return "", ""


def _clean_recipient_value(value: str) -> str:
    value = _SAVE_RE.split(value, maxsplit=1)[0]
    value = value.replace("\n", "; ")
    value = _BULLET_RE.sub("; ", value)
    value = re.sub(r"\s*;\s*", "; ", value)
    value = re.sub(r"(?:;\s*)+", "; ", value)
    value = re.sub(r"^[.;,:\s]+", "", value)
    value = re.sub(r"[;:\s]+$", "", value)
    return value.strip(" ;")


def _extract_anchor_value(
    blocks: list[_Block],
    regex: re.Pattern[str],
    field_name: str,
    rule: str,
    evidence: dict[str, list[dict[str, Any]]],
) -> str:
    for block_index, block in enumerate(blocks):
        match = regex.search(block.text)
        if not match:
            continue
        value = block.text[match.end() :]
        if field_name == "first_recipients":
            value = re.sub(
                r"\bNg[aà]y\s*[:：]\s*\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{4}",
                " ",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(r"\bS[oố]\s*[:：]\s*[0-9][0-9 .\-/]*$", "", value, flags=re.IGNORECASE)
        if field_name == "recipients" and (not value.strip() or value.strip().isdigit()) and block.geometry_reliable:
            # Layout can split the label and each bullet into independent blocks.
            # Follow the same column by geometry, not layout reading-order indices.
            parts = []
            previous_y = block.y1
            for candidate in sorted(blocks, key=lambda item: (item.y0, item.x0)):
                if candidate.index == block.index or candidate.y0 < block.y0:
                    continue
                if abs(candidate.x0 - block.x0) > 0.06 or candidate.cx > 0.62:
                    continue
                if candidate.y0 - previous_y > 0.045:
                    break
                if re.match(r"^\s*[-–—•]?\s*L[uư]u\b", candidate.text, re.IGNORECASE):
                    break
                if not parts and not re.match(r"^\s*[-–—•]", candidate.text):
                    break
                if _RECIPIENT_RE.search(candidate.text):
                    break
                parts.append(candidate.text)
                previous_y = candidate.y1
                evidence[field_name].append(_evidence(candidate, "recipient-column-continuation", candidate.text))
            if parts:
                value = "\n".join(parts)
        value = _clean_recipient_value(value)
        continuation_block: _Block | None = None
        continuation_value = ""
        if field_name == "first_recipients" and value and ";" not in value:
            for candidate in blocks[block_index + 1 : block_index + 5]:
                if candidate.geometry_reliable and candidate.y0 > block.y1 + 0.06:
                    break
                if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                    continue
                if len(candidate.text) > 160 or re.search(
                    r"\b(?:tru so|ten cong ty|ten to chuc|dia chi|noi dung|" r"can cu|thuc hien|dieu\s+\d+)\b",
                    candidate.folded,
                ):
                    break
                if _ORG_RE.search(candidate.text):
                    continuation = _clean_recipient_value(candidate.text)
                    if continuation:
                        value = f"{value}; {continuation}"
                        continuation_block = candidate
                        continuation_value = continuation
                    break
        if value:
            evidence[field_name].append(_evidence(block, rule, value))
            if continuation_block is not None:
                evidence[field_name].append(_evidence(continuation_block, f"{rule}-continuation", continuation_value))
            return value
    return ""


def _extract_levels(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    priority = "0_BÌNH THƯỜNG"
    security = "0_BÌNH THƯỜNG"
    for block in blocks:
        if block.geometry_reliable:
            # Security/urgency stamps occupy a small upper-left margin area;
            # body paragraphs merely overlapping that area are not stamps.
            if block.cx > 0.30 or block.y0 < 0.08 or block.y1 > 0.48:
                continue
        if len(block.text) > 80:
            continue
        folded = block.folded
        if "tuyet mat" in folded:
            security = "3_TUYỆT MẬT"
        elif "toi mat" in folded:
            security = "2_TỐI MẬT"
        elif re.search(r"(?:^|\W)mat(?:$|\W)", folded):
            security = "1_MẬT"
        if "thuong khan" in folded:
            priority = "3_THƯỢNG KHẨN"
        elif "hoa toc" in folded:
            priority = "1_HỎA TỐC"
        elif re.search(r"(?:^|\W)khan(?:$|\W)", folded):
            priority = "2_KHẨN"
        if security != "0_BÌNH THƯỜNG":
            evidence["security_level"].append(_evidence(block, "security-stamp", security))
        if priority != "0_BÌNH THƯỜNG":
            evidence["priority_level"].append(_evidence(block, "priority-stamp", priority))
    return priority, security


def _extract_receiver_date(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> str:
    for block in blocks:
        has_den = bool(re.search(r"(?:^|\W)den(?:$|\W)", block.folded))
        has_stamp_phrase = any(anchor in block.folded for anchor in ("cong van den", "van ban den"))
        has_stamp_fields = has_den and "ngay:" in block.folded and len(block.text) <= 180
        starts_with_den = bool(re.match(r"^\s*ĐẾN\b", block.text, re.IGNORECASE)) and len(block.text) <= 80
        if not (has_stamp_phrase or has_stamp_fields or starts_with_den):
            continue
        if len(block.text) > 220 and not any(anchor in block.folded for anchor in ("cong van den", "van ban den")):
            continue
        value = _find_date(block.text)
        if "ngay" in block.folded:
            if value:
                evidence["receiverDate"].append(_evidence(block, "arrival-stamp-date", value))
                return value
            # The stamp has its own date slot but OCR did not produce a valid
            # calendar value.  Do not substitute a nearby body/issuance date.
            continue
        # Arrival stamp text is often split into adjacent layout blocks.
        nearby_blocks = [
            candidate
            for candidate in blocks
            if candidate.index != block.index
            and re.match(r"^\s*ngay\s*[:：]", candidate.folded)
            and len(candidate.text) <= 80
            and candidate.x0 <= block.x1 + 0.12
            and candidate.x1 >= block.x0 - 0.12
            and candidate.y0 <= block.y1 + 0.14
            and candidate.y1 >= block.y0 - 0.14
        ]
        joined = "\n".join([block.text, *(candidate.text for candidate in nearby_blocks)])
        if "ngay" in _fold(joined):
            value = _find_date(joined)
            if value:
                evidence["receiverDate"].append(_evidence(block, "split-arrival-stamp-date", value))
                for candidate in nearby_blocks:
                    evidence["receiverDate"].append(_evidence(candidate, "split-arrival-stamp-date-part", value))
                return value
    return ""


def _extract_signature(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    titles: list[str] = []
    signers: list[str] = []
    candidates = sorted(_signature_candidates(blocks), key=lambda item: (item[0].y0, item[0].x0))
    for block, title, signer in candidates:
        clean_title = " ".join(title.split()).strip() if title else ""
        if clean_title and clean_title not in titles:
            titles.append(clean_title)
            evidence["signer_title"].append(_evidence(block, "signature-authority", clean_title))
        if signer and signer not in signers:
            signers.append(signer)
            evidence["signer"].append(_evidence(block, "signature-name", signer))
        if title and not signer:
            for name_block in blocks:
                if name_block.type == "seal" or name_block.y0 < block.y0:
                    continue
                if name_block.geometry_reliable:
                    if name_block.y0 > block.y1 + 0.22 or abs(name_block.cx - block.cx) > 0.24:
                        continue
                if _looks_like_person_name(name_block.text) and name_block.text not in signers:
                    signers.append(name_block.text)
                    evidence["signer"].append(_evidence(name_block, "name-below-signature-authority", name_block.text))
                    break
    if not signers:
        for block in sorted(blocks, key=lambda b: (-b.y0, b.x0)):
            if block.type in {"seal", "image"}:
                continue
            if block.geometry_reliable and (block.cx < 0.50 or block.y0 < 0.35):
                continue
            cleaned = block.text.strip()
            lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
            for candidate_line in reversed(lines):
                if _looks_like_person_name(candidate_line) and candidate_line not in signers:
                    signers.append(candidate_line)
                    evidence["signer"].append(_evidence(block, "fallback-signature-zone-name", candidate_line))
                    break
            if signers:
                break
    return "; ".join(titles), "; ".join(signers)


def extract_vbhc(
    pages_blocks: list[list[PageBlock]],
    original_page_sizes: list[tuple[int, int]],
    processed_page_sizes: list[tuple[int, int]],
    crop_offsets: list[tuple[float, float]],
    *,
    geometry_reliable: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract the first VBHC document and return ``(prediction, debug)``.

    ``processing_time`` is initialized to zero; the caller owns the full
    pipeline timer and overwrites it immediately before returning/persisting
    the final response.
    """
    lengths = {len(pages_blocks), len(original_page_sizes), len(processed_page_sizes), len(crop_offsets)}
    if len(lengths) != 1:
        raise ValueError("pages_blocks, page sizes and crop_offsets must have equal lengths")

    evidence: dict[str, list[dict[str, Any]]] = {field: [] for field in TEXT_FIELDS}
    if not pages_blocks:
        values = {field: "" for field in TEXT_FIELDS}
        values["priority_level"] = "0_BÌNH THƯỜNG"
        values["security_level"] = "0_BÌNH THƯỜNG"
        information = {field: _field(values[field]) for field in TEXT_FIELDS}
        return {"information": [information], "processing_time": 0.0}, {
            "document_start_page": None,
            "document_end_page": None,
            "geometry_reliable": geometry_reliable,
            "evidence": evidence,
        }

    pages = _make_blocks(
        pages_blocks,
        original_page_sizes,
        processed_page_sizes,
        crop_offsets,
        geometry_reliable,
    )
    start = _document_start(pages)
    next_start = _next_document_start(pages, start)
    search_limit = (next_start - 1) if next_start is not None else len(pages) - 1
    end = _closing_page(pages, start, search_limit)

    header_blocks = pages[start]
    closing_blocks = pages[end]
    code, code_block = _extract_code(header_blocks, evidence)
    document_date, province = _extract_date_province(header_blocks, code_block, evidence)
    office_sender = _extract_office_sender(header_blocks, code_block, evidence)
    document_type, title = _extract_type_title(header_blocks, evidence)
    first_recipients = _extract_anchor_value(
        header_blocks, _FIRST_RECIPIENT_RE, "first_recipients", "kinh-gui-anchor", evidence
    )
    recipients = _extract_anchor_value(closing_blocks, _RECIPIENT_RE, "recipients", "noi-nhan-anchor", evidence)
    signer_title, signer = _extract_signature(closing_blocks, evidence)
    priority, security = _extract_levels(header_blocks, evidence)
    receiver_date = _extract_receiver_date(header_blocks, evidence)

    values = {
        "type": document_type,
        "title": title,
        "code": code,
        "documentDate": document_date,
        "officeSender": office_sender,
        "recipients": recipients,
        "signer": signer,
        "priority_level": priority,
        "security_level": security,
        "first_recipients": first_recipients,
        "signer_title": signer_title,
        "province": province,
        "receiverDate": receiver_date,
    }
    information = {field: _field(values[field]) for field in TEXT_FIELDS}
    prediction = {"information": [information], "processing_time": 0.0}
    debug = {
        "document_start_page": start + 1,
        "document_end_page": end + 1,
        "next_document_start_page": next_start + 1 if next_start is not None else None,
        "geometry_reliable": geometry_reliable,
        "evidence": evidence,
    }
    return prediction, debug


__all__ = ["extract_vbhc"]
