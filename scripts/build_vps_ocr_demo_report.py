"""Generate VPS OCR demo report presentation with updated benchmarks, metrics, time/resource reports, and priority flow.
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import os
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.util import Inches, Pt
from pptx.oxml.ns import qn


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = PROJECT_ROOT / "data" / "reports" / "demo_slide_draft" / "assets"
TEMPLATE_PATH = PROJECT_ROOT / "data" / "reports" / "demo_slide_draft" / "vts_ocr_demo_antigravity.pptx"

OUTPUT_WSL = Path("/mnt/d/Disk/Computer/Downloads/VPS OCR demo report_updated.pptx")
OUTPUT_TARGET = Path("/mnt/d/Disk/Computer/Downloads/VPS OCR demo report.pptx")
OUTPUT_UPDATED_NAME = Path("/mnt/d/Disk/Computer/Downloads/VPS OCR demo report (Updated).pptx")
OUTPUT_FINAL_NAME = Path("/mnt/d/Disk/Computer/Downloads/VPS OCR demo report_final.pptx")
OUTPUT_REPO = PROJECT_ROOT / "data" / "reports" / "demo_slide_draft" / "VPS OCR demo report_updated.pptx"

# Color Palette (Viettel Solutions standard)
RED = RGBColor(0xEE, 0x00, 0x33)
NAVY = RGBColor(0x17, 0x22, 0x35)
INK = RGBColor(0x22, 0x28, 0x2E)
GRAY = RGBColor(0x60, 0x66, 0x6D)
LIGHT_GRAY = RGBColor(0x8C, 0x93, 0x9D)
LIGHT = RGBColor(0xF5, 0xF7, 0xFA)
LIGHT_RED = RGBColor(0xFD, 0xF2, 0xF3)
LIGHT_GREEN = RGBColor(0xED, 0xF8, 0xF1)
MUTED_ROW = RGBColor(0xEE, 0xF1, 0xF5)
BORDER = RGBColor(0xE0, 0xE5, 0xEB)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x1A, 0x7F, 0x50)

TITLE_FONT = "Arial"
BODY_FONT = "Arial"


def clone_shape(source, target, shape):
    """Copy a decorative shape, including image-fill relationships."""
    element = deepcopy(shape.element)
    for blip in element.xpath(".//a:blip"):
        old_id = blip.get(qn("r:embed"))
        if old_id:
            try:
                image_part = source.part.related_part(old_id)
                blip.set(qn("r:embed"), target.part.relate_to(image_part, RT.IMAGE))
            except Exception:
                pass
    target.shapes._spTree.insert_element_before(element, "p:extLst")


def base_slide(prs, source, indices):
    slide = prs.slides.add_slide(source.slide_layout)
    for idx in indices:
        if idx < len(source.shapes):
            clone_shape(source, slide, source.shapes[idx])
    return slide


def textbox(slide, x, y, w, h, text, *, size=18, color=INK, bold=False,
            font=BODY_FONT, align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP,
            margin=0.03, spacing=1.15):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = valign
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    for i, line in enumerate(text.split("\n")):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.text = line
        para.alignment = align
        para.space_after = Pt(size * 0.15)
        para.line_spacing = spacing
        for run in para.runs:
            run.font.name = font
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = color
    return shape


def panel(slide, x, y, w, h, *, fill=LIGHT, edge=BORDER, radius=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = edge
    shape.line.width = Pt(0.75)
    return shape


def card(slide, x, y, w, h, title, body, *, tint=LIGHT, emphasis=None,
         title_size=18, body_size=15.5, emphasis_color=RED):
    panel(slide, x, y, w, h, fill=tint)
    if emphasis:
        textbox(slide, x + 0.22, y + 0.16, w - 0.44, 0.55, emphasis,
                size=28, color=emphasis_color, bold=True, font=TITLE_FONT)
        start = y + 0.82
    else:
        start = y + 0.22
    textbox(slide, x + 0.22, start, w - 0.44, 0.6, title,
            size=title_size, bold=True, font=TITLE_FONT, color=NAVY)
    textbox(slide, x + 0.22, start + 0.6, w - 0.44,
            max(0.3, h - (start - y) - 0.75), body, size=body_size, color=INK)


def badge(slide, x, y, w, text, *, fill=LIGHT_RED, color=RED):
    panel(slide, x, y, w, 0.38, fill=fill, edge=fill)
    textbox(slide, x + 0.05, y + 0.02, w - 0.1, 0.32, text,
            size=10.5, color=color, bold=True, align=PP_ALIGN.CENTER)


def banner(slide, y, text, *, size=19.5, bg=LIGHT_RED, edge=BORDER, color=NAVY):
    panel(slide, 1.36, y, 17.4, 0.82, fill=bg, edge=edge)
    textbox(slide, 1.6, y + 0.12, 16.9, 0.58, text,
            size=size, color=color, bold=True)


def quote(slide, x, y, w, label, value, *, good=False, h=0.95, size=16):
    fill = LIGHT_GREEN if good else LIGHT_RED
    panel(slide, x, y, w, h, fill=fill, edge=fill)
    textbox(slide, x + 0.17, y + 0.08, w - 0.34, 0.22, label.upper(),
            size=10, color=GREEN if good else RED, bold=True)
    textbox(slide, x + 0.17, y + 0.32, w - 0.34, h - 0.38, value,
            size=size, bold=True, color=INK)


def photo(slide, filename, x, y, w, h, *, caption="", bg=WHITE):
    panel(slide, x, y, w, h, fill=bg, radius=False)
    path = ASSET_DIR / filename
    if path.exists():
        with Image.open(path) as im:
            iw, ih = im.size
            data = BytesIO()
            is_page = filename.startswith(("demo-", "stamp-", "sign-", "missing-"))
            if is_page:
                im.convert("RGB").save(data, "JPEG", quality=92)
            else:
                im.save(data, "PNG")
            data.seek(0)
        image_h = h - (0.45 if caption else 0.1)
        scale = min((w - 0.15) / iw, (image_h - 0.12) / ih)
        pw, ph = iw * scale, ih * scale
        slide.shapes.add_picture(data, Inches(x + (w - pw) / 2),
                                 Inches(y + (image_h - ph) / 2),
                                 width=Inches(pw), height=Inches(ph))
    if caption:
        textbox(slide, x + 0.15, y + h - 0.4, w - 0.3, 0.35,
                caption, size=10, color=GRAY)


def table_slide(slide, x, y, w, h, headers, rows_data, col_widths=None,
                font_size=11, header_bg=NAVY, highlight_rules=None):
    table_shape = slide.shapes.add_table(len(rows_data) + 1, len(headers),
                                         Inches(x), Inches(y), Inches(w), Inches(h))
    tbl = table_shape.table
    if col_widths:
        for idx, cw in enumerate(col_widths):
            tbl.columns[idx].width = Inches(cw)

    for col_idx, h_text in enumerate(headers):
        cell = tbl.cell(0, col_idx)
        cell.fill.solid()
        cell.fill.fore_color.rgb = header_bg
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = cell.margin_right = Inches(0.09)
        cell.margin_top = cell.margin_bottom = Inches(0.04)
        p = cell.text_frame.paragraphs[0]
        p.text = h_text
        p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            r.font.name = TITLE_FONT
            r.font.size = Pt(font_size + 1)
            r.font.bold = True
            r.font.color.rgb = WHITE

    for row_idx, row in enumerate(rows_data):
        row_str = " ".join(str(c) for c in row).lower()
        is_required = "bắt buộc" in row_str
        is_out = "ngoài phạm vi" in row_str or "out of scope" in row_str
        
        row_bg = WHITE if row_idx % 2 == 0 else RGBColor(0xF8, 0xFA, 0xFC)
        text_color = INK
        
        if highlight_rules:
            rule = highlight_rules[row_idx]
            if rule == "better":
                row_bg = LIGHT_GREEN
            elif rule == "worse":
                row_bg = MUTED_ROW
                text_color = GRAY
            elif rule == "equal":
                row_bg = WHITE if row_idx % 2 == 0 else RGBColor(0xF8, 0xFA, 0xFC)

        if is_out:
            row_bg = RGBColor(0xFD, 0xFA, 0xFA)

        for col_idx, val in enumerate(row):
            cell = tbl.cell(row_idx + 1, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = row_bg
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = Inches(0.09)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            p = cell.text_frame.paragraphs[0]
            p.text = str(val)
            p.alignment = PP_ALIGN.LEFT
            for r in p.runs:
                r.font.name = BODY_FONT
                r.font.size = Pt(font_size)
                r.font.color.rgb = text_color
                if col_idx == 0:
                    r.font.bold = True
                    if is_required and not (highlight_rules and highlight_rules[row_idx] == "worse"):
                        r.font.color.rgb = RED
                elif col_idx == 1 and ("(" not in str(val) and len(str(val)) < 20):
                    r.font.name = "Consolas"
                    r.font.size = Pt(font_size - 0.5)


def generate_error_chart_image() -> BytesIO:
    """Generate high-resolution horizontal bar chart comparing Pipeline 01 vs VAI OCR errors."""
    fields = [
        ("Chức danh ký (signer_title)", 56, 17, False),
        ("Trích yếu (title)", 30, 12, True),
        ("Ngày ban hành (documentDate)", 29, 9, True),
        ("Cơ quan ban hành (officeSender)", 20, 20, True),
        ("Họ tên người ký (signer)", 19, 6, False),
        ("Số, ký hiệu (code)", 13, 6, True),
        ("Nơi nhận (recipients)", 10, 8, False),
        ("Kính gửi (first_recipients)", 8, 19, False),
        ("Độ khẩn (priority_level)", 5, 2, True),
        ("Loại văn bản (type)", 4, 2, True),
        ("Địa danh (province)", 2, 24, False),
        ("Độ mật (security_level)", 0, 2, True),
    ]
    fields = fields[::-1]
    labels = [f[0] for f in fields]
    pipe_errors = [f[1] for f in fields]
    vai_errors = [f[2] for f in fields]

    y = np.arange(len(labels))
    height = 0.38

    fig, ax = plt.subplots(figsize=(10.5, 6.8), dpi=200)
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FFFFFF')

    rects1 = ax.barh(y + height/2, pipe_errors, height, label='OCR Nội bộ (Pipeline 01 - v5)', color='#EE0033', edgecolor='none')
    rects2 = ax.barh(y - height/2, vai_errors, height, label='Viettel AI OCR (Đối chuẩn)', color='#172235', edgecolor='none')

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=11, fontweight='bold', color='#22282E')
    ax.set_xlabel('Tổng số ô trường bị lỗi (Đọc sai + Bỏ sót + Trả thừa)', fontsize=11, color='#60666D', fontweight='bold')
    ax.legend(loc='lower right', frameon=True, facecolor='#F5F7FA', edgecolor='#E0E5EB', fontsize=11)
    ax.grid(axis='x', linestyle='--', alpha=0.5, color='#D0D7DE')
    ax.set_axisbelow(True)

    for rect in rects1:
        w = rect.get_width()
        if w > 0:
            ax.annotate(f'{int(w)}',
                        xy=(w, rect.get_y() + rect.get_height() / 2),
                        xytext=(4, 0), textcoords="offset points",
                        ha='left', va='center', fontsize=10, fontweight='bold', color='#EE0033')
    for rect in rects2:
        w = rect.get_width()
        if w > 0:
            ax.annotate(f'{int(w)}',
                        xy=(w, rect.get_y() + rect.get_height() / 2),
                        xytext=(4, 0), textcoords="offset points",
                        ha='left', va='center', fontsize=10, fontweight='bold', color='#172235')

    ax.set_xlim(0, 64)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#D0D7DE')
    ax.spines['bottom'].set_color('#D0D7DE')
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_field_comparison_target_chart() -> BytesIO:
    """Generate high-res 2-subplot chart comparing Pipeline 01 vs VAI OCR across 12 fields with dotted target lines."""
    fields_info = [
        ('type', 'Loại VB', 96.0, 98.5, 96.0, 98.0),
        ('code', 'Số ký hiệu', 87.0, 94.5, 87.0, 94.0),
        ('documentDate', 'Ngày ban hành', 78.5, 94.3, 71.0, 91.0),
        ('officeSender', 'Cơ quan', 80.4, 81.2, 74.0, 80.0),
        ('title', 'Trích yếu', 70.7, 88.4, 41.0, 79.0),
        ('priority_level', 'Độ khẩn', 95.0, 98.5, 95.0, 98.0),
        ('security_level', 'Độ mật', 100.0, 98.5, 100.0, 98.0),
        ('signer', 'Người ký', 84.5, 94.4, 80.6, 93.9),
        ('signer_title', 'Chức danh', 45.7, 83.9, 37.8, 81.6),
        ('first_recipients', 'Kính gửi', 75.9, 43.3, 66.7, 20.0),
        ('recipients', 'Nơi nhận', 90.2, 92.0, 36.4, 43.2),
        ('province', 'Địa danh', 98.5, 76.4, 97.9, 75.3),
    ]

    labels = [f'{f[1]}\n({f[0]})' for f in fields_info]
    p_f1 = [f[2] for f in fields_info]
    v_f1 = [f[3] for f in fields_info]
    p_nem = [f[4] for f in fields_info]
    v_nem = [f[5] for f in fields_info]

    x = np.arange(len(labels))
    width = 0.36

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(17.2, 6.0), dpi=200, sharex=True)
    fig.patch.set_facecolor('#FFFFFF')

    # --- SUBPLOT 1: F1-SCORE ---
    ax1.set_facecolor('#FFFFFF')
    r1 = ax1.bar(x - width/2, p_f1, width, label='OCR Nội bộ (Pipeline 01 - v5)', color='#EE0033', edgecolor='none')
    r2 = ax1.bar(x + width/2, v_f1, width, label='Viettel AI OCR (Đối chuẩn)', color='#172235', edgecolor='none')

    ax1.axhline(y=85.0, color='#D97706', linestyle='--', linewidth=1.8, label='Target PoC: F1 ≥ 85% (0.85)')
    ax1.axhline(y=90.0, color='#16A34A', linestyle=':', linewidth=2.0, label='Target Kỳ vọng (Stretch): F1 ≥ 90% (0.90)')

    ax1.set_ylabel('F1-Score (%)', fontsize=10, fontweight='bold', color='#22282E')
    ax1.set_ylim(0, 118)
    ax1.grid(axis='y', linestyle='--', alpha=0.5, color='#D0D7DE')
    ax1.set_axisbelow(True)
    ax1.legend(loc='upper right', ncol=4, frameon=True, facecolor='#F5F7FA', edgecolor='#E0E5EB', fontsize=9.5)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.spines['left'].set_color('#D0D7DE')
    ax1.spines['bottom'].set_color('#D0D7DE')

    for rect in r1:
        h = rect.get_height()
        ax1.annotate(f'{h:.1f}%', xy=(rect.get_x() + rect.get_width()/2, h),
                     xytext=(0, 2), textcoords='offset points', ha='center', va='bottom',
                     fontsize=7.5, fontweight='bold', color='#EE0033')
    for rect in r2:
        h = rect.get_height()
        ax1.annotate(f'{h:.1f}%', xy=(rect.get_x() + rect.get_width()/2, h),
                     xytext=(0, 2), textcoords='offset points', ha='center', va='bottom',
                     fontsize=7.5, fontweight='bold', color='#172235')

    # --- SUBPLOT 2: NEM (Khớp tuyệt đối) ---
    ax2.set_facecolor('#FFFFFF')
    r3 = ax2.bar(x - width/2, p_nem, width, label='NEM Nội bộ (Pipeline 01)', color='#EE0033', alpha=0.85, edgecolor='none')
    r4 = ax2.bar(x + width/2, v_nem, width, label='NEM Viettel AI OCR', color='#172235', alpha=0.85, edgecolor='none')

    ax2.axhline(y=75.0, color='#2563EB', linestyle='--', linewidth=1.8, label='Target PoC: NEM ≥ 75% (0.75)')

    ax2.set_ylabel('NEM (%)', fontsize=10, fontweight='bold', color='#22282E')
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9.5, fontweight='bold', color='#22282E')
    ax2.set_ylim(0, 118)
    ax2.grid(axis='y', linestyle='--', alpha=0.5, color='#D0D7DE')
    ax2.set_axisbelow(True)
    ax2.legend(loc='upper right', ncol=3, frameon=True, facecolor='#F5F7FA', edgecolor='#E0E5EB', fontsize=9.5)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.spines['left'].set_color('#D0D7DE')
    ax2.spines['bottom'].set_color('#D0D7DE')

    for rect in r3:
        h = rect.get_height()
        ax2.annotate(f'{h:.1f}%', xy=(rect.get_x() + rect.get_width()/2, h),
                     xytext=(0, 2), textcoords='offset points', ha='center', va='bottom',
                     fontsize=7.5, fontweight='bold', color='#EE0033')
    for rect in r4:
        h = rect.get_height()
        ax2.annotate(f'{h:.1f}%', xy=(rect.get_x() + rect.get_width()/2, h),
                     xytext=(0, 2), textcoords='offset points', ha='center', va='bottom',
                     fontsize=7.5, fontweight='bold', color='#172235')

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def build_presentation():
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found at {TEMPLATE_PATH}")

    prs = Presentation(str(TEMPLATE_PATH))
    cover_source = prs.slides[0]
    content_source = prs.slides[1]
    closing_source = prs.slides[22]
    original_count = len(prs.slides)

    pages = []

    def content(title, source_text, section, *, number=None):
        slide = base_slide(prs, content_source, range(8))
        pages.append(slide)
        n = number or len(pages)
        textbox(slide, 1.33, 0.58, 15.5, 0.68, title,
                size=27, color=NAVY, bold=True, font=TITLE_FONT)
        textbox(slide, 1.35, 10.3, 14.3, 0.35, source_text,
                size=9, color=GRAY)
        textbox(slide, 18.78, 10.3, 0.65, 0.35, str(n).zfill(2),
                size=10, color=RED, align=PP_ALIGN.RIGHT)
        badge(slide, 1.36, 1.4, min(6.0, 1.2 + len(section) * 0.11), section.upper(),
              fill=LIGHT_RED, color=RED)
        return slide

    # =========================================================================
    # SLIDE 01 — COVER SLIDE (Exact team members & emails as paragraph lines)
    # =========================================================================
    s = base_slide(prs, cover_source, range(7))
    pages.append(s)
    textbox(s, 7.8, 2.7, 11.2, 1.8,
            "AI OCR cho văn bản hành chính\nDự án Văn phòng số (VPS)",
            size=38, color=WHITE, bold=True, font=TITLE_FONT)
    textbox(s, 7.85, 4.6, 11.0, 0.6,
            "Báo cáo kết quả thử nghiệm & Đánh giá đối chuẩn giải pháp KIE (PoC)",
            size=20, color=WHITE)
    
    # Exact team members & emails preserved 100%
    team_info = (
        "Trưởng phòng: Đỗ Quốc Hưng\n"
        "Quản lý dự án: Huỳnh Lê Bảo\n\n"
        "Các thành viên dự án:\n"
        "• Nguyễn Hoàng Nguyên  —  nguyennh7@viettel.com.vn\n"
        "• Bùi Đình Bảo  —  baobd1@viettel.com.vn\n"
        "• Nguyễn Xuân An  —  annx29@viettel.com.vn\n\n"
        "Thời gian: Tháng 10/2026  |  Đánh giá Full inference 100 văn bản hành chính"
    )
    textbox(s, 7.85, 5.3, 11.0, 3.8, team_info, size=15.5, color=RGBColor(0xF0, 0xF4, 0xF8), spacing=1.2)

    # =========================================================================
    # SLIDE 02 — BỐI CẢNH & VẤN ĐỀ NGHIỆP VỤ
    # =========================================================================
    s = content("Từ nhập liệu thủ công đến dữ liệu có cấu trúc",
                "Nguồn: Yêu cầu nghiệp vụ · Văn phòng số (VPS)", "01 · Bối cảnh")
    card(s, 1.35, 2.05, 5.5, 5.7, "Hiện trạng",
         "Nhân viên văn thư đọc từng trang PDF rồi nhập liệu thủ công số ký hiệu, ngày ban hành, cơ quan, trích yếu… vào hệ thống phần mềm.",
         emphasis="01", body_size=18)
    card(s, 7.07, 2.05, 5.5, 5.7, "Pain point",
         "Khối lượng văn bản lớn làm tăng chi phí nhân lực và thời gian xử lý; nguy cơ sai sót ký tự, nhầm lẫn ngày tháng và khó mở rộng quy mô.",
         emphasis="02", body_size=18)
    card(s, 12.78, 2.05, 5.9, 5.7, "Mục tiêu PoC",
         "Kiểm chứng giải pháp OCR/KIE nội bộ có khả năng tự động bóc tách cấu trúc 13 trường thông tin, kiểm soát độ chính xác và bảo mật dữ liệu.",
         emphasis="03", body_size=18)
    banner(s, 8.15, "Đánh giá tính khả thi kỹ thuật & đối chuẩn với giải pháp thương mại trên 100 văn bản thực tế.")

    # =========================================================================
    # SLIDE 03 — AGILE FLOW
    # =========================================================================
    s = content("Viettel Agile: học và tối ưu từ dữ liệu thật",
                "Nguồn: Quy chuẩn benchmark §6, §9 · docs/ocr_pipeline_benchmark_metrics.md", "01 · Bối cảnh")
    steps = [("Aware", "Nhận diện pain point"), ("Go Through", "Khảo sát nghiệp vụ"),
             ("Implement", "Xây pipeline KIE"), ("Learn", "Benchmark & Đo lỗi"),
             ("Enable", "Thử nghiệm UAT")]
    for i, (step, detail) in enumerate(steps):
        x = 1.36 + i * 3.53
        card(s, x, 2.3, 3.3, 2.95, step, detail,
             tint=LIGHT_RED if i == 3 else LIGHT,
             title_size=20, body_size=16)
    card(s, 1.36, 5.7, 8.45, 3.38, "Nhu cầu khách hàng là điểm xuất phát",
         "Đối chiếu biểu mẫu với BA để phân biệt rõ: trường nào OCR đọc từ PDF, trường nào người dùng nhập, trường nào hệ thống tự điền mặc định.",
         body_size=18)
    card(s, 10.1, 5.7, 8.67, 3.38, "Tối ưu dựa trên dữ liệu & bằng chứng",
         "Mọi điều chỉnh thuật toán phải dựa trên Ground Truth (GT), benchmark định lượng, trace vị trí và regression test; không sửa luật theo cảm tính.",
         body_size=18)

    # =========================================================================
    # SLIDE 04 — PHẠM VI DỮ LIỆU
    # =========================================================================
    s = content("Phạm vi dữ liệu thực tế — 100 văn bản hành chính",
                "Nguồn: full inference manifest.json + predictions.jsonl · 100 PDF benchmark", "02 · Dữ liệu")
    for i, (value, title, detail) in enumerate([
        ("100", "văn bản", "Có Ground Truth (GT) chuẩn hóa"),
        ("2.249", "trang PDF", "Độ dài từ 1 đến 353 trang / file"),
        ("69", "bản Scan", "Chất lượng mờ, nghiêng, dấu đỏ"),
        ("31", "Điện tử", "Bản in PDF digital rõ nét"),
    ]):
        card(s, 1.36 + 4.42 * i, 2.02, 4.13, 3.35, title, detail,
             emphasis=value, title_size=20, body_size=16)
    card(s, 1.36, 5.85, 8.45, 3.38, "Phân bổ thể loại văn bản",
         "Bao gồm Quyết định (30), Công văn (17), Nghị quyết, Thông báo, Thông tư, Kế hoạch, Báo cáo…\nBố cục trang bìa, header và phần ký đa dạng.", body_size=18)
    card(s, 10.1, 5.85, 8.67, 3.38, "Nguồn gốc & Đặc điểm phức tạp",
         "Cơ quan Chính phủ, Bộ/Ngành, UBND các tỉnh, Sở Giao dịch Chứng khoán, Doanh nghiệp…\nChứa nhiều yếu tố gây nhiễu: con dấu đỏ đè chữ, chữ ký tươi, chữ viết tay.", body_size=18)

    # =========================================================================
    # SLIDE 05 — HỢP ĐỒNG ĐẦU RA & 2 METRIC BAO QUÁT
    # =========================================================================
    s = content("Định nghĩa đầu ra & 2 chỉ số bao quát",
                "Nguồn: docs/ocr_pipeline_benchmark_metrics.md · §1, §5", "02 · Tiêu chí")
    card(s, 1.36, 2.03, 8.45, 5.66, "7 trường Bắt buộc & 5 trường Tùy chọn",
         "• 7 trường Bắt buộc (Required):\ntype · title · code · documentDate · officeSender · priority_level · security_level\n\n• 5 trường Tùy chọn (Optional) được chấm:\nrecipients · signer · first_recipients · signer_title · province\n\n• 1 trường Ngoài phạm vi (Out of scope):\nreceiverDate (luôn trả \"\" để giữ ổn định API schema).",
         body_size=17)
    card(s, 10.1, 2.03, 8.67, 5.66, "Hai chỉ số đánh giá bao quát",
         "🎯 Document Success@5% (Chỉ số mục tiêu chính):\nVăn bản chỉ đạt khi TẤT CẢ 7 trường bắt buộc có trong GT đều đúng (NCER ≤ 5%). Một trường sai → toàn bộ văn bản FAIL.\n\n📊 VAI-style Accuracy (Chỉ số tham chiếu đối chuẩn):\nĐo độ chính xác ký tự trung bình trên toàn bộ các trường theo chuẩn thương mại của Viettel AI.",
         tint=LIGHT_RED, body_size=17)
    banner(s, 8.02, "Target cam kết: F1/Precision/Recall ≥ 85%; Tỷ lệ khớp tuyệt đối NEM ≥ 75%.", size=20)

    # =========================================================================
    # SLIDE 06 — BẢNG DANH MỤC 13 TRƯỜNG API & TIÊU CHÍ (Thuần Việt & Metric gọn)
    # =========================================================================
    s = content("Danh mục 13 trường API & Tiêu chí đánh giá",
                "Nguồn: docs/ocr_pipeline_benchmark_metrics.md · §1, §5", "02 · Tiêu chí")
    headers = ["Tên trường (Tiếng Việt)", "Key API", "Nhóm trường", "Metric đánh giá chính", "Target đánh giá"]
    field_rows = [
        ["Loại văn bản", "type", "Bắt buộc", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Trích yếu / Tiêu đề", "title", "Bắt buộc", "Độ chính xác xấp xỉ (F1@5%, sai ≤ 5/100 ký tự)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Số, ký hiệu văn bản", "code", "Bắt buộc", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Ngày ban hành", "documentDate", "Bắt buộc", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Cơ quan ban hành", "officeSender", "Bắt buộc", "Độ chính xác xấp xỉ (F1@5%, sai ≤ 5/100 ký tự)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Độ khẩn", "priority_level", "Bắt buộc", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Độ mật", "security_level", "Bắt buộc", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Nơi nhận cuối VB", "recipients", "Quan trọng", "Độ chính xác xấp xỉ (F1@5%, sai ≤ 5/100 ký tự)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Họ tên người ký", "signer", "Quan trọng", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Kính gửi đầu VB", "first_recipients", "Quan trọng", "Độ chính xác xấp xỉ (F1@5%, sai ≤ 5/100 ký tự)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Chức danh người ký", "signer_title", "Quan trọng", "Độ chính xác xấp xỉ (F1@5%, sai ≤ 5/100 ký tự)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Địa danh ban hành", "province", "Tùy chọn", "Độ chính xác tuyệt đối (F1 Exact)", "F1 ≥ 85%, NEM ≥ 75%"],
        ["Ngày tiếp nhận", "receiverDate", "Ngoài phạm vi", "Không chấm (luôn trả \"\")", "— (Ngoài phạm vi)"],
    ]
    table_slide(s, 1.36, 2.05, 17.4, 7.8, headers, field_rows, [3.6, 2.2, 2.2, 5.2, 4.2], font_size=11)

    # =========================================================================
    # SLIDE 07 — DIỄN GIẢI 4 METRIC CỐT LÕI (Đơn giản, ngắn gọn, tường minh)
    # =========================================================================
    s = content("Ý nghĩa 4 Metric cốt lõi trong đánh giá OCR",
                "Nguồn: docs/ocr_pipeline_benchmark_metrics.md · §5", "03 · Success Metrics")
    
    card(s, 1.36, 2.05, 4.15, 5.8, "1. Document Success@5%",
         "🎯 Tỷ lệ văn bản đạt trọn vẹn:\n\n"
         "• Ý nghĩa: Đo lường tỷ lệ văn bản nạp thẳng được vào hệ thống VPS mà không cần con người sửa lại.\n\n"
         "• Nguyên tắc: Đạt khi TẤT CẢ 7 trường bắt buộc đều đúng (sai số ký tự ≤ 5%).\n\n"
         "• Tính nghiêm ngặt: Sai 1 trường bắt buộc → Cả văn bản KHÔNG ĐẠT.",
         emphasis="Nghiệp vụ", title_size=16.5, body_size=15, emphasis_color=RED)

    card(s, 5.78, 2.05, 4.15, 5.8, "2. F1-Score (F1 Exact & F1@5%)",
         "⚖ Cân bằng Bắt đúng & Bỏ sót:\n\n"
         "• Ý nghĩa: Đánh giá chất lượng của từng trường thông tin riêng biệt.\n\n"
         "• F1 Exact: Khớp chính xác 100% từng ký tự (dùng cho Ngày, Số hiệu, Tên người ký...).\n\n"
         "• F1@5%: Cho phép sai lệch nhỏ (CER ≤ 5%) đối với các đoạn văn dài (Trích yếu, Cơ quan...).",
         emphasis="Từng trường", title_size=16.5, body_size=15, emphasis_color=NAVY)

    card(s, 10.2, 2.05, 4.15, 5.8, "3. CER (Character Error Rate)",
         "🔍 Tỷ lệ sai sót ký tự:\n\n"
         "• Ý nghĩa: Đo lường tỷ lệ ký tự bị nhận dạng Sai (S), Bỏ sót (D) hoặc Thừa (I) trên độ dài văn bản gốc.\n\n"
         "• Công thức: CER = (S + D + I) / Tổng ký tự GT.\n\n"
         "• Chuẩn @5%: Sai không quá 5 trên 100 ký tự thì vẫn được tính là Đạt (Acceptable).",
         emphasis="Ký tự", title_size=16.5, body_size=15, emphasis_color=GRAY)

    card(s, 14.62, 2.05, 4.15, 5.8, "4. VAI-style Accuracy",
         "📊 Thước đo đối chuẩn thương mại:\n\n"
         "• Ý nghĩa: Độ chính xác ký tự trung bình trên toàn bộ văn bản theo công thức của Viettel AI.\n\n"
         "• Công thức: AoC = 1 - Số lỗi / Max(độ dài GT, độ dài AI).\n\n"
         "• Mục đích: So sánh khách quan và công bằng với các giải pháp thương mại lớn trên thị trường.",
         emphasis="Đối chuẩn", title_size=16.5, body_size=15, emphasis_color=GREEN)

    banner(s, 8.15, "Document Success đại diện cho ứng dụng nghiệp vụ; F1/CER đo chất lượng từng trường; VAI ACC đo năng lực OCR thô.")

    # =========================================================================
    # SLIDE 08 — KIẾN TRÚC PIPELINE
    # =========================================================================
    s = content("Kiến trúc Pipeline xử lý tự động end-to-end",
                "Nguồn: module/extract/vbhc_rules.py · Pipeline 01", "03 · Kiến trúc")
    for i, text in enumerate(["PDF Đầu vào", "Layout + Line OCR", "Trích xuất KIE", "Chuẩn hóa API", "Benchmark & Audit"]):
        panel(s, 1.36 + i * 3.52, 2.26, 3.27, 1.45, fill=LIGHT)
        textbox(s, 1.54 + i * 3.52, 2.65, 2.93, 0.65, text,
                size=19, bold=True, font=TITLE_FONT, align=PP_ALIGN.CENTER, color=NAVY)
    for i, (title, body) in enumerate([
        ("Chuẩn bị & Tiền xử lý", "Phân tích cấu trúc trang PDF, tách dòng văn bản, khử nhiễu và nhận dạng ký tự tiếng Việt với VietOCR."),
        ("Quy tắc KIE & Bóc tách", "Áp dụng tập luật hình học, neo vị trí (anchor) và biểu thức chính quy để trích xuất 13 trường nghiệp vụ."),
        ("Đánh giá & Truy vết", "Đo đạc tự động Document Success, VAI ACC; lưu trữ trace v2, bbox và OCR gốc để phân tích nguyên nhân lỗi."),
    ]):
        card(s, 1.36 + i * 5.83, 4.38, 5.55, 3.5, title, body, body_size=17)
    banner(s, 8.3, "Mô hình vận hành hoàn toàn độc lập, đảm bảo bảo mật dữ liệu và tự chủ về tài nguyên tính toán.")

    # =========================================================================
    # SLIDE 09 — KẾT QUẢ TỔNG THỂ (SO SÁNH NỘI BỘ VS VAI OCR)
    # =========================================================================
    s = content("Kết quả tổng thể — So sánh OCR Nội bộ vs VAI OCR",
                "Nguồn: ocr-collab/reports/vai_acc_v1_20261002/ · Đánh giá trên cùng 100 PDF & GT chuẩn", "04 · Kết quả")
    
    card(s, 1.36, 2.05, 5.55, 3.3, "Document Success@5%",
         "Nội bộ: 36 / 100 văn bản (36%)\nVAI OCR: 59 / 100 văn bản (59%)\nMục tiêu PoC: ≥ 80% (80 văn bản)",
         emphasis="36% vs 59%", body_size=17)
    card(s, 7.13, 2.05, 5.55, 3.3, "Độ chính xác ký tự (12 trường)",
         "Nội bộ: 89,03% ACC\nVAI OCR: 92,38% ACC\nKhoảng cách chênh lệch: ~3,35%",
         emphasis="89,0% vs 92,4%", body_size=17)
    card(s, 12.9, 2.05, 5.88, 3.3, "Độ chính xác (6 trường chung)",
         "Nội bộ: 91,45% ACC\nVAI OCR: 94,04% ACC\n(Gồm: code, date, sender, type, signer, title)",
         emphasis="91,5% vs 94,0%", body_size=17)
    
    card(s, 1.36, 5.65, 17.4, 2.3, "Nhận định tổng quan từ Ban Dự án",
         "• Độ chính xác ở mức độ ký tự của cả 2 hệ thống đều đạt mức khá cao (xấp xỉ 90% - 94%), cho thấy năng lực nhận diện chữ tiếng Việt tốt.\n• Tuy nhiên, tỷ lệ văn bản đạt hoàn hảo 7 trường bắt buộc (Document Success) còn thấp (36% và 59%), cả 2 đều chưa đạt mốc PoC 80%.\n• Nguyên nhân chính: Chỉ cần sai sót 1 ký tự ở trường bắt buộc (như ngày ban hành hoặc số hiệu) là văn bản bị tính không đạt.",
         body_size=17, tint=LIGHT_RED)
    banner(s, 8.25, "ACC là chỉ số tham chiếu đối chuẩn; quyết định chất lượng ứng dụng nằm ở Document Success@5%.")

    # =========================================================================
    # SLIDE 10 (NEW) — BÁO CÁO THỜI GIAN CHẠY & TÀI NGUYÊN SỬ DỤNG
    # =========================================================================
    s = content("Thời gian xử lý & Tài nguyên hệ thống",
                "Nguồn: docs/ocr_pipeline_benchmark_metrics.md §8 · Benchmark Quadro RTX 5000 (100 PDF, 2.249 trang)", "04 · Hiệu năng")
    
    # 4 Cards for Performance & Hardware Stats
    card(s, 1.36, 2.05, 4.15, 3.25, "Thời gian TB / Văn bản",
         "• Trung bình: 53,5 s / văn bản\n• Trung bình / trang: 2,69 s / trang\n• Tốc độ xử lý ổn định trên các tệp từ 1 đến 353 trang.",
         emphasis="53,5 s", body_size=15.5)

    card(s, 5.78, 2.05, 4.15, 3.25, "RAM Tiến trình (CPU)",
         "• RAM Trung bình: 4.835 MB (~4,7 GB)\n• RAM Đỉnh (Peak): 5.858 MB (~5,7 GB)\n• Mức tiêu thụ tối ưu, phù hợp server tiêu chuẩn.",
         emphasis="4,8 / 5,9 GB", body_size=15.5, emphasis_color=NAVY)

    card(s, 10.2, 2.05, 4.15, 3.25, "VRAM Toàn GPU (Device)",
         "• Device VRAM TB: 3.720 MB\n• Device VRAM Đỉnh: 7.370 MB (~7,2 GB)\n• Chạy trên GPU NVIDIA Quadro RTX 5000 16GB.",
         emphasis="3,7 / 7,4 GB", body_size=15.5, emphasis_color=NAVY)

    card(s, 14.62, 2.05, 4.15, 3.25, "Framework Allocator",
         "• PyTorch (VietOCR): TB 120 MB / Đỉnh 3.446 MB\n• Paddle (Layout): TB 112 MB / Đỉnh 117 MB\n• Không bị rò rỉ bộ nhớ (memory leak).",
         emphasis="PyTorch / Paddle", body_size=15.5, emphasis_color=GREEN)

    # Detailed table of execution time breakdown by page buckets
    time_headers = ["Nhóm quy mô tài liệu", "Số lượng file", "Tổng số trang", "Thời gian TB / File", "Thời gian TB / Trang", "Thời gian Min – Max"]
    time_rows = [
        ["Văn bản ngắn (1 – 10 trang)", "62 văn bản", "217 trang", "9,8 giây / file", "2,87 s / trang", "2,64 s – 34,71 s"],
        ["Văn bản vừa (11 – 30 trang)", "20 văn bản", "330 trang", "40,0 giây / file", "2,45 s / trang", "23,40 s – 89,08 s"],
        ["Văn bản dài (> 30 trang)", "18 văn bản", "1.702 trang", "218,9 giây / file", "2,34 s / trang", "85,78 s – 748,05 s (353 trang)"],
        ["Toàn bộ tập mẫu Benchmark", "100 văn bản", "2.249 trang", "53,5 giây / file", "2,69 s / trang", "2,64 s – 748,05 s"],
    ]
    table_slide(s, 1.36, 5.55, 17.4, 2.45, time_headers, time_rows,
                [4.0, 2.2, 2.2, 3.0, 2.8, 3.2], font_size=11)
    
    banner(s, 8.25, "Tài nguyên VRAM (đỉnh 7,4 GB) và RAM (5,9 GB) chứng minh mô hình hoạt động an toàn trên hạ tầng máy chủ GPU thương mại.")

    # =========================================================================
    # SLIDE 11 — SO SÁNH CHI TIẾT 12 TRƯỜNG (Highlight xanh Nội bộ tốt hơn, xám VAI tốt hơn)
    # =========================================================================
    s = content("So sánh chi tiết 12 trường: OCR Nội bộ vs VAI OCR",
                "Nguồn: ocr-collab/reports/vai_acc_v1_20261002/ · Metric v2.2 + VAI ACC v1.0", "04 · Kết quả")
    
    headers_12 = ["Trường thông tin", "Nhóm", "F1 Nội bộ", "NEM Nội bộ", "ACC Nội bộ", "F1 VAI", "NEM VAI", "ACC VAI", "Đánh giá thế mạnh"]
    data_12 = [
        ["Loại văn bản (type)", "Bắt buộc", "96.0%", "96.0%", "96.6%", "98.5%", "98.0%", "98.1%", "Tương đương"],
        ["Trích yếu (title)", "Bắt buộc", "70.7%", "41.0%", "92.3%", "88.4%", "79.0%", "96.1%", "VAI tốt hơn"],
        ["Số, ký hiệu (code)", "Bắt buộc", "87.0%", "87.0%", "98.6%", "94.5%", "94.0%", "97.8%", "VAI tốt hơn"],
        ["Ngày ban hành (documentDate)", "Bắt buộc", "78.5%", "71.0%", "79.7%", "94.3%", "91.0%", "95.2%", "VAI tốt hơn"],
        ["Cơ quan ban hành (officeSender)", "Bắt buộc", "80.4%", "74.0%", "93.3%", "81.2%", "80.0%", "86.7%", "Tương đương"],
        ["Độ khẩn (priority_level)", "Bắt buộc", "95.0%", "95.0%", "96.2%", "98.5%", "98.0%", "98.2%", "Tương đương"],
        ["Độ mật (security_level)", "Bắt buộc", "100.0%", "100.0%", "100.0%", "98.5%", "98.0%", "98.2%", "Nội bộ đạt 100%"],
        ["Nơi nhận (recipients)", "Quan trọng", "90.2%", "36.4%", "94.0%", "92.1%", "43.2%", "94.2%", "Tương đương"],
        ["Họ tên người ký (signer)", "Quan trọng", "84.5%", "80.6%", "86.9%", "94.4%", "93.9%", "96.9%", "VAI tốt hơn"],
        ["Kính gửi (first_recipients)", "Quan trọng", "75.9%", "66.7%", "88.5%", "43.3%", "20.0%", "79.1%", "Nội bộ vượt trội (+32.6%)"],
        ["Chức danh ký (signer_title)", "Quan trọng", "45.7%", "37.8%", "71.8%", "83.9%", "81.6%", "89.2%", "VAI tốt hơn"],
        ["Địa danh (province)", "Tùy chọn", "98.5%", "97.9%", "98.9%", "76.4%", "75.3%", "91.8%", "Nội bộ vượt trội (+22.1%)"],
    ]
    
    highlight_rules_12 = [
        "equal",  # type
        "worse",  # title
        "worse",  # code
        "worse",  # documentDate
        "equal",  # officeSender
        "equal",  # priority_level
        "better", # security_level
        "equal",  # recipients
        "worse",  # signer
        "better", # first_recipients
        "worse",  # signer_title
        "better", # province
    ]
    
    table_slide(s, 1.36, 2.05, 17.4, 7.8, headers_12, data_12,
                [3.0, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 3.2], font_size=10.5,
                highlight_rules=highlight_rules_12)

        # =========================================================================
    # SLIDE 12 — BIỂU ĐỒ SO SÁNH 12 TRƯỜNG & DOTTED TARGET LINES (0.85, 0.90)
    # =========================================================================
    s = content("Biểu đồ so sánh 12 trường & Mốc mục tiêu PoC",
                "Nguồn: ocr-collab/reports/vai_acc_v1_20261002/ · So sánh mốc PoC F1 ≥ 85% & Kỳ vọng 90%", "04 · Đối chuẩn")
    
    target_chart_buf = generate_field_comparison_target_chart()
    s.shapes.add_picture(target_chart_buf, Inches(1.36), Inches(2.05), width=Inches(17.4), height=Inches(6.05))
    
    banner(s, 8.25, "F1 PoC (≥85%) đạt 6/12 trường (Nội bộ) vs 10/12 (VAI); Nội bộ vượt trội ở Địa danh (98.5% vs 76.4%) và Kính gửi (75.9% vs 43.3%).")

# =========================================================================
    # SLIDE 12 — DEMO 1 TRANG CLEAN (Exact GT & Prediction matching 3116+QĐ-BKHCN)
    # =========================================================================
    s = content("Demo trích xuất thông tin thực tế từ văn bản",
                "Nguồn: predictions.jsonl · File 3116+QĐ-BKHCN (2 trang scan)", "04 · Demo")
    photo(s, "demo-3116.webp", 1.36, 2.05, 7.2, 7.7, caption="3116+QĐ-BKHCN · Ảnh trang 1 và vùng nhận dạng")
    
    demo_headers = ["Trường thông tin", "Dữ liệu chuẩn (Ground Truth)", "Kết quả OCR Nội bộ", "Đánh giá"]
    demo_rows = [
        ["Loại văn bản", "QUYẾT ĐỊNH", "QUYẾT ĐỊNH", "Exact (Đúng)"],
        ["Số, ký hiệu", "3116/QĐ-BKHCN", "3116/QĐ-BKHCN", "Exact (Đúng)"],
        ["Ngày ban hành", "14/07/2026", "14/07/2026", "Exact (Đúng)"],
        ["Cơ quan ban hành", "BỘ KHOA HỌC VÀ CÔNG NGHỆ", "BỘ KHOA HỌC VÀ CÔNG NGHỆ", "Exact (Đúng)"],
        ["Trích yếu / Tiêu đề", "Quy định cơ cấu tổ chức của Quỹ Đổi mới...", "Quy định cơ cấu tổ chức của Quỹ Đối mới...", "Acceptable (CER=1.6% ≤ 5%)"],
        ["Độ khẩn / Độ mật", "0_BÌNH THƯỜNG / 0_BÌNH THƯỜNG", "0_BÌNH THƯỜNG / 0_BÌNH THƯỜNG", "Exact (Đúng)"],
        ["Họ tên người ký", "Vũ Hải Quân", "Vũ Hải Quân", "Exact (Đúng)"],
        ["Chức danh người ký", "BỘ TRƯỞNG", "BỘ TRƯỞNG", "Exact (Đúng)"],
        ["Địa danh ban hành", "Hà Nội", "Hà Nội", "Exact (Đúng)"],
        ["Kính gửi đầu VB", "“ ” (Không có trong văn bản)", "“ ” (Không bịa thông tin)", "Correct Absent (Đúng)"],
    ]
    table_slide(s, 8.86, 2.05, 9.9, 7.7, demo_headers, demo_rows, [2.3, 3.4, 3.4, 1.8], font_size=10.5)

    # =========================================================================
    # SLIDE 13 — THỐNG KÊ LỖI & THỨ TỰ ƯU TIÊN CẢI THIỆN
    # =========================================================================
    s = content("Thống kê lỗi các trường & Thứ tự ưu tiên cải thiện",
                "Nguồn: ocr-collab/reports/vai_acc_v1_20261002/ · 196 lỗi Nội bộ vs 127 lỗi VAI", "04 · Phân tích lỗi")
    
    chart_buf = generate_error_chart_image()
    s.shapes.add_picture(chart_buf, Inches(1.36), Inches(2.05), width=Inches(9.2), height=Inches(5.9))
    
    card(s, 10.8, 2.05, 7.95, 5.9, "Thứ tự ưu tiên cải thiện nghiệp vụ",
         "🎯 CHIẾN LƯỢC TẬP TRUNG NGUỒN LỰC:\n\n"
         "1. Cơ quan ban hành (officeSender)\n"
         "2. Số, ký hiệu văn bản (code)\n"
         "3. Ngày ban hành (documentDate)\n"
         "4. Trích yếu / tiêu đề (title)\n"
         "5. Họ tên người ký (signer)\n"
         "6. Chức danh người ký (signer_title)\n\n"
         "💡 Lý do ưu tiên:\n"
         "• Nhóm 1-4 là các trường Bắt buộc (Required) quyết định tính pháp lý và nâng nhanh tỷ lệ Document Success.\n"
         "• Nhóm 5-6 là vùng ký ở cuối văn bản, được xử lý tiếp theo sau khi đã hoàn thiện phần header.",
         tint=LIGHT_RED, title_size=18, body_size=15)
    
    banner(s, 8.2, "OCR Nội bộ có 196 lỗi (147 Đọc sai, 49 Bỏ sót, 0 Trả thừa); không bịa thông tin khi thiếu dữ liệu.", size=19)

    # =========================================================================
    # SLIDE 14 — EVIDENCE 01: OCR KÝ TỰ NGÀY & CƠ QUAN
    # =========================================================================
    s = content("Một ký tự OCR sai làm hỏng trường bắt buộc",
                "Nguồn: field_errors.csv · File 8931+VPCP-PL trang 1 · Lỗi nhận dạng OCR", "04 · Phân tích lỗi")
    photo(s, "ocr-date-8931.webp", 1.36, 2.1, 7.65, 2.25, caption="Ngày ban hành · bbox [847, 274, 1337, 308]")
    photo(s, "ocr-sender-8931.webp", 1.36, 4.65, 7.65, 2.25, caption="Cơ quan ban hành · bbox [236, 154, 663, 195]")
    
    quote(s, 9.35, 2.1, 9.4, "Giá trị đúng (Ground Truth) · documentDate", "29/08/2026", good=True)
    quote(s, 9.35, 3.25, 9.4, "OCR Nội bộ đọc được (Đọc sai ký tự)", "19/08/2026 (Nhận nhầm số 2 thành số 1 do vết scan)")
    quote(s, 9.35, 4.65, 9.4, "Giá trị đúng (Ground Truth) · officeSender", "VĂN PHÒNG CHÍNH PHỦ", good=True)
    quote(s, 9.35, 5.8, 9.4, "OCR Nội bộ đọc được (Dính chữ)", "VĂN PHÒNG CHÍNH PHỦNH PHỦ")
    
    textbox(s, 9.37, 7.1, 9.35, 2.0,
            "Đánh giá nghiệp vụ: Lỗi phát sinh do bước OCR nhận dạng ký tự thô từ bản scan chất lượng kém. Cần cải thiện tiền xử lý ảnh và áp dụng luật kiểm tra logic ngày tháng.",
            size=17, color=INK)

    # =========================================================================
    # SLIDE 15 — EVIDENCE 02: DẤU MỘC ĐỎ & VÙNG KÝ
    # =========================================================================
    s = content("Dấu mộc đỏ che khuất và chữ ký đè chữ",
                "Nguồn: field_errors.csv · File 29+CT-TTg trang 1 & 4 · Dấu mộc & Vùng ký", "04 · Phân tích lỗi")
    photo(s, "stamp-29.webp", 1.36, 2.05, 4.98, 7.5, caption="Trang 1 · Con dấu đỏ Hỏa tốc bị mờ")
    photo(s, "sign-29.webp", 6.54, 2.05, 4.98, 7.5, caption="Trang 4 · Chữ ký đè lên tên người ký")
    
    quote(s, 11.79, 2.05, 6.98, "Độ khẩn (priority_level)", "GT: 1_HỎA TỐC  →  Dự đoán: 0_BÌNH THƯỜNG", h=1.35, size=16)
    quote(s, 11.79, 3.6, 6.98, "Họ tên người ký (signer)", "GT: Hồ Quốc Dũng  →  OCR đọc: Huốc Dũng", h=1.35, size=16)
    quote(s, 11.79, 5.15, 6.98, "Chức danh người ký (signer_title)", "GT: KT. THỦ TƯỚNG PHÓ THỦ TƯỚNG  →  Bỏ sót", h=1.35, size=15)
    
    textbox(s, 11.85, 6.85, 6.9, 2.4,
            "Đánh giá nghiệp vụ: Dấu đỏ che khuất chữ và chữ ký đè lên text là thách thức lớn nhất ở vùng ký. Cần thêm module bóc tách lớp màu (color separation) để lọc con dấu đỏ.",
            size=16, color=INK)

    # =========================================================================
    # SLIDE 16 — EVIDENCE 03: PHÂN VÙNG LAYOUT & TRÍCH YẾU
    # =========================================================================
    s = content("Phân vùng Layout: Trích yếu lẫn tên cơ quan & Bắt nhầm anchor",
                "Nguồn: field_errors.csv · File 12+NQ-PVIRe & 240+TB-PVIRe · Phân vùng Layout", "04 · Phân tích lỗi")
    photo(s, "layout-title-12.webp", 1.36, 2.1, 8.42, 4.0, caption="12+NQ · Khung bbox trích yếu bị kéo dài lên trên")
    photo(s, "layout-sender-240.webp", 10.1, 2.1, 8.68, 4.0, caption="240+TB · Bắt nhầm anchor 'Số:' làm tên cơ quan")
    
    card(s, 1.36, 6.4, 8.42, 2.75, "12+NQ-PVIRe · Trích yếu (title) bị thừa text",
         "GT: “Về việc chốt danh sách cổ đông…”\nOCR Nội bộ: Gom nhầm cả dòng “SỞ GIAO DỊCH CHỨNG KHOÁN HÀ NỘI… HỘI ĐỒNG QUẢN TRỊ” vào trích yếu.",
         body_size=16)
    card(s, 10.1, 6.4, 8.68, 2.75, "240+TB-PVIRe · Bắt nhầm Cơ quan ban hành",
         "GT: “TỔNG CÔNG TY CỔ PHẦN TÁI BẢO HIỂM PVI”\nOCR Nội bộ: Trả ra nhãn “Số:” do anchor nhận diện nhầm vị trí góc trên bên trái.",
         body_size=16)

    # =========================================================================
    # SLIDE 17 — EVIDENCE 04: LỌC NHIỄU KÍNH GỬI
    # =========================================================================
    s = content("Hậu xử lý trích xuất: Lọc nhiễu vùng Kính gửi",
                "Nguồn: field_errors.csv · File 2125+TB-ĐLTKV · Quy tắc Kính gửi", "04 · Phân tích lỗi")
    photo(s, "extract-2125.webp", 1.36, 2.1, 17.4, 2.8, caption="Vùng Kính gửi đầu văn bản · bbox [473, 616, 1450, 767]")
    quote(s, 1.36, 5.2, 17.4, "Giá trị đúng (Ground Truth) · first_recipients",
          "Ủy ban Chứng khoán Nhà nước; Sở Giao dịch Chứng khoán Hà Nội; Trung tâm Lưu ký Chứng khoán Việt Nam.",
          good=True, h=1.1, size=17)
    quote(s, 1.36, 6.5, 17.4, "Kết quả OCR Nội bộ (Dính text rác từ con dấu)",
          "Uỷ ban Chứng khoán Nhà nước; số 1.772; Sở Giao dịch Chứng khoán Hà Nội; Trung tâm Lưu ký Chứng khoán Việt Nam.",
          h=1.15, size=17)
    textbox(s, 1.45, 8.0, 17.05, 1.1,
            "Đánh giá nghiệp vụ: Chuỗi 'số 1.772' là text từ dấu công văn đến lọt vào vùng Kính gửi. Đã bổ sung bộ lọc stub tự động để loại bỏ các số hiệu lạc dòng.",
            size=17, color=INK)

    # =========================================================================
    # SLIDE 18 — EVIDENCE 05: RÀ SOÁT GROUND TRUTH (GT)
    # =========================================================================
    s = content("Rà soát tính chuẩn xác của nhãn Ground Truth (GT)",
                "Nguồn: field_errors.csv · File 03+BC.HĐQT & 27+2026+VBHN · Chuẩn hóa GT", "04 · Phân tích lỗi")
    photo(s, "gt-03.webp", 1.36, 2.1, 8.43, 3.3, caption="Ảnh gốc: “Số 03/BC HĐQT”")
    photo(s, "gt-27.webp", 10.1, 2.1, 8.68, 3.3, caption="Ảnh gốc: “Số 27/2026/VBHN-NĐ-BTC”")
    
    card(s, 1.36, 5.65, 8.43, 3.55, "03+BC.HĐQT · Dấu chấm hay gạch nối",
         "GT gắn nhãn: 03/BC.HĐQT\nOCR Nội bộ chuẩn hóa: 03/BC-HĐQT (đổi dấu cách thành '-').\nCần thống nhất quy tắc gán nhãn GT chuẩn cho các ký tự phân cách.",
         body_size=17)
    card(s, 10.1, 5.65, 8.68, 3.55, "27+2026+VBHN · Ký tự có dấu trong GT",
         "GT gắn nhãn: …-ND-BTC (viết thiếu dấu 'Đ')\nOCR Nội bộ nhận dạng: …-NĐ-BTC (đúng theo ảnh gốc).\nCần người review xác nhận cập nhật GT, tránh chấm phạt oan cho mô hình.",
         body_size=17)

    # =========================================================================
    # SLIDE 19 — ĐÁNH GIÁ TÍNH KHẢ THI
    # =========================================================================
    s = content("Đánh giá tính khả thi của giải pháp OCR Nội bộ",
                "Nguồn: Tổng hợp đánh giá PoC · Văn phòng số (VPS)", "05 · Đánh giá")
    card(s, 1.36, 2.1, 8.44, 5.75, "Đã chứng minh thành công",
         "✔ Làm chủ 100% pipeline xử lý tự động end-to-end từ PDF đến JSON 13 trường.\n\n✔ Tự chủ hoàn toàn về công nghệ, bảo mật dữ liệu văn bản hành chính tuyệt đối.\n\n✔ Tiết kiệm chi phí vận hành so với việc gọi API thương mại trả phí theo trang.\n\n✔ Xây dựng được hệ thống benchmark, bộ đo lường và quy trình audit truy vết lỗi chuẩn mực.",
         body_size=18)
    card(s, 10.1, 2.1, 8.68, 5.75, "Thách thức cần vượt qua",
         "✖ Tỷ lệ Document Success (36%) còn cách mục tiêu PoC 80%.\n\n✖ Độ chính xác ở các trường Ngày ban hành, Trích yếu và Chức danh ký cần được cải thiện.\n\n✖ Cần xử lý triệt để các trường hợp scan khó: dấu đỏ che chữ, chữ viết tay và trang xoay nghiêng.",
         tint=LIGHT_RED, body_size=18)
    banner(s, 8.15, "Kết luận: Giải pháp nội bộ hoàn toàn khả thi để tiếp tục hoàn thiện và tiến tới triển khai thử nghiệm UAT.")

    # =========================================================================
    # SLIDE 20 — KẾ HOẠCH HÀNH ĐỘNG TIẾP THEO
    # =========================================================================
    s = content("Lộ trình cải thiện & Kế hoạch hành động",
                "Nguồn: Kế hoạch R&D giai đoạn tiếp theo · VPS OCR Team", "06 · Kế hoạch")
    card(s, 1.36, 2.05, 5.5, 5.8, "01 · Tối ưu Dữ liệu",
         "• Bổ sung mẫu scan khó: văn bản có dấu đỏ đậm, chữ ký đè, chữ viết tay và văn bản dài.\n\n• Rà soát và chuẩn hóa 100% bộ Ground Truth (GT) theo đúng quy chuẩn thống nhất với BA.\n\n• Chia tập dữ liệu Train / Dev / Test chuẩn mực phục vụ fine-tuning.",
         body_size=17)
    card(s, 7.08, 2.05, 5.5, 5.8, "02 · Nâng cấp Kỹ thuật",
         "• Tập trung xử lý theo thứ tự ưu tiên: Cơ quan → Số KH → Ngày → Trích yếu → Họ tên → Chức danh.\n\n• Bổ sung module khử dấu đỏ & nâng cấp thuật toán phân vùng Layout Parser.\n\n• Fine-tune VietOCR chuyên biệt cho font chữ hành chính và chữ số ngày tháng.",
         body_size=17)
    card(s, 12.8, 2.05, 5.98, 5.8, "03 · Thử nghiệm & Triển khai",
         "• Tự động hóa kiểm thử hồi quy (Regression Test) sau mỗi phiên bản cập nhật.\n\n• Đạt ngưỡng Document Success ≥ 80% trước khi tối ưu tốc độ và tài nguyên GPU.\n\n• Tiến hành thử nghiệm thực tế có kiểm soát tại môi trường UAT của Văn phòng số (VPS).",
         body_size=17)
    banner(s, 8.2, "Mục tiêu: Đạt Document Success ≥ 80% trong đợt cập nhật tiếp theo để sẵn sàng thử nghiệm UAT.")

    # =========================================================================
    # SLIDE 21 — CLOSING SLIDE
    # =========================================================================
    s = base_slide(prs, closing_source, range(7))
    pages.append(s)
    textbox(s, 7.8, 3.8, 11.1, 1.4, "TRÂN TRỌNG CẢM ƠN!",
            size=48, color=WHITE, bold=True, font=TITLE_FONT)
    textbox(s, 7.85, 5.4, 11.0, 1.8,
            "Nhóm dự án rất mong nhận được ý kiến đóng góp & chỉ đạo từ Ban Lãnh đạo!\n\n"
            "Liên hệ: Nhóm Phát triển OCR Văn bản hành chính (VPS / AI Solutions)",
            size=21, color=WHITE, spacing=1.2)

    # Remove template source slides
    for _ in range(original_count):
        slide_id = prs.slides._sldIdLst[0]
        prs.part.drop_rel(slide_id.rId)
        prs.slides._sldIdLst.remove(slide_id)

    prs.core_properties.title = "Báo cáo thử nghiệm AI OCR Văn bản hành chính (VBHC)"
    prs.core_properties.subject = "VPS OCR Demo Report · Full inference v5 & VAI Benchmark"
    
    tmp_out = Path("/tmp/vps_ocr_demo_report_final.pptx")
    prs.save(str(tmp_out))
    print(f"Saved to temporary path: {tmp_out} ({tmp_out.stat().st_size:,} bytes)")
    
    OUTPUT_REPO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tmp_out, OUTPUT_REPO)
    print(f"Saved to Repo Draft Path: {OUTPUT_REPO}")

    for target_path in [OUTPUT_UPDATED_NAME, OUTPUT_FINAL_NAME, OUTPUT_WSL, OUTPUT_TARGET]:
        try:
            shutil.copyfile(tmp_out, target_path)
            print(f"Successfully saved: {target_path}")
        except Exception as e:
            print(f"Notice: could not overwrite {target_path.name}: {e}")


if __name__ == "__main__":
    build_presentation()
