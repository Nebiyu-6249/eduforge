"""Format-neutral intermediate document: an ordered list of paragraphs and tables.

DOCX and PDF readers both emit this; the template mapper consumes it. Keeping
the mapper format-agnostic means AURAK template knowledge lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Para:
    text: str
    page: int | None = None
    is_heading: bool = False  # True when the source styled it as a heading


@dataclass
class Table:
    rows: list[list[str]]
    page: int | None = None  # page the table starts on
    notes: list[str] = field(default_factory=list)
    # PDF only: the page each row is on (a stitched table spans pages).
    row_pages: list[int] | None = None


Block = Para | Table
