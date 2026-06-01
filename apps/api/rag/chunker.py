"""Markdown chunker for methodology.md.

Splits the document by `## category` and `### section` headings.
Each chunk corresponds to one `###` subsection (the smallest meaningful unit
of the methodology), tagged with its parent `##` category.

Sections whose category is in MANDATORY_CATEGORIES are *not* emitted — those
stay in the system prompt verbatim (they're the must-always-be-present
hard rules + self-check checklist). This is so RAG never accidentally
drops the non-negotiable constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MANDATORY_CATEGORIES = {"二、硬规则", "六、生成时的自检清单"}


@dataclass
class Chunk:
    category: str
    section: str
    content: str

    def for_embedding(self) -> str:
        # Prepend the heading so embedding picks up topical signal.
        return f"[{self.category} / {self.section}]\n{self.content}".strip()


_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
# Drop trailing parenthetical hints in headings:
#   "二、硬规则（必须 100% 遵守…）" -> "二、硬规则"
# We strip both full-width and half-width parens so the heading reduces to its
# canonical short form, which is what MANDATORY_CATEGORIES matches against.
_PAREN_TAIL = re.compile(r"[（(].*?[）)]\s*$")


def _strip_heading(text: str) -> str:
    text = text.strip()
    while True:
        new = _PAREN_TAIL.sub("", text).strip()
        if new == text:
            return new
        text = new


def parse_methodology(markdown: str) -> list[Chunk]:
    """Walk the markdown line-by-line, accumulate ### subsections under ## categories.

    Returns chunks for non-mandatory categories only.
    """
    chunks: list[Chunk] = []
    current_category: str | None = None
    current_section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current_category is None or current_section is None:
            return
        if current_category in MANDATORY_CATEGORIES:
            return
        content = "\n".join(buffer).strip()
        if not content:
            return
        chunks.append(Chunk(category=current_category, section=current_section, content=content))

    for line in markdown.splitlines():
        m2 = _H2.match(line)
        if m2:
            flush()
            current_category = _strip_heading(m2.group(1))
            current_section = None
            buffer = []
            continue
        m3 = _H3.match(line)
        if m3:
            flush()
            current_section = _strip_heading(m3.group(1))
            buffer = []
            continue
        buffer.append(line)

    flush()
    return chunks


def load_chunks(methodology_path: Path | str) -> list[Chunk]:
    return parse_methodology(Path(methodology_path).read_text(encoding="utf-8"))


def extract_mandatory(markdown: str) -> str:
    """Return the verbatim text of mandatory `##` sections, joined.

    Used by the system prompt builder to guarantee hard rules + self-check
    are always present, regardless of RAG state.
    """
    sections: list[str] = []
    current_category: str | None = None
    current_keep = False
    buffer: list[str] = []

    def flush() -> None:
        if current_keep and buffer:
            sections.append("\n".join(buffer).rstrip())

    for line in markdown.splitlines():
        m2 = _H2.match(line)
        if m2:
            flush()
            current_category = _strip_heading(m2.group(1))
            current_keep = current_category in MANDATORY_CATEGORIES
            buffer = [line] if current_keep else []
            continue
        if current_keep:
            buffer.append(line)

    flush()
    return "\n\n".join(sections).strip()
