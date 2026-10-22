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
# Inline filing suffix ("... Ban TGĐ Lưu VT, TK..."): "Lưu" followed by a
# records-office token can only be the filing line, never a recipient surname
# (surnames are followed by a given name, not VT/VP/HS/...).
_SAVE_SUFFIX_RE = re.compile(
    r"[\s,;]\(?(?:[-–—•]\s*)?L[uư]u\s*[:：]?\s*(?:VT|VP|HS|HĐ|HD|TK|HC|QT)\b.*$",
    re.IGNORECASE,
)

# A stamp serial riding inside a recipient value ("số 1.772") names no
# addressee: only segments without any real (3+ letter) word are dropped, so
# genuine references ("Số: 123/BQP") survive via their lettered token.
_SERIAL_ONLY_SEGMENT_RE = re.compile(r"^\s*S[oố]\s*[:：.]?\s*[\d\s./\-]*$", re.IGNORECASE)
# Longest values first so QUYẾT ĐỊNH LIÊN TỊCH wins over QUYẾT ĐỊNH.
_DOCUMENT_TYPES = (
    "QUYẾT ĐỊNH LIÊN TỊCH",
    "CÔNG BỐ THÔNG TIN BẤT THƯỜNG",
    "VĂN BẢN HỢP NHẤT",
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
# Folded (accent-insensitive) document-type match; the concrete map/regex are
# built right after _fold() is defined below.
_TYPE_FOLDED_TO_CANONICAL: dict[str, str] = {}
_TYPE_FOLDED_RE: re.Pattern[str] | None = None
_AUTHORITY_RE = re.compile(
    r"\b(?:TM\.|KT\.|TL\.|TUQ\.|Q\.|CHỦ\s+TỊCH|PHÓ\s+CHỦ\s+TỊCH|"
    r"GIÁM\s+ĐỐC|PHÓ\s+GIÁM\s+ĐỐC|BỘ\s+TRƯỞNG|THỨ\s+TRƯỞNG|"
    r"THỦ\s+TƯỚNG|PHÓ\s+THỦ\s+TƯỚNG|CỤC\s+TRƯỞNG|PHÓ\s+CỤC\s+TRƯỞNG|"
    r"CHÁNH\s+VĂN\s+PHÒNG|PHÓ\s+CHÁNH\s+VĂN\s+PHÒNG|CHỦ\s+NHIỆM|PHÓ\s+CHỦ\s+NHIỆM|"
    r"TỔNG\s+GIÁM\s+ĐỐC|NGƯỜI\s+ĐẠI\s+DIỆN|NGƯỜI\s+ỦY\s+QUYỀN|"
    r"NGƯỜI\s+CÔNG\s+BỐ\s+THÔNG\s+TIN\w*|"
    r"NGƯỜI\s+THỰC\s+HIỆN\s+CÔNG\s+BỐ\s+THÔNG\s+TIN)\b",
    re.IGNORECASE,
)
_ORG_RE = re.compile(
    r"\b(?:ỦY\s+BAN|UỶ\s+BAN|BỘ|SỞ|CỤC|VỤ|BAN|PHÒNG|VĂN\s+PHÒNG|CHÍNH\s+PHỦ|"
    r"THỦ\s+TƯỚNG|QUỐC\s+HỘI|HỘI\s+ĐỒNG|TÒA\s+ÁN|VIỆN\s+KIỂM\s+SÁT|TRUNG\s+TÂM|"
    r"NGÂN\s+HÀNG|CÔNG\s+TY|TỔNG\s+CÔNG\s+TY)\b",
    re.IGNORECASE,
)
# Folded (accent-insensitive) counterpart of _ORG_RE.  OCR frequently damages a
# single diacritic (e.g. "BỌ TÀI CHÍNH" for "BỘ TÀI CHÍNH"); folding both sides
# recovers those anchors without touching output spelling.  Word boundaries are
# required: bare-substring matching would fire on "Số:" prefixes.  "ban" must
# not match the promulgation verb "ban hành", only committee nouns ("Ban").
_ORG_FOLDED_RE = re.compile(
    r"\b(?:uy ban|bo|so|cuc|vu|ban(?! hanh)|phong|van phong|chinh phu|"
    r"thu tuong|quoc hoi|hoi dong|toa an|vien kiem sat|trung tam|"
    r"ngan hang|cong ty|tong cong ty)\b"
)
# Digital-signature / PDF annotations that must never be mistaken for the
# statutory issuing authority, matched on folded text.
_ANNOTATION_FOLDED_MARKERS = (
    "nguoi ky",
    "nguoi ki",
    "thoi gian ky",
    "co quan phat hanh",
    "cong bao",
    "ky boi",
    "chu ky so",
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
    "toa",
}


def _has_org_keyword(text: str, folded: str | None = None) -> bool:
    """Match issuing-authority keywords on raw or folded (accent-insensitive) text."""
    if _ORG_RE.search(text):
        return True
    folded_text = folded if folded is not None else _fold(text)
    # "Sở" and "Số" both fold to "so": a code anchor ("Số:", "Số 12/...")
    # is never an issuing authority, so those occurrences are removed before
    # matching.  A genuine "Sở ..." (letters, no colon after "Sở") survives.
    disambiguated = re.sub(r"\bso\s*[:：]", " ", folded_text)
    disambiguated = re.sub(r"\bso\s+(?=\d)", " ", disambiguated)
    return bool(_ORG_FOLDED_RE.search(disambiguated))


def _is_annotation_header(text: str, folded: str | None = None) -> bool:
    """Detect digital-signature / PDF annotation blocks, never an officeSender."""
    folded_text = folded if folded is not None else _fold(text)
    if any(marker in folded_text for marker in _ANNOTATION_FOLDED_MARKERS):
        return True
    return "@" in text or "mail:" in folded_text


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


def _build_folded_type_matcher() -> None:
    """Build the accent-insensitive document-type matcher (needs _fold)."""
    global _TYPE_FOLDED_TO_CANONICAL, _TYPE_FOLDED_RE
    _TYPE_FOLDED_TO_CANONICAL = {_fold(v): v for v in _DOCUMENT_TYPES}
    _TYPE_FOLDED_RE = re.compile(
        r"(?:^|\n)\s*(" + "|".join(sorted(_TYPE_FOLDED_TO_CANONICAL, key=len, reverse=True)) + r")\b"
    )


_build_folded_type_matcher()


def _match_document_type(block: _Block) -> tuple[str, str, int] | None:
    """Match a line-start document-type heading; return (canonical, tail, line).

    Matching runs on folded text so a single damaged diacritic in the heading
    (e.g. "CHÌ THỊ") still resolves to the canonical label ("CHỈ THỊ").
    ``tail`` is the remainder of the same original line after the heading.
    """
    assert _TYPE_FOLDED_RE is not None
    # The consolidation label is a wrapper, never the instrument's type.
    # Continue within the same block as well as across blocks: OCR may merge
    # "VĂN BẢN HỢP NHẤT\nTHÔNG TƯ\n..." into one region.
    match = next((m for m in _TYPE_FOLDED_RE.finditer(block.folded)
                  if m.group(1) != "van ban hop nhat"), None)
    if match is None:
        return None
    canonical = _TYPE_FOLDED_TO_CANONICAL[match.group(1)]
    # Group 1 starts at the heading itself (the leading (?:^|\n)\s* may span
    # lines), so its line index maps back to the original line 1:1.
    line_index = block.folded.count("\n", 0, match.start(1))
    original_lines = block.text.splitlines()
    if line_index >= len(original_lines):
        return canonical, "", line_index
    words = original_lines[line_index].split()
    drop = len(canonical.split())
    tail_first = " ".join(words[drop:])
    remaining = "\n".join([tail_first, *original_lines[line_index + 1 :]]).strip(" \n:-–—")
    return canonical, remaining, line_index


def _normalise_code(value: str) -> str:
    # 1. Bỏ whitespace đầu/cuối.
    val = value.strip()
    # 2. Xóa toàn bộ dấu `.`.
    val = val.replace(".", "")
    # 3. Rút nhiều whitespace thành một dấu cách.
    val = re.sub(r"\s+", " ", val)
    # 4. Xóa whitespace quanh `/` và `-`.
    val = re.sub(r"\s*([/\-])+\s*", r"\1", val)
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


def _skipped_adoption_text(block: PageBlock) -> str:
    """Read an adoption assertion misclassified as a footnote, for date KIE only.

    Do not mutate the skipped block or make arbitrary footnotes available to
    header, type, issuer, signature or document-boundary extraction.
    """
    if str(block.get("type", "")).lower() != "footnote" or block.get("content_type") != "skip":
        return ""
    items = sorted(block.get("text_items", []), key=lambda item: (item["bbox"][1], item["bbox"][0]))
    text = "\n".join(str(item.get("text", "")).strip() for item in items if str(item.get("text", "")).strip())
    folded = _fold(text)
    if not re.match(r"^(?:luat|nghi quyet|van ban|quy che|quy dinh)\s+nay\s+(?:da\s+)?duoc\b", folded):
        return ""
    if not re.search(r"\bthong\s+qua\s+ngay\b", folded):
        return ""
    return text


def _make_blocks(
    pages_blocks: list[list[PageBlock]],
    original_page_sizes: list[tuple[int, int]],
    processed_page_sizes: list[tuple[int, int]],
    crop_offsets: list[tuple[float, float]],
    geometry_reliable: bool,
    *,
    skipped_adoption_only: bool = False,
) -> list[list[_Block]]:
    pages: list[list[_Block]] = []
    for page_index, blocks in enumerate(pages_blocks):
        original_w, original_h = original_page_sizes[page_index]
        processed_w, processed_h = processed_page_sizes[page_index]
        offset_x, offset_y = crop_offsets[page_index]
        converted: list[_Block] = []
        for block_index, block in enumerate(blocks):
            text = _skipped_adoption_text(block) if skipped_adoption_only else _plain_text(block.get("content"))
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
        # A body clause can mention the country's full name. That substring,
        # especially in a tall paragraph crossing the header search window,
        # is not an independent national heading.
        has_country = any(
            re.fullmatch(
                r"cong hoa xa hoi chu nghia viet nam[ .]*(?:\s+doc lap.*)?",
                line.strip(),
            )
            for block in blocks if _zone(block, y1=0.45)
            for line in block.folded.splitlines()
        )
        if has_country and _header_score(blocks) >= 3:
            return page_index
    return None


def _looks_like_person_name(value: str) -> bool:
    value = value.strip(" ,.;:-")
    words = value.split()
    if not 2 <= len(words) <= 6:
        return False
    folded_words = {_fold(word).strip(".") for word in words}
    title_hits = folded_words & _TITLE_WORDS_FOLDED
    if title_hits:
        # Authority vocabulary veto.  Statutory titles are ALL-CAPS, so any
        # hit disqualifies an all-caps candidate.  Title-case printed names
        # often share one syllable with authority words ("Hiền"/"Hiện",
        # "Thông", "Công"): a single hit is not disqualifying there, only
        # two or more authority words mark a title ("Chủ tịch").
        if any(ch.islower() for ch in value):
            if len(title_hits) >= 2:
                return False
        else:
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


# Adjacent word pairs that only occur inside authority/government phrases, never
# inside a Vietnamese personal name.  Used to reject all-uppercase authority
# text ("CHÍNH PHỦ THỦ TƯỚNG") that _looks_like_person_name would accept.
_AUTHORITY_COMPOUNDS_FOLDED = (
    ("chinh", "phu"),
    ("thu", "tuong"),
    ("bo", "truong"),
    ("thu", "truong"),
    ("pho", "thu"),
    ("uy", "ban"),
    ("quoc", "hoi"),
    ("tong", "giam"),
    ("chanh", "van"),
    ("chu", "tich"),
)


def _contains_authority_compound(folded_words: list[str]) -> bool:
    for first, second in _AUTHORITY_COMPOUNDS_FOLDED:
        for index in range(len(folded_words) - 1):
            if folded_words[index] == first and folded_words[index + 1] == second:
                return True
    return False


def _looks_like_signature_name(value: str) -> bool:
    """Person-name check hardened against all-uppercase authority phrases.

    Title-case names always use the base check.  All-uppercase candidates
    additionally must not contain an authority compound ("CHÍNH PHỦ",
    "THỦ TƯỚNG", ...): those are titles, never signers.
    """
    if not _looks_like_person_name(value):
        return False
    # Note: [a-zà-ỹ] also matches UPPERCASE Vietnamese (U+1E00 block mixes
    # cases inside à-ỹ), so case must be tested with islower() instead.
    if any(ch.islower() for ch in value):
        return True
    return not _contains_authority_compound(_fold(value).split())


def _split_signature(text: str) -> tuple[str, str]:
    """Return (title, signer) while keeping the OCR spelling/punctuation."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        for index in range(len(lines) - 1, -1, -1):
            if _looks_like_signature_name(lines[index]):
                return _strip_signature_serial(" ".join(lines[:index]).strip()), lines[index].strip()

    if _has_authority_anchor(text):
        organization = re.search(
            r"\b(?:TR\w*NG\s+T[AÂ]M\s+)?L[ƯU]U\s+K[ÝY]\s+CH[ỨU]NG\s+KHO[AÁ]N\b",
            text,
            re.IGNORECASE,
        )
        if organization:
            return _strip_signature_serial(" ".join(text[: organization.start()].split()).strip()), ""

    # Layout sometimes merges the entire signature image into one line.
    words = text.strip().split()
    for width in range(min(6, len(words)), 1, -1):
        suffix = " ".join(words[-width:]).strip(" ,.;:-")
        if _looks_like_signature_name(suffix):
            title = " ".join(words[:-width]).strip()
            return _strip_signature_serial(title), suffix
    return (_strip_signature_serial(" ".join(text.split()).strip()), "") if _has_authority_anchor(text) else ("", "")


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
        if has_authority and len(block.text) > 120:
            # A body paragraph can mention an authority mid-sentence
            # ("... giao cho Hội đồng ... Ban Tổng Giám đốc Công ty thực
            # hiện ..."): only a block LED by the anchor is a signature.
            anchor_pos = min([match.start() for match in _AUTHORITY_RE.finditer(block.text)] or [0])
            if anchor_pos > 40:
                has_authority = False
                title, signer = "", ""
        visual_signature = (
            block.type in {"image", "seal"}
            and signer
            and (block.x1 - block.x0) >= 0.15
            and block.x0 < 0.88
            # All-uppercase suffixes cut out of a company seal are commonly
            # organization-name fragments, not the signer's printed name.
            and not (_ORG_RE.search(block.text) and signer.isupper())
            # Seal-stamp remnants ("ONG HOA VII" clipped from "CỘNG HÒA...") are
            # all-caps fragments built from seal vocabulary; a printed signer
            # name either keeps Title case or avoids that vocabulary.
            and not _is_seal_name_fragment(signer)
        )
        # A person-like suffix in an ordinary body paragraph is not enough:
        # require an authority/title anchor, or visual signature/seal layout.
        if has_authority or visual_signature:
            candidates.append((block, title, signer))
    return candidates


# Seal-vocabulary fragments clipped out of a round seal ("ONG HOA VII" from
# "CỘNG HÒA...") are all-caps and built from seal vocabulary; a printed signer
# name either keeps Title case or avoids that vocabulary.  Bare "hoa" alone is
# NOT enough (it is also a Vietnamese given name): it only counts with a
# co-occurring seal token or a serial/roman-numeral fragment ("VII", "001").
_SEAL_NAME_TOKENS = ("doc lap", "xa hoi", "viet nam", "chung thuc", "sao y")
_SEAL_ROMAN_TOKENS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _is_seal_name_fragment(value: str) -> bool:
    if any(ch.islower() for ch in value):
        return False
    folded_words = _fold(value).split()
    folded = " ".join(folded_words)
    if any(token in folded for token in _SEAL_NAME_TOKENS):
        return True
    if "hoa" in folded_words and (
        any(word in _SEAL_ROMAN_TOKENS or any(ch.isdigit() for ch in word) for word in folded_words)
        or "cong" in folded_words
    ):
        return True
    return False


def _closing_page(pages: list[list[_Block]], start: int, limit: int) -> int:
    consolidated = any(
        "van ban hop nhat" in b.folded or re.search(r"\bvbhn\s*-", b.folded)
        for b in pages[start] if _zone(b, y1=0.35)
    )
    if consolidated:
        # Consolidation footnotes may quote old closing/signature material.
        # The authentication is the closing of this wrapper, not that quote.
        for page_index in range(start, limit + 1):
            if any("xac thuc van ban hop nhat" in b.folded for b in pages[page_index]):
                return page_index
    for page_index in range(start, limit + 1):
        blocks = pages[page_index]
        # The "Nơi nhận" anchor itself is a strong closing signal.  No lower
        # vertical bound: crop-normalized coordinates shift with the detected
        # margins (e.g. a stamp-strip crop maps the closing block above 0.45
        # in original-page space).  The left-column bound stays to avoid
        # right-column quotations.
        recipients = [block for block in blocks if _RECIPIENT_RE.search(block.text) and _zone(block, x1=0.62)]
        signatures = _signature_candidates(blocks)
        right_seal = any(block.type in {"seal", "image"} and _zone(block, x0=0.40, y0=0.40) for block in blocks)
        strong_signature = any(
            title and signer and (not block.geometry_reliable or block.y0 >= 0.40 or block.type in {"image", "seal"})
            for block, title, signer in signatures
        )
        if (recipients and (signatures or right_seal)) or strong_signature:
            return page_index
        # ``Nơi nhận`` is itself a strong closing anchor when it is in the
        # left column; many scans do not OCR the signature reliably.
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


@dataclass(frozen=True)
class _HeaderFrame:
    """Default header geometry anchored on the Quốc hiệu/Tiêu ngữ block.

    The country header (top-right) is the reference milestone: the issuing
    authority sits to its LEFT, the code sits BELOW the authority (still left
    of the country), and the place/date line sits to the RIGHT under the
    country.  All relations are relative overlaps, never absolute cutoffs, so
    crops and narrow/wide layouts keep working.

    This is the DEFAULT flow.  Documents without a country header (corporate
    letterheads, foreign forms) get ``country=None`` and callers fall back to
    the absolute-zone behavior — that is the edge-case path, not a failure.
    """

    country: _Block | None
    office: _Block | None


def _find_country_block(blocks: list[_Block]) -> _Block | None:
    candidates = [
        block
        for block in blocks
        if _zone(block, y1=0.22)
        and (
            "cong hoa xa hoi chu nghia viet nam" in block.folded
            or "doc lap - tu do - hanh phuc" in block.folded
            or "doc lap tu do hanh phuc" in block.folded
        )
    ]
    if not candidates:
        return None
    # Rightmost country block is the true right column; a merged
    # "office + country" block further left is handled by the office fallback.
    return max(candidates, key=lambda block: (block.x0, block.y0))


def _header_frame(blocks: list[_Block]) -> _HeaderFrame:
    country = _find_country_block(blocks)
    office: _Block | None = None
    if country is not None:
        left_orgs = [
            block
            for block in blocks
            if _zone(block, y1=0.30)
            and _has_org_keyword(block.text, block.folded)
            and (not block.geometry_reliable or block.x1 <= country.x0 + 0.05)
            and (not block.geometry_reliable or block.y1 >= 0.04)
            and not _is_annotation_header(block.text, block.folded)
            and "cong bao" not in block.folded
            and re.match(r"^\s*mau\s+\d+", block.folded) is None
        ]
        if left_orgs:
            office = min(left_orgs, key=lambda block: (block.y0, block.x0))
        elif _has_org_keyword(country.text, country.folded):
            # Merged "office + country" single block: the authority is the
            # country block's left part (split later by _clean_office_sender_text).
            office = country
    return _HeaderFrame(country=country, office=office)


def _code_match_reaches_line_end(block_text: str, match_end: int) -> bool:
    """True when nothing but whitespace/punctuation follows the code value.

    Statutory codes close their line ("Số: 8871/VPCP-CN" and nothing after);
    body citations ("... số 81/2013/NĐ-CP ngày 19 tháng 7 ...") continue.
    """
    return re.match(r"[\s;:,.]*(\n|$)", block_text[match_end:]) is not None


def _extract_xac_thuc_office(
    blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]
) -> tuple[str, _Block | None]:
    """Issuing authority restated beside a VBHN authentication label.

    Only fires on closing pages carrying an "XÁC THỰC" anchor, and only takes
    a short organization block in the same column band.  Stamp/arrival blocks
    naming other institutions are excluded by the same markers as the header
    flow.
    """
    anchors = [block for block in blocks if "xac thuc van ban hop nhat" in block.folded]
    if not anchors:
        return "", None
    anchor = min(anchors, key=lambda block: (block.y0, block.x0))
    # OCR may put the issuer and authentication label in one text block.
    lines = anchor.text.splitlines()
    anchor_line = next((i for i, line in enumerate(lines)
                        if "xac thuc van ban hop nhat" in _fold(line)), 0)
    if anchor_line:
        value = _clean_office_sender_text(" ".join(lines[:anchor_line]))
        if len(value) <= 100 and _office_candidate_valid(value):
            evidence["officeSender"].append(_evidence(anchor, "closing-xac-thuc-office", value))
            return value, anchor
    best: tuple[float, _Block, str] | None = None
    for block in blocks:
        if block is anchor or "xac thuc" in block.folded:
            continue
        text = _clean_office_sender_text(block.text)
        if not text or len(text) > 100:
            continue
        if not _has_org_keyword(text, _fold(text)):
            continue
        if _is_annotation_header(block.text, block.folded):
            continue
        if "van ban den" in block.folded or "cong van den" in block.folded:
            continue
        if any(token in block.folded for token in ("ky boi", "cong bao", "@")):
            continue
        if block.geometry_reliable:
            if abs(block.cx - anchor.cx) > 0.30:
                continue
            gap = anchor.y0 - block.y1
            if gap < -0.02 or gap > 0.25:
                continue
            score = abs(block.cx - anchor.cx) + max(gap, 0.0)
        else:
            score = 0.0
        if best is None or score < best[0]:
            best = (score, block, text)
    if best is None:
        return "", None
    _, block, value = best
    evidence["officeSender"].append(_evidence(block, "closing-xac-thuc-office", value))
    return value, block


def _extract_code(
    blocks: list[_Block],
    evidence: dict[str, list[dict[str, Any]]],
    *,
    office_block: _Block | None = None,
    date_block_hint: _Block | None = None,
    country_block: _Block | None = None,
) -> tuple[str, _Block | None]:
    # QH-anchored flow: the caller resolves the header frame ONCE
    # (country -> office -> date/province -> code) and passes the anchors in.
    # Direct calls without anchors (unit tests) fall back to local resolution.
    if office_block is None or country_block is None:
        frame = _header_frame(blocks)
        if country_block is None:
            country_block = frame.country
        if office_block is None:
            office_block = frame.office
    country_block = country_block
    if office_block is None:
        # Edge-case path: legacy absolute-zone office resolution.
        office_blocks = [
            block
            for block in blocks
            if _zone(block, y1=0.30)
            and _has_org_keyword(block.text, block.folded)
            and (not block.geometry_reliable or block.cx <= 0.52)
            and (not block.geometry_reliable or country_block is None or block.cx < country_block.cx)
            and "cong bao" not in block.folded
            and re.match(r"^\s*mau\s+\d+", block.folded) is None
            and not _is_annotation_header(block.text, block.folded)
        ]
        office_block = min(office_blocks, key=lambda block: (block.y0, block.x0)) if office_blocks else None

    date_block = date_block_hint
    if date_block is None:
        date_blocks = [b for b in blocks if _zone(b, x0=0.40, y1=0.40) and "ngay" in b.folded]
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
        # Exclusion rules: ignore form templates, citations, body articles,
        # cong bao, addresses.  A "Mẫu 08/..." template block carries a cited
        # decision serial ("... số 600190-SGDHN ..."), never the document code.
        if "cong bao" in block.folded or block.folded.startswith("can cu") or "căn cứ" in block.text.lower():
            continue
        if re.match(r"^\s*mau\s+\d+", block.folded):
            continue
        if (
            block.folded.startswith("xet ")
            or block.folded.startswith("dieu ")
            or re.search(r"\bdieu\s+\d+", block.folded)
        ):
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
            (
                0
                if office_block is None or block.index == office_block.index or block.y0 >= office_block.y1 - 0.04
                else 1
            ),
            block.y0,
            block.x0,
        )
    )

    # Pass 0: Consolidated-heading code without a "Số" anchor
    # (e.g. "VĂN BẢN HỢP NHẤT 05/2026/VBHN-TT-BTP" at the very top of the
    # header).  This must run before the generic "Số" passes: body citations
    # such as "Thông tư số 07/2022/..." would otherwise win and cascade into
    # wrong date/province skips.  Restricted to the top header strip so body
    # references can never match.
    consolidated_re = re.compile(
        r"VĂN\s+BẢN\s+HỢP\s+NHẤT\s*:?\s*" r"([0-9][0-9A-Za-zÀ-ỹĐđ./\-]*(?:\s*[0-9A-Za-zÀ-ỹĐđ./\-]+)*)",
        re.IGNORECASE,
    )
    for block in blocks:
        if block.geometry_reliable and (block.y0 > 0.20 or block.cx > 0.60):
            continue
        if "cong bao" in block.folded:
            continue
        if re.match(r"^\s*mau\s+\d+", block.folded):
            continue
        match = consolidated_re.search(block.text)
        if match:
            raw_val = match.group(1).strip()
            if _is_valid_code_value(raw_val):
                value = _normalise_code(raw_val)
                evidence["code"].append(_evidence(block, "consolidated-heading-code", value))
                return value, block

    # Pass 1: Primary regex: Line starts with Số / Số:
    # Collect every match, then prefer the value that closes its line:
    # statutory codes end their line while body citations continue.
    line_start_code_re = re.compile(
        r"(?:^|\n)\s*S[oố]\s*[:：.]?\s*([0-9A-Za-zÀ-ỹĐđ./\-]+(?:(?!\s*(?:ng[aà]y|v/v|k[ií]nh|n[oơ]i|c[oộ]ng))\s+[0-9A-Za-zÀ-ỹĐđ./\-]+)*)",
        re.IGNORECASE,
    )
    pass1: list[tuple[int, int, _Block, str]] = []
    for order, block in enumerate(candidates):
        match = line_start_code_re.search(block.text)
        if match:
            raw_val = match.group(1).strip()
            if _is_valid_code_value(raw_val):
                eol = 0 if _code_match_reaches_line_end(block.text, match.end()) else 1
                pass1.append((eol, order, block, raw_val))
    if pass1:
        pass1.sort(key=lambda item: (item[0], item[1]))
        _, _, block, raw_val = pass1[0]
        value = _normalise_code(raw_val)
        evidence["code"].append(_evidence(block, "number-anchor", value))
        return value, block

    # Pass 2: Inline document type code (e.g. QUỐC HỘI Nghị quyết số: 36/2026/QH16)
    pass2: list[tuple[int, int, _Block, str]] = []
    for block in blocks:
        if block.geometry_reliable and block.y0 > 0.42:
            continue
        if (
            "cong bao" in block.folded
            or re.match(r"^\s*mau\s+\d+", block.folded)
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
                eol = 0 if _code_match_reaches_line_end(block.text, match.end()) else 1
                pass2.append((eol, block.y0, block, raw_val))
    if pass2:
        pass2.sort(key=lambda item: (item[0], item[1]))
        _, _, block, raw_val = pass2[0]
        value = _normalise_code(raw_val)
        evidence["code"].append(_evidence(block, "document-type-number-anchor", value))
        return value, block

    # Pass 3: General Số regex inside candidates (not preceded by address/noise)
    pass3: list[tuple[int, int, _Block, str]] = []
    for order, block in enumerate(candidates):
        match = _CODE_RE.search(block.text)
        if match:
            prefix = block.text[: match.start()]
            if not _is_address_or_noise(prefix):
                raw_val = match.group(1).strip()
                if _is_valid_code_value(raw_val):
                    eol = 0 if _code_match_reaches_line_end(block.text, match.end()) else 1
                    pass3.append((eol, order, block, raw_val))
    if pass3:
        pass3.sort(key=lambda item: (item[0], item[1]))
        _, _, block, raw_val = pass3[0]
        value = _normalise_code(raw_val)
        evidence["code"].append(_evidence(block, "number-anchor", value))
        return value, block

    # Pass 4: Fallback for geometry_reliable=False
    if any(not b.geometry_reliable for b in blocks[:10]):
        for block in blocks[:10]:
            if "cong bao" in block.folded or block.folded.startswith("can cu") or block.folded.startswith("xet "):
                continue
            if re.match(r"^\s*mau\s+\d+", block.folded):
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
    *,
    country_block: _Block | None = None,
) -> tuple[str, str]:
    # QH-anchored flow: province + documentDate live RIGHT of / UNDER the
    # country header.  Without a country anchor (edge case) the absolute
    # right-column zone applies.  Province is resolved INDEPENDENTLY of the
    # date parse: a place prefix ("Hà Nam, ngày ...") yields province even
    # when OCR destroys the date itself.
    # documentDate only accepts the long "ngày ... tháng ... năm ..." form
    # (accented or not); a bare slash/dot date belongs to an arrival stamp,
    # never to the issuance line.
    scored: list[tuple[int, float, _Block, str, str]] = []
    place_hits: list[tuple[float, _Block, str]] = []
    for block in blocks:
        if block.geometry_reliable:
            if country_block is not None:
                if block.x1 < country_block.x0 - 0.10:
                    continue
                if block.y0 < country_block.y0 - 0.05 or block.y0 > country_block.y1 + 0.14:
                    continue
            elif block.cx < 0.56 or block.y0 > 0.24:
                continue
        if code_block and block.geometry_reliable and block.y0 < code_block.y0 - 0.04:
            continue
        # Body citations ("Căn cứ Luật ... ngày ...", "Xét ...", "Điều N")
        # carry calendar dates but are never the issuance line.
        if block.folded.startswith("can cu") or block.folded.startswith("xet "):
            continue
        if re.search(r"\bdieu\s+\d+", block.folded):
            continue
        if "ngay" not in block.folded:
            continue
        issuance_text = re.split(
            r"(?:CÔNG\s+VĂN|VĂN\s+BẢN)?\s*ĐẾN\b",
            block.text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        place_match = re.search(r"^\s*(.+?)\s*,\s*ng[aà]y\b", issuance_text, re.IGNORECASE)
        place = place_match.group(1).strip() if place_match else ""
        place_valid = bool(place and 1 <= len(place.split()) <= 6 and not _has_org_keyword(place, _fold(place)))
        value = ""
        for long_match in _LONG_DATE_RE.finditer(unicodedata.normalize("NFKC", issuance_text)):
            value = _canonical_date(*long_match.groups())
            if value:
                break
        if value:
            scored.append((0 if place_valid else 1, block.y0, block, value, place if place_valid else ""))
        if place_valid:
            place_hits.append((block.y0, block, place))
    value = ""
    date_block: _Block | None = None
    if scored:
        scored.sort(key=lambda item: (item[0], item[1]))
        _, _, date_block, value, _ = scored[0]
        evidence["documentDate"].append(_evidence(date_block, "issuance-date", value))
    province = ""
    province_block: _Block | None = None
    if place_hits:
        # Prefer the place on the chosen date line; otherwise earliest place.
        same_line = [hit for hit in place_hits if date_block is not None and hit[1].index == date_block.index]
        candidates = same_line or sorted(place_hits, key=lambda item: item[0])
        _, province_block, province = candidates[0]
        evidence["province"].append(_evidence(province_block, "place-before-date", province))
    # OCR can damage every digit/keyword in the issuance date while leaving
    # the leading place intact.  Keep province independently when a short
    # place-like prefix remains at the start of a top metadata block.
    if not province:
        for block in blocks:
            if block.geometry_reliable:
                if country_block is not None:
                    if block.x1 < country_block.x0 - 0.10:
                        continue
                    if block.y0 < country_block.y0 - 0.05 or block.y0 > country_block.y1 + 0.30:
                        continue
                elif block.y0 > 0.32:
                    continue
            if code_block and block.geometry_reliable and block.y0 < code_block.y0 - 0.04:
                continue
            # Postal-address lines ("Thành phố Sa Đéc, Tỉnh Đồng Tháp") also
            # match the "Place," shape but are addresses, never the province:
            # the issuance line always keeps its "ngày" keyword even when the
            # digits are unreadable.
            if _is_address_or_noise(block.text):
                continue
            if "ngay" not in block.folded:
                continue
            match = re.match(r"^\s*([A-ZÀ-ỸĐ][^,\n]{1,40})\s*,", block.text)
            if not match:
                continue
            candidate_place = match.group(1).strip()
            if any(token in _fold(candidate_place) for token in ("dia chi", "website", "fax", "dien thoai", "dt:")):
                continue
            if 1 <= len(candidate_place.split()) <= 6 and not _ORG_RE.search(candidate_place):
                province = candidate_place
                evidence["province"].append(_evidence(block, "place-prefix-date-unreadable", province))
                break
    return value, province


def _split_country_office(text: str) -> str:
    """Keep the part before the country header in a merged office block.

    Matched on folded text so OCR variants ("CỘNG HOÀ", "CỘNG HÒA") split the
    same way; the cut maps back by word position, preserving original spelling.
    When OCR damages the words after "CỘNG HÒA" ("CỘNG HÒA NGHĨA..." for
    "CỘNG HÒA XÃ HỘI..."), the strict four-word anchor misses, so a loose cut
    at "CỘNG HÒA" applies whenever the head still names an issuing authority.
    """
    folded_words = _fold(text).split()
    for index in range(len(folded_words) - 3):
        if folded_words[index : index + 4] == ["cong", "hoa", "xa", "hoi"]:
            original_words = text.split()
            return " ".join(original_words[: min(index, len(original_words))])
    for index in range(len(folded_words) - 1):
        if folded_words[index : index + 2] == ["cong", "hoa"]:
            original_words = text.split()
            head = " ".join(original_words[: min(index, len(original_words))])
            if head and _has_org_keyword(head):
                return head
    return text


def _clean_office_sender_text(text: str) -> str:
    # Layout may merge the issuing authority and the country header in one
    # block (e.g. "THỦ TƯỚNG CHÍNH PHỦ CỘNG HÒA XÃ HỘI..."); keep the part
    # before the country anchor.
    text = _split_country_office(text)
    # A corporate letterhead label ("Tên tổ chức phát hành: X") is metadata,
    # never part of the issuing authority itself.
    text = re.sub(
        r"^\s*T[eê]n\s+(?:c[oô]ng\s+ty|t[oổ]\s+ch[uứ]c(?:\s+ph[aá]t\s+h[aà]nh)?)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    # A single layout line can merge the authority with its postal address
    # ("CÔNG TY ... TN Số 1253, CMT8, ..."): cut the address tail.  A comma
    # after "Số <digits>" never occurs in a statutory code.
    text = re.split(r"\bS[oố]\s+\d+\s*,", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    # Strip any inline code anchor if merged in same block
    code_m = _CODE_RE.search(text)
    if code_m:
        text = text[: code_m.start()].strip()
    # Layout may merge the issuing authority with the first-recipient block.
    text = _FIRST_RECIPIENT_RE.split(text, maxsplit=1)[0].strip()
    # A subject line ("V/v: ...") riding in the same block is body content,
    # never part of the issuing authority.
    text = _VV_RE.split(text, maxsplit=1)[0].strip()
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
    cleaned = " ".join(" ".join(lines).split())
    # Certified-copy headers embed the authority between a "SAO Y" prefix and a
    # signing-time suffix; drop those wrappers while keeping the authority.
    cleaned = re.sub(
        r"^(?:sao\s+y[\s,.:;]*)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.split(
        r"[,;]?\s*thời\s+gian\s+k[ýy]\s*[:：]?.*$",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return cleaned


def _extract_office_sender(
    blocks: list[_Block],
    code_block: _Block | None,
    evidence: dict[str, list[dict[str, Any]]],
    *,
    country_block: _Block | None = None,
    closing_pages: list[list[_Block]] | None = None,
) -> tuple[str, _Block | None]:
    # QH-anchored flow: the office lives LEFT of the country header and its
    # vertical band is anchored on the country (not on the code — the code is
    # resolved AFTER the office, so a wrong code must never mask the office).
    # ``code_block`` is kept for backward compatibility and ignored.
    if country_block is None:
        country_block = _header_frame(blocks).country
    country = country_block
    if country is not None and country.geometry_reliable:
        max_y = max(0.25, country.y1 + 0.10)
    else:
        max_y = 0.25

    def _left_of_country(block: _Block) -> bool:
        if not block.geometry_reliable or country is None:
            return True
        return block.x1 <= country.x0 + 0.05

    candidates = []
    for block in blocks:
        if block.geometry_reliable and block.y1 > max_y:
            continue
        if block.geometry_reliable:
            if country is None:
                # Edge case (no country header): absolute left-column bound.
                if block.cx > 0.52:
                    continue
            elif not _left_of_country(block):
                continue
        # Top-strip digital-signature annotations (portal name, signer, time)
        # sit entirely above the statutory letterhead; their mangled OCR can
        # still contain an "org keyword" (e.g. "... điện tử Chính phủ").
        if block.geometry_reliable and block.y1 < 0.04:
            continue
        # Form-template headers ("Mẫu 08/CBTT-SGDHN...") describe the paper
        # form, never the issuing authority.
        if re.match(r"^\s*mau\s+\d+", block.folded):
            continue
        # Country text is stripped inside _clean_office_sender_text, so merged
        # "office + country" blocks still contribute their office part while
        # pure country blocks clean to "" and are dropped below.
        if _is_annotation_header(block.text, block.folded):
            continue
        # Arrival-stamp blocks ("SỞ GIAO DỊCH ... HÌNH ĐẾN", "VĂN BẢN ĐẾN
        # Ngày: ...") name another institution, never the issuing authority.
        if "van ban den" in block.folded or "cong van den" in block.folded:
            continue
        if any(token in block.folded for token in ("ky boi", "cong bao")):
            continue
        if _office_candidate_valid(block.text):
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
            return val, parts[-1][1]

    for closing in closing_pages or []:
        value, source = _extract_xac_thuc_office(closing, evidence)
        if value:
            return value, source

    # A corporate letterhead names its issuer through a labeled field ("Tên
    # công ty:", "Tên tổ chức phát hành:"): prefer it over a loose
    # centered-org guess (arrival stamps name other institutions, e.g. "SỞ
    # GIAO DỊCH ... (HNX)", and would otherwise win by reading order).
    # Explicit issuer labels can occur in the first page's body as well.
    for block in blocks:
        match = re.search(
            r"\bTên\s+(?:công\s+ty|tổ\s+chức)(?!\s+nhận\b)(?:\s+phát\s+hành)?\s*[:：]?\s+([^\n]+)",
            block.text,
            re.IGNORECASE,
        )
        if match:
            raw_val = match.group(1).strip()
            clean_val = " ".join(raw_val.split())
            if _office_candidate_valid(clean_val):
                evidence["officeSender"].append(_evidence(block, "company-name-anchor", clean_val))
                return clean_val, block

    # Corporate letterheads commonly center the issuing company rather than using statutory left column
    for block in blocks:
        if block.geometry_reliable and block.y1 > max_y and block.y0 < 0.85:
            continue
        if block.geometry_reliable and block.y1 < 0.04:
            continue
        if re.match(r"^\s*mau\s+\d+", block.folded):
            continue
        if _is_annotation_header(block.text, block.folded):
            continue
        if any(token in block.folded for token in ("ky boi", "dia chi", "cong bao", "van ban den", "cong van den")):
            continue
        if re.search(r"(?:^|\W)den(?:$|\W)", block.folded):
            continue
        if _office_candidate_valid(block.text) and not re.search(
            r"\b(?:ban hanh|quyet dinh|nhu sau|can cu|de nghi|chiu trach nhiem)\b", block.folded
        ):
            cleaned = _clean_office_sender_text(block.text)
            if cleaned:
                evidence["officeSender"].append(_evidence(block, "upper-left-organization", cleaned))
                return cleaned, block

    return "", None


def _office_candidate_valid(text: str) -> bool:
    text = _clean_office_sender_text(text)
    folded = _fold(text)
    if any(token in folded for token in (
        "kinh gui", "noi nhan", "ten cong ty nhan", "ten to chuc nhan",
        "van ban hop nhat", "van ban den", "cong van den",
    )) or re.search(r"\bdien\s*[:：]", folded):
        return False
    return bool(_clean_office_sender_text(text) and _has_org_keyword(text, folded))


def _extract_adoption_date(blocks, evidence, *, rule="closing-adoption-date"):
    """Only a closing assertion about this instrument, not a cited date."""
    for block in blocks:
        if not re.search(r"\b(?:luat|nghi quyet|van ban|quy che|quy dinh)\s+nay\b", block.folded):
            continue
        anchor = re.search(r"\bth[oô]ng\s+qua\s+ng[aà]y\b", block.text, re.IGNORECASE)
        if not anchor:
            continue
        tail = "ngày " + block.text[anchor.end():].lstrip()
        match = _LONG_DATE_RE.match(unicodedata.normalize("NFKC", tail))
        if match:
            value = _canonical_date(*match.groups())
            if value:
                evidence["documentDate"].append(_evidence(block, rule, value))
                return value
    return ""


# A citation opening another instrument ("Thông tư số 46/2024/... ngày ...")
# starts the consolidation preamble or a reference, never a title
# continuation.  Matched on folded text so OCR variants ("Thông tự") split
# the same way; a digit in the code token is required so prose merely
# mentioning an instrument ("thi hành nghị quyết của đại hội") flows on.
_DOCUMENT_CITATION_OPEN_RE = re.compile(
    r"^\s*(?:\d+\s*[.)]\s*)?"
    r"(luat|nghi dinh|nghi quyet|quyet dinh|thong tu|chi thi|cong dien)"
    r"\s+so\s*[:：.]?\s*\S*\d\S*"
)

# A stamp serial standing alone ("Số 14501", "Số: 10608") carries no title
# words; neither does a bare date keyword ("Ngày") or a letter-less fragment
# ("03311-2020", "28981").  All are stamp/layout noise, never title text.
_SERIAL_ONLY_FRAGMENT_RE = re.compile(r"^\s*S[oố]\s*[:：.]?\s*[\d\s./\-]+\s*$", re.IGNORECASE)
_BARE_DATE_KEYWORD_RE = re.compile(r"^\s*Ng[aà]y\s*[:：]?\s*$", re.IGNORECASE)


def _is_title_noise_fragment(text: str) -> bool:
    """True for stamp/layout fragments that can never continue a title."""
    stripped = text.strip()
    if not stripped or not re.search(r"[A-Za-zÀ-ỹĐđ]", stripped):
        return True
    if _SERIAL_ONLY_FRAGMENT_RE.match(stripped):
        return True
    return bool(_BARE_DATE_KEYWORD_RE.match(stripped))


def _starts_with_document_citation(folded: str) -> bool:
    return bool(_DOCUMENT_CITATION_OPEN_RE.match(folded))


def _first_content_heading(
    blocks: list[_Block],
    after_index: int,
    evidence: dict[str, list[dict[str, Any]]],
) -> str:
    """Title of a consolidated (VBHN) document from its instrument heading.

    Returns the tail (or continuation) of the first non-VBHN named heading
    below the VBHN label, e.g. "Quy định ..." after "NGHỊ ĐỊNH".
    """
    for block_index in range(after_index + 1, len(blocks)):
        block = blocks[block_index]
        if not _zone(block, y0=0.08, y1=0.60):
            continue
        matched = _match_document_type(block)
        if not matched:
            continue
        _, tail, _ = matched
        if re.fullmatch(r"s[oố]\s*[:.]?\s*[0-9A-Za-zÀ-ỹĐđ./\-\s]+", tail, re.IGNORECASE):
            tail = ""
        title = " ".join(tail.split())
        if title:
            evidence["title"].append(_evidence(block, "content-heading-title", title))
            return title
        following: list[str] = []
        for candidate in blocks[block_index + 1 : block_index + 5]:
            if _FIRST_RECIPIENT_RE.search(candidate.text):
                break
            if candidate.y0 - block.y1 > 0.14:
                break
            if _is_title_noise_fragment(candidate.text):
                continue
            if _starts_with_document_citation(candidate.folded):
                break
            # A numbered form/body item ("2. Nội dung ...", "3. ...") opens a
            # new section, never continues the title.
            if re.match(r"^\s*\d+\s*[.)]", candidate.text):
                break
            if re.fullmatch(r"\d+", candidate.text.strip()):
                continue
            if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                continue
            if "cong hoa xa hoi chu nghia viet nam" in candidate.folded:
                continue
            if re.match(r"^\s*S[oố]\s*[:：.]", candidate.text):
                continue
            if len(candidate.text) < 80 and _find_date(candidate.text):
                continue
            if candidate.folded.startswith("can cu"):
                break
            if candidate.type in {"doc_title", "paragraph_title", "text"} and _zone(
                candidate, x0=0.16, x1=0.88, y1=0.62
            ):
                following.append(candidate.text)
                evidence["title"].append(_evidence(candidate, "content-heading-continuation", candidate.text))
        if following:
            return " ".join(" ".join(following).split())
        return ""
    return ""


def _clean_type_tail(tail: str) -> str:
    """Strip arrival-stamp fragments from the same-line title tail.

    Layout merges the heading with stamp lines ("NGHỊ QUYẾT Ngày: 27 04-
    2017 ĐẠI HỘI... 2017 10247 Số:"): a colon-led "Ngày:" stamp prefix, a
    serial glued to a trailing "Số:" stub, and a letter-less "Số:" stub are
    stamp noise, never title text.  The colon requirement keeps legitimate
    prose dates ("... ngày 30/4 ...") intact.
    """
    cleaned = re.sub(r"\bNg[aà]y\s*[:：]\s*[\d\s/\-.]+", " ", tail, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s+S[oố]\s*[:：]?\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bS[oố]\s*[:：]?\s*[^A-Za-zÀ-ỹĐđ]*$", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _extract_type_title(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    consolidated = any(
        "van ban hop nhat" in b.folded or re.search(r"\bvbhn\s*-", b.folded)
        for b in blocks if _zone(b, y1=0.35)
    )
    # A named heading in the header zone is the authoritative document type,
    # even when a "V/v" subject line appears earlier on the page (corporate
    # letterheads put the subject above the heading).  ``V/v`` only identifies
    # a Công văn when no named heading exists.
    # Exception: when the subject rides inside the code line itself
    # ("Số: 270/HĐ V/v: ..."), the document is a Công văn whose body may quote
    # a named instrument ("Nghị quyết Đại hội..."); a later line-start type
    # word is then quoted content, not the heading.
    subject_in_code_line = any(
        _CODE_RE.search(block.text) and _VV_RE.search(block.text) for block in blocks if _zone(block, y0=0.08, y1=0.52)
    )
    if not subject_in_code_line:
        for block_index, block in enumerate(blocks):
            if not _zone(block, y0=0.08, y1=0.52):
                continue
            matched = _match_document_type(block)
            if not matched:
                continue
            document_type, tail, line_index = matched
            if consolidated and _starts_with_document_citation(_fold(block.text.splitlines()[line_index])):
                continue
            # A "type word" starting a wrapped line of a V/v subject sentence
            # (e.g. "V/v: ... thông tin\nNghị quyết Đại hội...") is a subject
            # continuation, not the document heading: the heading never shares
            # its block with an earlier V/v anchor.
            if _VV_RE.search("\n".join(block.text.splitlines()[:line_index])):
                continue
            if re.fullmatch(r"s[oố]\s*[:.]?\s*[0-9A-Za-zÀ-ỹĐđ./\-\s]+", tail, re.IGNORECASE):
                # "Nghị quyết số: ..." is a number line, not the title's
                # heading. Prefer the same instrument's actual named heading
                # below it, otherwise its whole "NGHỊ QUYẾT\n<title>" block
                # would incorrectly become a title continuation.
                actual_heading_below = False
                for candidate in blocks[block_index + 1:]:
                    if candidate.folded.startswith("can cu"):
                        break
                    if not _zone(candidate, y0=0.08, y1=0.52):
                        continue
                    candidate_match = _match_document_type(candidate)
                    if candidate_match and candidate_match[0] == document_type:
                        candidate_tail = candidate_match[1]
                        if not re.fullmatch(r"s[oố]\s*[:.]?\s*[0-9A-Za-zÀ-ỹĐđ./\-\s]+", candidate_tail, re.IGNORECASE):
                            actual_heading_below = True
                            break
                if actual_heading_below:
                    continue
                tail = ""
            title = _clean_type_tail(tail)
            title_evidence: list[tuple[_Block, str, str]] = []
            if title:
                title = " ".join(title.split())
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
                    if _is_title_noise_fragment(candidate.text):
                        continue
                    if _starts_with_document_citation(candidate.folded):
                        break
                    # A numbered form/body item ("2. Nội dung ...", "3. ...")
                    # opens a new section, never continues the title.
                    if re.match(r"^\s*\d+\s*[.)]", candidate.text):
                        break
                    if re.fullmatch(r"\d+", candidate.text.strip()):
                        continue
                    if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                        continue
                    # The country header, the code line and the place/date line
                    # sit between the heading and the body; none of them is a
                    # title continuation.
                    if "cong hoa xa hoi chu nghia viet nam" in candidate.folded:
                        continue
                    if re.match(r"^\s*S[oố]\s*[:：.]", candidate.text):
                        continue
                    # A date-led line ("Ngày: 27 04- 2017 ...") is stamp/header
                    # metadata, never a title continuation — even when OCR
                    # damage makes the date itself unparseable.
                    if re.match(r"^\s*Ng[aà]y\s*[:：]", candidate.text, re.IGNORECASE):
                        continue
                    # Short date lines ("Hà Nội, ngày ...") are metadata, never
                    # title text; long sentences merely mentioning a date keep
                    # flowing into the title.
                    if len(candidate.text) < 80 and _find_date(candidate.text):
                        continue
                    # Citation lines ("Căn cứ Luật...") follow the heading in
                    # statutory documents and mark the start of the body;
                    # they are never the title, and neither is anything below.
                    if candidate.folded.startswith("can cu"):
                        break
                    if candidate.type in {"doc_title", "paragraph_title", "text"} and _zone(
                        candidate, x0=0.16, x1=0.88, y1=0.58
                    ):
                        following.append(candidate.text)
                        title_evidence.append((candidate, "title-continuation", candidate.text))
                title = "\n".join(following).strip()
            # API output joins a wrapped title with a single space (contract
            # 3.1), whichever path produced it; raw breaks stay in evidence.
            title = " ".join(title.split())
            evidence["type"].append(_evidence(block, "named-document-type", document_type))
            for title_block, rule, matched_value in title_evidence:
                evidence["title"].append(_evidence(title_block, rule, matched_value))
            return document_type, title

    for block in blocks:
        if not _zone(block, y0=0.08, y1=0.52):
            continue
        match = _VV_RE.search(block.text)
        if match:
            title = block.text[match.start() :].strip()
            evidence["type"].append(_evidence(block, "v-v-structure", "Công văn"))
            evidence["title"].append(_evidence(block, "v-v-title-preserved", title))
            return "Công văn", title
    return "", ""


def _extract_disclosure_content_title(
    blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]
) -> str:
    """Subject of a CÔNG BỐ THÔNG TIN BẤT THƯỜNG form from its content item.

    The heading names the form, not the subject; the actual subject sits in
    the numbered "Nội dung thông tin công bố:" item below (same pattern as
    the CÔNG ĐIỆN dispatch handler: a form-level anchor, never a filename).
    """
    for block_index, block in enumerate(blocks):
        if "noi dung" not in block.folded or "cong bo" not in block.folded:
            continue
        if ":" not in block.text or len(block.text) > 160:
            continue
        match = re.search(r":\s*(.*)$", block.text)
        tail = match.group(1).strip() if match else ""
        parts = [tail] if tail else []
        evidence["title"].append(_evidence(block, "disclosure-content-anchor", block.text.strip()))
        for candidate in blocks[block_index + 1 : block_index + 4]:
            text = candidate.text.strip()
            if not text:
                continue
            if re.match(r"^\s*\d+\s*[.)]", text) or candidate.folded.startswith("can cu"):
                break
            if _FIRST_RECIPIENT_RE.search(text) or _RECIPIENT_RE.search(text):
                break
            if len(text) > 400:
                break
            parts.append(text)
            evidence["title"].append(_evidence(candidate, "disclosure-content-continuation", text))
        value = " ".join(" ".join(parts).split())
        if value:
            return value
    return ""


def _clean_recipient_value(value: str) -> str:
    # Recipients keep the OCR wording.  A line break after "," continues the
    # same value (joined with a space, swallowing a wrap bullet); a bare
    # line end (no "," or ";" behind it) starts a new item ("; ").  Explicit
    # source markers (";", bullets, "/") always survive as separators.
    value = _SAVE_RE.split(value, maxsplit=1)[0]
    value = _SAVE_SUFFIX_RE.sub("", value)
    # A break after "," continues the same value (comma kept); a bare break
    # with no "," or ";" behind it opens a new item.  A bullet on the next
    # line always opens a new item, even after a comma.
    value = re.sub(r",[ \t]*\n[ \t]*", ", ", value)
    value = re.sub(r";[ \t]*\n[ \t]*", "; ", value)
    value = value.replace("\n", "; ")
    # OCR turns quotation marks into "?": never a meaningful character.
    value = re.sub(r"[?\"'“”‘’«»`]", "", value)
    # OCR joins wrapped values with "/": an explicit source marker, kept as a
    # separator like bullets and ";" (only soft line wraps join with space).
    value = re.sub(r"\s+/\s+", "; ", value)
    # An arrival-stamp serial riding inside the value ("số 1.772 - ...")
    # names no addressee: drop digit-only serials, keep genuine references
    # ("Số: 123/BQP" survives via its lettered token).
    value = re.sub(
        r"\s*\bS[oố]\s*[:：.]?\s*\d[\d\s./\-]*(?=\s*(?:[;]|$|\s+[-–—•]\s))",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = _BULLET_RE.sub("; ", value)
    parts = []
    for segment in value.split(";"):
        text = " ".join(segment.split())
        if not text:
            continue
        if _SERIAL_ONLY_SEGMENT_RE.match(text) and not any(
            sum(ch.isalpha() for ch in word) >= 3 for word in text.split()
        ):
            continue
        parts.append(text)
    value = "; ".join(parts)
    value = re.sub(r"\s*;\s*", "; ", value)
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
        if field_name == "first_recipients" and any(
            anchor in block.folded for anchor in ("van ban den", "cong van den")
        ):
            # A "Kính ..." fragment inside an arrival-stamp paragraph is stamp
            # noise — UNLESS the anchor is immediately followed by a real
            # addressee on the same block (the stamp overlaps the Kính gửi
            # line instead of replacing it).
            remainder = block.text[match.end() :].strip()
            if not remainder or re.match(r"^(ngay|so)\s*[:：]", remainder, re.IGNORECASE):
                continue
        value = block.text[match.end() :]
        if field_name == "first_recipients":
            value = re.sub(
                r"\bNg[aà]y\s*[:：]\s*\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{4}",
                " ",
                value,
                flags=re.IGNORECASE,
            )
            # A trailing arrival-stamp stub ("Số:................ A03/",
            # "Số: 10608") is stamp noise, never an addressee: cut at "Số:"
            # when no real word (3+ letters) follows it.  A genuine reference
            # ("... Số: 123/BQP") keeps its code and survives.
            stub = re.search(r"\bS[oố]\s*[:：]", value, flags=re.IGNORECASE)
            if stub and not any(
                sum(ch.isalpha() for ch in word) >= 3 for word in value[stub.end() :].split()
            ):
                value = value[: stub.start()]
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
                # The first item need not be bulleted: form lists often carry
                # no markers at all.  Still require a short block so body
                # paragraphs are never absorbed through an empty label.
                if not parts and not re.match(r"^\s*[-–—•]", candidate.text) and len(candidate.text) > 120:
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
        anchor_had_value = bool(value.strip())
        if field_name == "first_recipients" and not anchor_had_value:
            # The label can sit alone on its line ("Kính gửi:"), the addressees
            # riding in the blocks below (form lists, dispatches).  Follow the
            # same column downward with the same stop rules as the inline
            # continuation; fragments join with a space via the shared cleaner.
            anchor_block = block
            collected: list[str] = []
            last_x0: float | None = None
            last_y1 = anchor_block.y1
            for candidate in blocks[block_index + 1 : block_index + 6]:
                if candidate.geometry_reliable and candidate.y0 > anchor_block.y1 + 0.10:
                    break
                if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                    continue
                if not candidate.text.strip() or len(candidate.text) > 160:
                    break
                if re.search(
                    r"\b(?:tru so|ten cong ty|ten to chuc|dia chi|noi dung|can cu|thuc hien|thong bao|dieu\s+\d+)\b",
                    candidate.folded,
                ):
                    break
                # Stamp serial fragments ("Số: 10608") are not organizations,
                # even though folded "số" collides with the "sở" keyword.
                if re.match(r"^\s*S[oố]\s*[:：]", candidate.text, re.IGNORECASE):
                    break
                if _RECIPIENT_RE.search(candidate.text) or _FIRST_RECIPIENT_RE.search(candidate.text):
                    break
                if _has_org_keyword(candidate.text, candidate.folded) or re.match(
                    r"^\s*[-–—•]", candidate.text
                ):
                    collected.append(candidate.text)
                    evidence[field_name].append(_evidence(candidate, f"{rule}-continuation", candidate.text))
                    last_x0 = candidate.x0 if candidate.geometry_reliable else last_x0
                    last_y1 = candidate.y1
                    continue
                # A wrapped item line keeps its column: same left edge as the
                # anchor or the previous item, adjacent, short, no stop
                # keywords.  Body text restarts at the page margin instead.
                if (
                    candidate.geometry_reliable
                    and last_x0 is not None
                    and abs(candidate.x0 - last_x0) <= 0.03
                    and candidate.y0 <= last_y1 + 0.06
                    and " ".join(candidate.text.split())
                ):
                    collected.append(candidate.text)
                    evidence[field_name].append(_evidence(candidate, f"{rule}-continuation", candidate.text))
                    last_y1 = candidate.y1
                    continue
                break
            if collected:
                value = _clean_recipient_value("\n".join(collected))
        if field_name == "first_recipients" and anchor_had_value and value and ";" not in value:
            for candidate in blocks[block_index + 1 : block_index + 5]:
                if candidate.geometry_reliable and candidate.y0 > block.y1 + 0.06:
                    break
                if any(anchor in candidate.folded for anchor in ("van ban den", "cong van den")):
                    continue
                if len(candidate.text) > 160 or re.search(
                    r"\b(?:tru so|ten cong ty|ten to chuc|dia chi|noi dung|" r"can cu|thuc hien|thong bao|dieu\s+\d+)\b",
                    candidate.folded,
                ):
                    break
                # Stamp serial fragments ("Số: 10608") are not organizations,
                # even though folded "số" collides with the "sở" keyword.
                if re.match(r"^\s*S[oố]\s*[:：]", candidate.text, re.IGNORECASE):
                    break
                if _has_org_keyword(candidate.text, candidate.folded):
                    continuation = _clean_recipient_value(candidate.text)
                    if continuation:
                        value = _clean_recipient_value(f"{value}\n{continuation}")
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
        elif "hoa toc" in folded or re.search(r"(?:^|\W)(?:oa|ha)\s+toc\b", folded):
            # OCR routinely drops or corrupts the leading H of the urgency
            # stamp ("OA TỐC" for "HỎA TỐC"); the stamp zone plus the intact
            # "TỐC" syllable keep this precise.
            priority = "1_HỎA TỐC"
        elif re.search(r"(?:^|\W)khan(?:$|\W)", folded):
            priority = "2_KHẨN"
        if security != "0_BÌNH THƯỜNG":
            evidence["security_level"].append(_evidence(block, "security-stamp", security))
        if priority != "0_BÌNH THƯỜNG":
            evidence["priority_level"].append(_evidence(block, "priority-stamp", priority))
    return priority, security


def _extract_receiver_date(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> str:
    """Arrival-stamp date (``receiverDate``) is out of scope this round.

    The API key is still returned (always ``""``) for schema stability, but no
    stamp block is read and nothing is scored.  See
    ``docs/ocr_pipeline_benchmark_metrics.md``.
    """
    return ""




# A trailing stamp serial glued to a signature title ("THỨ TRƯỞNG AY 4"):
# signature titles never end with a serial/token code, while authority
# acronyms without digits ("HĐQT") are untouched.
_SIGNATURE_TITLE_SERIAL_SUFFIX_RE = re.compile(r"\s+[A-ZÀ-ỸĐ]{1,3}\s+\d[\d\s./\-]*$")


def _strip_signature_serial(title: str) -> str:
    """Drop a trailing stamp serial glued to a signature title."""
    return _SIGNATURE_TITLE_SERIAL_SUFFIX_RE.sub("", title).strip()


def _nearby_standalone(block: _Block, standalone: list[_Block]) -> bool:
    """True when a standalone printed name sits in the same signature zone."""
    for other in standalone:
        if other is block:
            continue
        if not other.geometry_reliable or not block.geometry_reliable:
            return True
        if abs(other.cx - block.cx) <= 0.30 and other.y0 >= block.y0 - 0.02 and other.y0 <= block.y1 + 0.25:
            return True
    return False


def _extract_signature(blocks: list[_Block], evidence: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    # Contract 3.1: one signature cluster per signer/position.  Lines of the
    # same cluster join with a space; only distinct clusters split with "; ".
    # Adjacent authority-only blocks ("KT. BỘ TRƯỞNG" / "THỨ TRƯỞNG") are one
    # cluster, not two: the old flat "; "-join over-split them.
    candidates = sorted(_signature_candidates(blocks), key=lambda item: (item[0].y0, item[0].x0))
    standalone = []
    for block in blocks:
        text = " ".join(block.text.split()).strip()
        if text and len(text) <= 80 and _looks_like_signature_name(text) and not _is_seal_name_fragment(text):
            standalone.append(block)
    standalone_texts = {" ".join(block.text.split()).strip() for block in standalone}

    restored: list[tuple[_Block, str, str]] = []
    for block, title, signer in candidates:
        clean_title = " ".join(title.split()).strip() if title else ""
        if signer and clean_title:
            # An all-caps org fragment split off a title line ("KT. CỤC
            # TRƯỞNG CỤC | QUẢN LÝ VÀ PHÁT TRIỂN") is not the signer when a
            # standalone printed name sits in the same signature zone: the
            # full line is title, the fragment is dropped.  Verified names
            # (matching a standalone block) never trigger this.  Runs before
            # the follower search so the restored title can still absorb a
            # wrapped line below.
            lines = [line for line in block.text.splitlines() if line.strip()]
            full = " ".join(block.text.split()).strip()
            if (
                len(lines) == 1
                and full != signer
                and signer not in standalone_texts
                and signer
                and not any(ch.islower() for ch in signer)
                and _has_authority_anchor(clean_title)
                and _has_org_keyword(clean_title, _fold(clean_title))
                and _nearby_standalone(block, standalone)
            ):
                signer = ""
                clean_title = full
        if clean_title and not signer:
            # Authority wrapped onto a second block ("TM. ĐOÀN CHỦ TỊCH" /
            # "CHỦ TỌA"): the following, column-aligned short block continues
            # the SAME title with a space (contract 3.1), unless it is a
            # person name, another anchor, or list content.  Recipient bullets
            # interleaved between the two lines are stepped over.  A wrapped
            # line without title vocabulary still joins when it is plain
            # prose ("THỊ TRƯỜNG TRONG NƯỚC"): stamp serials carry digits and
            # stay out.
            follower = None
            try:
                position = blocks.index(block) + 1
            except ValueError:
                position = None
            if position is not None:
                for candidate_block in blocks[position : position + 4]:
                    candidate_text = " ".join(candidate_block.text.split()).strip()
                    if re.match(r"^\s*[-–—•]", candidate_text) or re.match(r"^\s*l[uư]u\b", candidate_block.folded):
                        continue
                    follower = candidate_block
                    break
            if follower is not None and follower is not block:
                follower_text = " ".join(follower.text.split()).strip()
                follower_words = set(follower.folded.split())
                if (
                    follower_text
                    and len(follower_text) <= 60
                    and (
                        (follower_words & _TITLE_WORDS_FOLDED)
                        or (
                            bool(re.search(r"[A-Za-zÀ-ỹĐđ]", follower_text))
                            and not re.search(r"\d", follower_text)
                            and len(follower_text.split()) >= 2
                        )
                    )
                    and not _has_authority_anchor(follower_text)
                    and not _has_org_keyword(follower_text, follower.folded)
                    and not _looks_like_signature_name(follower_text)
                    and not _RECIPIENT_RE.search(follower_text)
                    and not re.match(r"^\s*[-–—•]", follower_text)
                    and not re.match(r"^\s*(?:luu|dieu\s+\d+)\b", follower.folded)
                    and (
                        not follower.geometry_reliable
                        or (follower.y0 <= block.y1 + 0.06 and abs(follower.cx - block.cx) <= 0.24)
                    )
                ):
                    clean_title = f"{clean_title} {follower_text}"
                    evidence["signer_title"].append(
                        _evidence(follower, "signature-authority-continuation", clean_title)
                    )
        if clean_title or signer:
            restored.append((block, clean_title, signer))

    # Cluster assembly: one cluster per distinct signer; title-only blocks
    # attach to the nearest cluster, otherwise merge adjacently with a space.
    clusters: list[dict[str, Any]] = []
    by_signer: dict[str, dict[str, Any]] = {}
    open_plain: dict[str, Any] | None = None

    def _attachable(cluster: dict[str, Any], block: _Block) -> tuple[float, float] | None:
        best: tuple[float, float] | None = None
        refs = list(cluster["titles"])
        if cluster.get("signer_block") is not None:
            refs.append((cluster["signer_block"], ""))
        for ref, _ in refs:
            if ref.geometry_reliable and block.geometry_reliable:
                if abs(ref.cx - block.cx) > 0.24:
                    continue
                if block.y1 <= ref.y0:
                    gap = ref.y0 - block.y1
                elif block.y0 >= ref.y1:
                    gap = block.y0 - ref.y1
                else:
                    gap = 0.0
                if gap < -0.02 or gap > 0.10:
                    continue
                key = (gap, abs(ref.cx - block.cx))
                if best is None or key < best:
                    best = key
            elif best is None:
                best = (0.0, 0.0)
        return best

    for block, title, signer in restored:
        if not signer:
            continue
        cluster = by_signer.get(signer)
        if cluster is None:
            cluster = {"signer": signer, "titles": [], "signer_block": block}
            by_signer[signer] = cluster
            clusters.append(cluster)
        if title:
            cluster["titles"].append((block, title))
    for block, title, signer in restored:
        if signer or not title:
            continue
        # Title-only: prefer the nearest signer cluster in the same column.
        target: dict[str, Any] | None = None
        target_key: tuple[float, float] | None = None
        for cluster in clusters:
            key = _attachable(cluster, block)
            if key is not None and (target_key is None or key < target_key):
                target, target_key = cluster, key
        if target is not None:
            target["titles"].append((block, title))
            open_plain = None
            continue
        if (
            open_plain is not None
            and block.geometry_reliable
            and open_plain["ref"].geometry_reliable
            and abs(open_plain["ref"].cx - block.cx) <= 0.24
            and -0.02 <= block.y0 - open_plain["ref"].y1 <= 0.06
        ):
            open_plain["cluster"]["titles"].append((block, title))
            open_plain["ref"] = block
            continue
        cluster = {"signer": "", "titles": [(block, title)], "signer_block": None}
        clusters.append(cluster)
        open_plain = {"cluster": cluster, "ref": block} if block.geometry_reliable else None

    titles: list[str] = []
    signers: list[str] = []
    # Reading order across clusters: a title-only cluster above a signer
    # cluster keeps its position (no more "B; A" swaps from build order).
    def _cluster_key(cluster: dict[str, Any]) -> tuple[float, float]:
        ys = [ref.y0 for ref, _ in cluster["titles"]]
        xs = [ref.x0 for ref, _ in cluster["titles"]]
        if cluster.get("signer_block") is not None:
            ys.append(cluster["signer_block"].y0)
            xs.append(cluster["signer_block"].x0)
        return (min(ys), min(xs)) if ys else (0.0, 0.0)

    for cluster in sorted(clusters, key=_cluster_key):
        parts = sorted(cluster["titles"], key=lambda item: (item[0].y0, item[0].x0))
        anchored = [(ref, text) for ref, text in parts if _has_authority_anchor(text)]
        # A title fragment without any authority anchor inside a multi-part
        # cluster is stamp/org noise from a merged image block ("TỔNG CÔNG
        # ... TÁI BẢO H PT" next to the real "TỔNG GIÁM ĐỐC"), never title.
        kept = anchored if anchored else parts
        merged: list[str] = []
        for _, text in kept:
            folded = _fold(text)
            if any(folded == _fold(done) or folded in _fold(done) for done in merged):
                continue
            merged = [done for done in merged if _fold(done) not in folded] + [text]
        cluster_title = " ".join(merged)
        if cluster_title:
            titles.append(cluster_title)
            for _, text in kept:
                if text in merged:
                    evidence["signer_title"].append(_evidence(_ref_of(cluster, text), "signature-authority", cluster_title))
        if cluster["signer"] and cluster["signer"] not in signers:
            signers.append(cluster["signer"])
            evidence["signer"].append(_evidence(cluster["signer_block"], "signature-name", cluster["signer"]))
        if cluster_title and not cluster["signer"]:
            anchor_block = parts[-1][0]
            for name_block in blocks:
                if name_block.type == "seal" or name_block.y0 < anchor_block.y0:
                    continue
                if name_block.geometry_reliable:
                    if name_block.y0 > anchor_block.y1 + 0.22 or abs(name_block.cx - anchor_block.cx) > 0.24:
                        continue
                if (
                    _looks_like_signature_name(name_block.text)
                    and not _is_seal_name_fragment(name_block.text.strip())
                    and name_block.text not in signers
                ):
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
                if (
                    _looks_like_signature_name(candidate_line)
                    and not _is_seal_name_fragment(candidate_line)
                    and candidate_line not in signers
                ):
                    signers.append(candidate_line)
                    evidence["signer"].append(_evidence(block, "fallback-signature-zone-name", candidate_line))
                    break
            if signers:
                break
    return "; ".join(titles), "; ".join(signers)


def _ref_of(cluster: dict[str, Any], text: str) -> _Block:
    for ref, part in cluster["titles"]:
        if part == text:
            return ref
    return cluster["titles"][0][0]


def _extract_cong_dien_recipients(
    blocks: list[_Block],
    evidence: dict[str, list[dict[str, Any]]],
) -> str:
    """Addressees of a CÔNG ĐIỆN: the distribution list after "[...] ĐIỆN:".

    Điện dispatches carry no "Kính gửi"; the addressee list follows the
    dispatch line ("THỦ TƯỚNG CHÍNH PHỦ ĐIỆN:") as bullet/continuation blocks.
    """
    for block_index, block in enumerate(blocks):
        if block.geometry_reliable and block.y0 > 0.55:
            continue
        dispatch = re.search(r"ĐIỆN\s*:\s*(.*)$", block.text, re.IGNORECASE)
        if not dispatch:
            continue
        parts = [dispatch.group(1).strip()] if dispatch.group(1).strip() else []
        anchor_block = block
        for candidate in blocks[block_index + 1 : block_index + 8]:
            if candidate.geometry_reliable and candidate.y0 > anchor_block.y1 + 0.20:
                break
            text = " ".join(candidate.text.split()).strip()
            if not text or len(text) > 220:
                break
            if _RECIPIENT_RE.search(text) or _FIRST_RECIPIENT_RE.search(text):
                break
            if re.search(r"\b(?:can cu|dieu\s+\d+|thuc hien)\b", candidate.folded):
                break
            parts.append(text)
            evidence["first_recipients"].append(_evidence(candidate, "dien-dispatch-continuation", text))
        value = _clean_recipient_value("\n".join(part for part in parts if part))
        if value:
            evidence["first_recipients"].append(_evidence(block, "dien-dispatch-anchor", value))
            return value
    return ""


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
    # QH-anchored header flow (contract 3.3): resolve the frame once, then
    # office LEFT of country -> province+date RIGHT/UNDER country ->
    # code BELOW office and LEFT of the date.  A wrong code must never mask
    # the office, so the office no longer depends on the code.
    frame = _header_frame(header_blocks)
    ending_pages = [pages[end]]
    for page in pages[end + 1:search_limit + 1]:
        if any(_RECIPIENT_RE.search(b.text) or "xac thuc van ban hop nhat" in b.folded for b in page):
            ending_pages.append(page)
        else:
            break
    office_sender, office_block = _extract_office_sender(
        header_blocks, None, evidence, country_block=frame.country,
        closing_pages=ending_pages,
    )
    # A fallback issuer on another page/footer must not move the header frame.
    code_office = office_block if office_block in header_blocks and office_block.y1 < 0.35 else frame.office
    document_date, province = _extract_date_province(header_blocks, None, evidence, country_block=frame.country)
    date_hint = None
    # Re-resolve the issuance block as a code anchor when present.
    if evidence["documentDate"]:
        date_page = evidence["documentDate"][0]["page"]
        date_bid = evidence["documentDate"][0]["block"]
        for block in header_blocks:
            if block.page + 1 == date_page and block.index + 1 == date_bid:
                date_hint = block
                break
    code, code_block = _extract_code(
        header_blocks,
        evidence,
        office_block=code_office,
        date_block_hint=date_hint,
        country_block=frame.country,
    )
    document_type, title = _extract_type_title(header_blocks, evidence)
    if not document_date:
        for ending in ending_pages:
            document_date = _extract_adoption_date(ending, evidence)
            if document_date:
                break
    if not document_date:
        # Keep this side channel separate from ordinary content: skipped
        # footnotes must not influence document boundaries or other fields.
        adoption_pages = _make_blocks(
            pages_blocks, original_page_sizes, processed_page_sizes, crop_offsets,
            geometry_reliable, skipped_adoption_only=True,
        )
        for page_index in range(end, end + len(ending_pages)):
            document_date = _extract_adoption_date(
                adoption_pages[page_index], evidence,
                rule="closing-adoption-date-skipped-footnote",
            )
            if document_date:
                break
    if not title and _fold(document_type) == "cong bo thong tin bat thuong":
        title = _extract_disclosure_content_title(header_blocks, evidence)
    first_recipients = _extract_anchor_value(
        header_blocks, _FIRST_RECIPIENT_RE, "first_recipients", "kinh-gui-anchor", evidence
    )
    if not first_recipients and _fold(document_type) == "cong dien":
        first_recipients = _extract_cong_dien_recipients(header_blocks, evidence)
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
