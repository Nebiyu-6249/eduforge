"""Deterministic normalisers for messy syllabus cell text (HANDOFF §8.3).

All functions are pure and keep no state, so they are easy to unit-test
against the date/term/day formats seen in the AURAK samples.
"""

from __future__ import annotations

import re
from datetime import date

from .schema import ClassMeeting, ScheduledAssessment

# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

_WS = re.compile(r"\s+")


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    return _WS.sub(" ", text).strip()


def label_key(text: str | None) -> str:
    """Lowercase letters only: 'Class Timing(s):' -> 'classtimings'."""
    return re.sub(r"[^a-z]", "", (text or "").lower())


def split_lines(text: str | None) -> list[str]:
    """Split a cell into list items on newlines, bullets and semicolons."""
    if not text:
        return []
    parts = re.split(r"[\n\r;•▪●◦·]+", text)  # '·' is the bullet in CENG 401's PDF
    out = []
    for p in parts:
        p = clean(p).lstrip("-–*· ").strip()
        if p and p.lower() not in {"-", "–", "n/a", "na", "none", "nil"}:
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_pct(text: str | None) -> float | None:
    if not text:
        return None
    m = _PCT.search(text)
    if m:
        return float(m.group(1))
    t = clean(text)
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    return None


def parse_int(text: str | None) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_float(text: str | None) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


_CLO_RANGE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")


def parse_clo_list(text: str | None) -> list[int]:
    """'CLO 1, 2' / 'CLO1, CLO3' / '1,2,4' / 'CLOs 1-3' -> sorted unique ints."""
    if not text:
        return []
    t = clean(text)
    if t.lower() in {"-", "–", "n/a", "na", "none", "tba"}:
        return []
    nums: set[int] = set()
    for a, b in _CLO_RANGE.findall(t):
        lo, hi = int(a), int(b)
        if 0 < lo <= hi <= 30:
            nums.update(range(lo, hi + 1))
    t = _CLO_RANGE.sub(" ", t)
    for n in re.findall(r"\d+", t):
        v = int(n)
        if 0 < v <= 30:
            nums.add(v)
    return sorted(nums)


def is_mark(text: str | None) -> bool:
    """A matrix cell that means 'yes' (X, ✓, ✔, x, •)."""
    t = clean(text).lower()
    return t in {"x", "✓", "✔", "√", "•", "yes", "y", "*", "xx"}


def parse_strength(text: str | None):
    t = clean(text).lower()
    if not t:
        return None
    if t.startswith("h"):
        return "high"
    if t.startswith("m"):
        return "medium"
    if t.startswith("l"):
        return "low"
    if t in {"3"}:
        return "high"
    if t in {"2"}:
        return "medium"
    if t in {"1"}:
        return "low"
    return None


# --------------------------------------------------------------------------- #
# Terms
# --------------------------------------------------------------------------- #

_SEASON = re.compile(r"\b(fall|autumn|spring|summer|winter)\b", re.I)


def normalise_term(text: str | None) -> str | None:
    """'Fall Semester 2026 / AY 2026-2027' -> 'Fall 2026'.

    For Spring/Summer with only an academic-year range ('2025-2026'), the
    second year is used.
    """
    if not text:
        return None
    t = clean(text)
    sm = _SEASON.search(t)
    if not sm:
        return None
    season = sm.group(1).capitalize()
    if season == "Autumn":
        season = "Fall"
    after = t[sm.end():]
    # Explicit year right after the season wins: "Spring 2026", "Fall Semester 2026".
    m = re.match(r"\D{0,15}?(20\d{2})(?!\s*[-–/]\s*\d)", after)
    if m:
        return f"{season} {m.group(1)}"
    rng = re.search(r"(20\d{2})\s*[-–/]\s*(20\d{2}|\d{2})", t)
    if rng:
        y1 = int(rng.group(1))
        y2s = rng.group(2)
        y2 = int(y2s) if len(y2s) == 4 else 2000 + int(y2s)
        return f"{season} {y1 if season == 'Fall' else y2}"
    m = re.search(r"(20\d{2})", t)
    if m:
        return f"{season} {m.group(1)}"
    return None


def term_year(term: str | None) -> int | None:
    m = re.search(r"(20\d{2})", term or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Dates (§8.3: "10 February 2026", "12-October", "16-Nov", "23-09-2026",
#               "W4", "Due Week 10", "TBA")
# --------------------------------------------------------------------------- #

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORD = r"(?:st|nd|rd|th)?"

_RE_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b")
_RE_DAY_MON = re.compile(rf"\b(\d{{1,2}}){_ORD}[\s\-./]*(?:of\s+)?{_MON}\b\.?(?:[\s,\-./]*(\d{{4}}))?", re.I)
_RE_MON_DAY = re.compile(rf"\b{_MON}\.?[\s\-./]*(\d{{1,2}}){_ORD}\b(?:[\s,\-./]*(\d{{4}}))?", re.I)
_RE_WEEK = re.compile(r"\b(?:w|wk|week)\s*#?\s*(\d{1,2})\b", re.I)


def _mk_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_due(text: str | None, default_year: int | None) -> tuple[date | None, int | None]:
    """Return (date, week) parsed from free text. Either may be None.

    Numeric dates are read DD-MM-YYYY (the UAE convention used in the
    samples). Missing years fall back to ``default_year`` (the term's year).
    """
    if not text:
        return None, None
    t = clean(text)
    if re.search(r"\b(tba|tbd|to be announced|to be determined)\b", t, re.I):
        tba_week = _RE_WEEK.search(t)
        return None, int(tba_week.group(1)) if tba_week else None

    d: date | None = None
    y: int | None
    m = _RE_NUMERIC.search(t)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(yy) if len(yy) == 4 else 2000 + int(yy)
        d = _mk_date(y, mm, dd)
    if d is None:
        m = _RE_DAY_MON.search(t)
        if m:
            y = int(m.group(3)) if m.group(3) else default_year
            if y:
                d = _mk_date(y, _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    if d is None:
        m = _RE_MON_DAY.search(t)
        if m:
            y = int(m.group(3)) if m.group(3) else default_year
            if y:
                d = _mk_date(y, _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))

    wk_m = _RE_WEEK.search(t)
    wk = int(wk_m.group(1)) if wk_m else None
    return d, wk


# --------------------------------------------------------------------------- #
# Class meeting days
# --------------------------------------------------------------------------- #

_DAY_WORDS = [
    (r"\bmon(?:day)?s?\b", "mon"),
    (r"\btue(?:s(?:day)?)?s?\b", "tue"),
    (r"\bwed(?:nesday)?s?\b", "wed"),
    (r"\bthu(?:r(?:s(?:day)?)?)?s?\b", "thu"),
    (r"\bfri(?:day)?s?\b", "fri"),
    (r"\bsat(?:urday)?s?\b", "sat"),
    (r"\bsun(?:day)?s?\b", "sun"),
]
_COMPACT = re.compile(r"\b((?:Th|Tu|Su|Sa|M|T|W|R|F|U|S){2,5})\b")
_COMPACT_MAP = {"M": "mon", "T": "tue", "Tu": "tue", "W": "wed", "R": "thu", "Th": "thu",
                "F": "fri", "S": "sat", "Sa": "sat", "U": "sun", "Su": "sun"}
_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(text: str) -> list[str]:
    found: set[str] = set()
    low = text.lower()
    for pat, day in _DAY_WORDS:
        if re.search(pat, low):
            found.add(day)
    if not found:
        for tok in _COMPACT.findall(text):
            for piece in re.findall(r"Th|Tu|Su|Sa|M|T|W|R|F|U|S", tok):
                found.add(_COMPACT_MAP[piece])
    return [d for d in _DAY_ORDER if d in found]


_TIME = re.compile(r"\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?(?:\s*[-–to]+\s*\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?)?", re.I)


def parse_meetings(text: str | None) -> list[ClassMeeting]:
    """'Tue/Thu 3:00-4:15 PM; Tue/Thu 4:30-5:45 PM' -> two meetings."""
    if not text:
        return []
    segs = [s for s in re.split(r"[\n;]+|(?i:\bsection\s*\d+\s*[:\-]?)", text) if clean(s)]
    out: list[ClassMeeting] = []
    for s in segs:
        days = parse_days(s)
        tm = _TIME.search(s)
        if days or tm:
            out.append(ClassMeeting(days=days, time_text=clean(tm.group()) if tm else None))
    # A trailing segment with only a time inherits the previous segment's days.
    for i in range(1, len(out)):
        if not out[i].days:
            out[i].days = list(out[i - 1].days)
    return out


# --------------------------------------------------------------------------- #
# Assessment names
# --------------------------------------------------------------------------- #

_CATEGORIES: list[tuple[str, str]] = [
    ("midterm", r"mid[\s\-]?term|mid[\s\-]?exam|mid[\s\-]?semester"),
    ("final", r"\bfinal\b"),
    ("quiz", r"\bquiz|\bquizzes"),
    ("homework", r"\bhw\b|\bhw\s*\d|\bhws\b|home\s?work|assignment"),
    ("lab", r"\blabs?\b|\blab\s*\d|laborator"),
    ("project", r"\bproject"),
    ("presentation", r"presentation"),
    ("participation", r"participation|attendance"),
    ("test", r"\btests?\b"),
    ("report", r"\breports?\b"),
    ("certification", r"certif"),
    ("case_study", r"case\s*stud"),
]

IN_CLASS_CATEGORIES = {"quiz", "midterm", "test", "presentation"}


def category_of(name: str) -> str | None:
    low = name.lower()
    for cat, pat in _CATEGORIES:
        if re.search(pat, low):
            return cat
    return None


def _strip_noise(name: str) -> str:
    """Drop counts and weights: 'Quizzes (2)', 'Labs x4', 'HW (4 × 5%)' -> no digits."""
    s = re.sub(r"\([^)]*\)", " ", name)
    s = re.sub(r"\d+(?:\.\d+)?\s*%", " ", s)
    s = re.sub(r"\b[x×]\s*\d+\b|\b\d+\s*[x×]\b", " ", s, flags=re.I)
    return s


def canonical_name(name: str) -> str:
    """Key used to match the same assessment across tables.

    'Quiz #1' / 'Quiz 1' / 'quiz no. 1' -> 'quiz 1'; 'HW1' / 'Homework 1' -> 'homework 1';
    'Midterm Exam' -> 'midterm'; 'Quizzes (2)' -> 'quiz'. Unknown categories
    fall back to cleaned text.
    """
    s = _strip_noise(name)
    cat = category_of(s)
    if cat:
        return " ".join([cat, *re.findall(r"\d+", s)])
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def is_category_name(name: str) -> bool:
    """True when a weight-table entry names a whole category ('Quizzes',
    'Homework', 'Midterm'), so it should be matched against the sum of all
    scheduled instances of that category."""
    s = _strip_noise(name)
    return category_of(s) is not None and not re.search(r"\d", s)


# --------------------------------------------------------------------------- #
# Weekly-schedule assessment cell
# --------------------------------------------------------------------------- #

_NAME_STOP = re.compile(r"\(|\d+(?:\.\d+)?\s*%|\bdue\b|\s[-–—]\s|[–—:,]|\bon\b\s+\w+day", re.I)
_EMPTY_CELL = re.compile(r"^(?:-+|–|n/?a|none|nil|no (?:assessment|assignment)s?|tba)$", re.I)


_RELEASE = re.compile(r"\b(out|released?|assigned|announced|handed\s+out|kick-?off|starts?|begins?)\s*$", re.I)


def _is_detail_line(line: str) -> bool:
    s = clean(line)
    if re.match(r"^[–—\-(:]", s):
        return True
    s = re.sub(r"\(?\s*\d+(?:\.\d+)?\s*%\s*\)?", " ", s)
    s = re.sub(r"\bdue\b.*$", " ", s, flags=re.I)
    for rx in (_RE_NUMERIC, _RE_DAY_MON, _RE_MON_DAY, _RE_WEEK):
        s = rx.sub(" ", s)
    s = re.sub(r"\b(tba|tbd|weight(?:ing)?|grade|on|by|at)\b", " ", s, flags=re.I)
    return not re.search(r"[A-Za-z]{2,}", s)


def parse_assessment_cell(text: str | None, default_year: int | None) -> list[ScheduledAssessment]:
    """Parse 'Quiz #1 (10%) – Due: 10 February 2026\\nHW 2 (5%) Due Week 6'."""
    if not text:
        return []
    # A line that is only a weight, date or due note continues the previous
    # assessment: 'Assignment\n10%\nDue Week 10' is one item, not three.
    lines: list[str] = []
    for line in re.split(r"[\n\r;•]+", text):
        if not clean(line):
            continue
        if lines and _is_detail_line(line):
            lines[-1] = f"{lines[-1]} {clean(line)}"
        else:
            lines.append(clean(line))
    pieces: list[str] = []
    for line in lines:
        # Two assessments on one line separated by ',' or '/' after a weight.
        pieces.extend(re.split(r"(?<=%\))\s*[,/&]\s*(?=[A-Za-z])|(?<=%)\s*[,/&]\s*(?=[A-Za-z])", line))
    out: list[ScheduledAssessment] = []
    for raw in pieces:
        p = clean(raw)
        if not p or _EMPTY_CELL.match(p):
            continue
        m = _NAME_STOP.search(p)
        name = clean(p[: m.start()] if m else p).strip(" -–—:.,")
        if not name or not re.search(r"[A-Za-z]", name):
            continue
        rest = p[m.start():] if m else ""
        if parse_pct(p) is None and _RELEASE.search(name):
            continue  # 'Project Out' / 'HW 2 released': handed out, not assessed here
        due_date, due_week = parse_due(rest, default_year)
        # Keep the due part only: '(10%) – Due: 12-Oct' -> 'Due: 12-Oct'.
        due_raw = re.sub(r"\(\s*\d+(?:\.\d+)?\s*%\s*\)|\d+(?:\.\d+)?\s*%", " ", rest)
        out.append(ScheduledAssessment(
            name=name,
            weight_pct=parse_pct(p),
            due_text_raw=clean(due_raw).strip(" -–—:,()") or None,
            due_date=due_date,
            due_week=due_week,
        ))
    return out
