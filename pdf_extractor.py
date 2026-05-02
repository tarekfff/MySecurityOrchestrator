"""
Extract structured sections from the PDF using pdfplumber (pure Python, no DLLs).

Strategy:
  - Group characters into lines by y-position.
  - Estimate the dominant (body) font size per page via mode.
  - Lines whose max font size is >= 1.15x the body size are treated as headings.
  - Regex patterns catch chapter / numbered-section headings regardless of size.
  - Body text is accumulated under the nearest heading into Section objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Iterator

import pdfplumber


@dataclass
class Section:
    heading: str
    content: str
    page_start: int
    page_end: int
    level: int  # 1 = chapter, 2 = section, 3 = sub-section


# ── Heading patterns (used independently of font size) ────────────────────────

_CHAPTER_RE = re.compile(
    r"^(chapter\s+\d+|part\s+[ivxlcdm\d]+)[:\s]",
    re.IGNORECASE,
)
_SECTION_NUM_RE = re.compile(r"^\d+\.\d+\s")


def _heading_level_from_text(text: str) -> int | None:
    """Return level purely from text pattern (ignores font size)."""
    t = text.strip()
    if _CHAPTER_RE.match(t):
        return 1
    if _SECTION_NUM_RE.match(t):
        return 2
    return None


# ── Per-page line builder ─────────────────────────────────────────────────────

_Y_TOLERANCE = 3  # pts — characters within this band are on the same line


def _page_to_lines(page: pdfplumber.page.Page) -> list[dict]:
    """
    Return a list of line dicts:
      {"text": str, "max_size": float, "y": float}

    Characters are grouped by their rounded y0 position.
    """
    chars = page.chars
    if not chars:
        return []

    # Sort by y then x
    chars_sorted = sorted(chars, key=lambda c: (round(c["y0"] / _Y_TOLERANCE), c["x0"]))

    lines: list[dict] = []
    for _, group in groupby(chars_sorted, key=lambda c: round(c["y0"] / _Y_TOLERANCE)):
        span = list(group)
        text = "".join(c["text"] for c in span).strip()
        if not text:
            continue
        max_size = max(c["size"] for c in span if c.get("size"))
        y = span[0]["y0"]
        lines.append({"text": text, "max_size": max_size, "y": y})

    return lines


def _body_font_size(lines: list[dict]) -> float:
    sizes = [round(ln["max_size"], 1) for ln in lines if ln["max_size"] > 4]
    if not sizes:
        return 10.0
    return max(set(sizes), key=sizes.count)


def _classify_line(line: dict, body_size: float) -> int | None:
    """Return heading level (1/2/3) or None for body text."""
    text = line["text"].strip()
    if not text or len(text) > 250:
        return None

    # Text-pattern headings (reliable regardless of size)
    level = _heading_level_from_text(text)
    if level is not None:
        return level

    # Font-size-based headings
    size_ratio = line["max_size"] / body_size if body_size else 1.0
    if size_ratio >= 1.35:
        return 1
    if size_ratio >= 1.18:
        return 2
    if size_ratio >= 1.08:
        return 3

    return None


# ── Main extractor ────────────────────────────────────────────────────────────

def extract_sections(pdf_path: str | Path) -> list[Section]:
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    raw_blocks: list[dict] = []  # {level: int|None, text: str, page: int}

    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            lines = _page_to_lines(page)
            body_size = _body_font_size(lines)
            for line in lines:
                level = _classify_line(line, body_size)
                raw_blocks.append({"level": level, "text": line["text"], "page": page_num})

    return _assemble_sections(raw_blocks)


def _assemble_sections(raw_blocks: list[dict]) -> list[Section]:
    sections: list[Section] = []
    current_heading = "Introduction"
    current_level = 1
    current_page_start = 1
    current_page = 1
    body_lines: list[str] = []

    def flush():
        content = " ".join(body_lines).strip()
        if content:
            sections.append(
                Section(
                    heading=current_heading,
                    content=content,
                    page_start=current_page_start,
                    page_end=current_page,
                    level=current_level,
                )
            )

    for block in raw_blocks:
        current_page = block["page"]
        if block["level"] is not None:
            flush()
            body_lines = []
            current_heading = block["text"]
            current_level = block["level"]
            current_page_start = block["page"]
        else:
            body_lines.append(block["text"])

    flush()
    return sections


def iter_sections(pdf_path: str | Path) -> Iterator[Section]:
    yield from extract_sections(pdf_path)
