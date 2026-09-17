#!/usr/bin/env python3
"""Audit raw label values against their paired PDF text layer.

The script deliberately does not use OCR.  It extracts an existing PDF text
layer with ``pdftotext`` and, when that layer is too sparse, can render the
first and final pages with ``pdftoppm`` for a human visual review.

Example:
    python3 scripts/audit_information_pdf.py \
      --root data/benchmark_demo/raw \
      --report /tmp/information-pdf-audit.json \
      --render-review-dir /tmp/information-pdf-review
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterator


def normalise(value: str) -> str:
    """Compare Vietnamese strings without case, accents, whitespace or punctuation."""
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def information_values(value: Any, path: str = "information") -> Iterator[tuple[str, str]]:
    """Yield every non-empty string stored in a {value, type} schema leaf."""
    if isinstance(value, dict):
        if isinstance(value.get("value"), str) and "type" in value:
            candidate = value["value"].strip()
            if candidate:
                yield path, candidate
            return
        for key, child in value.items():
            yield from information_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from information_values(child, f"{path}[{index}]")


def leaf_name(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def date_in_text(value: str, text: str) -> bool:
    """Accept either dd/mm/yyyy or Vietnamese long-date presentation."""
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    if not match:
        return False
    day, month = (str(int(part)) for part in match.groups()[:2])
    year = match.group(3)
    return bool(
        re.search(
            rf"\b0?{day}\D+0?{month}\D+{year}\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def enum_display(value: str) -> str | None:
    """Return display text for an enum, or None for the unprinted normal state."""
    prefix, separator, display = value.partition("_")
    if not separator:
        return value
    if prefix == "0" and normalise(display) == "binhthuong":
        return None
    return display


def check_field(path: str, value: str, text: str) -> tuple[str, str]:
    """Return (status, checked_value) without claiming a visual result."""
    field = leaf_name(path)
    if field in {"priority_level", "security_level"}:
        display = enum_display(value)
        if display is None:
            return "non_textual_normal_enum", ""
        value = display

    if normalise(value) in normalise(text):
        return "present_text", value
    if field == "documentDate" and date_in_text(value, text):
        return "present_text_date_format", value
    return "not_found_text", value


def tool_output(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def page_count(pdf: Path) -> int | None:
    try:
        output = tool_output(["pdfinfo", str(pdf)])
    except subprocess.CalledProcessError:
        return None
    match = re.search(r"^Pages:\s+(\d+)$", output, re.MULTILINE)
    return int(match.group(1)) if match else None


def extract_text(pdf: Path) -> str:
    try:
        return tool_output(["pdftotext", "-layout", str(pdf), "-"])
    except subprocess.CalledProcessError:
        return ""


def render_page(pdf: Path, page: int, destination: Path, dpi: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "pdftoppm",
            "-f", str(page),
            "-l", str(page),
            "-r", str(dpi),
            "-jpeg",
            "-singlefile",
            str(pdf),
            str(destination.with_suffix("")),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/benchmark_demo/raw"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--low-text-chars", type=int, default=500)
    parser.add_argument("--render-review-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()

    for executable in ("pdftotext", "pdfinfo"):
        if shutil.which(executable) is None:
            raise SystemExit(f"Missing required executable: {executable}")
    if args.render_review_dir and shutil.which("pdftoppm") is None:
        raise SystemExit("Missing required executable: pdftoppm")

    documents: list[dict[str, Any]] = []
    for label in sorted(args.root.glob("data_*/label/*.json")):
        group = label.parent.parent.name
        pdf = label.parent.parent / f"{label.stem}.pdf"
        if not pdf.exists():
            documents.append(
                {
                    "group": group,
                    "json": str(label),
                    "pdf": str(pdf),
                    "status": "missing_pdf",
                    "fields": [],
                }
            )
            continue

        raw = json.loads(label.read_text(encoding="utf-8"))
        text = extract_text(pdf)
        fields = []
        for path, value in information_values(raw.get("information", [])):
            status, checked_value = check_field(path, value, text)
            fields.append({"path": path, "value": value, "checked_value": checked_value, "status": status})
        low_text = len(text.strip()) < args.low_text_chars
        document = {
            "group": group,
            "json": str(label),
            "pdf": str(pdf),
            "pages": page_count(pdf),
            "text_characters": len(text.strip()),
            "needs_visual_review": low_text,
            "fields": fields,
        }
        documents.append(document)

        if low_text and args.render_review_dir:
            total_pages = document["pages"] or 1
            render_page(
                pdf,
                1,
                args.render_review_dir / f"{group}__{label.stem}--p1.jpg",
                args.dpi,
            )
            if total_pages > 1:
                render_page(
                    pdf,
                    total_pages,
                    args.render_review_dir / f"{group}__{label.stem}--plast.jpg",
                    args.dpi,
                )

    field_statuses = Counter(
        field["status"] for document in documents for field in document["fields"]
    )
    payload = {
        "method": "pdftotext -layout; optional pdftoppm first-page rendering; no OCR",
        "root": str(args.root),
        "documents": documents,
        "summary": {
            "documents": len(documents),
            "needs_visual_review": sum(bool(doc.get("needs_visual_review")) for doc in documents),
            "field_statuses": dict(sorted(field_statuses.items())),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
