"""Grading scale: read it from the syllabus, check it (V13), apply it (plan 4.4, D12).

AURAK syllabi print the scale as a table "Grade | Percentage Scores | Grade
Points" (e.g. ``B+ | 85-89 | 3.50``). Ranges are whole percentages, so bands
85-89 and 90-100 are contiguous. A percentage between two printed bands (89.6)
takes the lower band: rounding policy belongs to the faculty member, who
confirms the scale before any release.
"""

from __future__ import annotations

import re

from app.extraction.schema import ExtractedSyllabus, GradeBand, SourceRef

_NUM = r"(\d{1,3}(?:\.\d+)?)"
_ROW = re.compile(
    rf"^\s*([A-F][+-]?)\s*[|:]?\s*{_NUM}\s*%?\s*(?:-|–|—|to)\s*{_NUM}\s*%?\s*(?:[|:]\s*(\d(?:\.\d+)?))?\s*(?:\||$)",
    re.I)
_BELOW = re.compile(rf"^\s*([A-F][+-]?)\s*[|:]?\s*(?:below|less than|under|<)\s*{_NUM}\s*%?\s*(?:[|:]\s*(\d(?:\.\d+)?))?",
                    re.I)


def _section(rec: ExtractedSyllabus) -> str | None:
    for k, v in rec.raw_sections.items():
        if re.sub(r"[^a-z]", "", k.lower()).startswith(("gradingscale", "gradingsystem")):
            return v
    return None


def parse_scale(rec: ExtractedSyllabus) -> list[GradeBand]:
    """Bands from the Grading Scale section; also records where each came from."""
    text = _section(rec)
    if not text:
        return []
    bands: list[GradeBand] = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if m:
            lo, hi = sorted((float(m.group(2)), float(m.group(3))))
            band = GradeBand(letter=m.group(1).upper(), min_pct=lo, max_pct=hi,
                             points=float(m.group(4)) if m.group(4) else None)
        elif (m := _BELOW.match(line)):
            band = GradeBand(letter=m.group(1).upper(), min_pct=0, max_pct=float(m.group(2)) - 1,
                             points=float(m.group(3)) if m.group(3) else None)
        else:
            continue
        if any(b.letter == band.letter and b.min_pct == band.min_pct for b in bands):
            continue  # a table repeated across a page break
        rec.sources[f"/grading_scale/{len(bands)}"] = SourceRef(raw_text=line.strip())
        bands.append(band)
    return bands


def problems(bands: list[GradeBand]) -> list[str]:
    """V13: bands are contiguous, cover 0–100 and don't overlap. Empty list = fine."""
    if not bands:
        return ["No grading scale was found, so letter grades can't be computed. Enter the scale."]
    out: list[str] = []
    seen: set[str] = set()
    for b in bands:
        if b.letter in seen:
            out.append(f"Letter {b.letter} appears twice.")
        seen.add(b.letter)
        if b.min_pct > b.max_pct:
            out.append(f"{b.letter}: the range {b.min_pct:g}–{b.max_pct:g} is reversed.")
    order = sorted(bands, key=lambda b: b.min_pct, reverse=True)
    if order[0].max_pct < 100:
        out.append(f"The top band ({order[0].letter}) ends at {order[0].max_pct:g}, not 100.")
    if order[-1].min_pct > 0:
        out.append(f"The lowest band ({order[-1].letter}) starts at {order[-1].min_pct:g}, not 0.")
    for hi, lo in zip(order, order[1:], strict=False):
        if hi.min_pct <= lo.max_pct:
            out.append(f"{lo.letter} ({lo.min_pct:g}–{lo.max_pct:g}) overlaps {hi.letter} ({hi.min_pct:g}–{hi.max_pct:g}).")
        elif hi.min_pct - lo.max_pct > 1:
            out.append(f"No letter covers {lo.max_pct:g}–{hi.min_pct:g} (between {lo.letter} and {hi.letter}).")
        if hi.points is not None and lo.points is not None and hi.points < lo.points:
            out.append(f"{hi.letter} has fewer grade points than {lo.letter}.")
    return out


def letter_for(pct: float, bands: list[GradeBand]) -> str | None:
    for b in sorted(bands, key=lambda b: b.min_pct, reverse=True):
        if pct >= b.min_pct:
            return b.letter
    return None


def signature(bands: list[GradeBand]) -> tuple:
    return tuple(sorted(((b.letter, b.min_pct, b.max_pct) for b in bands), key=lambda t: -t[1]))


def describe(bands: list[GradeBand]) -> str:
    """'A 90–100, B+ 85–89, …' for messages."""
    return ", ".join(f"{b.letter} {b.min_pct:g}–{b.max_pct:g}" for b in sorted(bands, key=lambda b: -b.min_pct))
