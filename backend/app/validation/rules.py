"""Validator rules V1–V13 (HANDOFF §8.4, plan 4.4) plus EX (parser notes).

Every rule only *flags*; nothing is auto-fixed (D6). Faculty settle each
flag before locking. Each flag has a stable ``key`` so that a faculty
resolution survives re-validation after unrelated edits.

Severity:
  error   - a contradiction inside the syllabus; blocks locking until settled
  warning - likely problem; blocks locking until acknowledged
  info    - worth a look; does not block
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from app.extraction.normalize import IN_CLASS_CATEGORIES, canonical_name, category_of
from app.extraction.schema import ExtractedSyllabus
from app.llm.gateway import LLMError, LLMGateway
from app.llm.prompts import V11_ON_TOPIC, OnTopicVerdict

from .matching import Matching, match_all

Severity = Literal["error", "warning", "info"]

RULE_TITLES = {
    "V1": "Weights sum to 100%",
    "V2": "Schedule weights match the weight table",
    "V3": "Assessments appear in both the schedule and the weight table",
    "V4": "Assessment names are unique",
    "V5": "CLO matrix agrees with the schedule",
    "V6": "Every assessment has a CLO; every CLO is assessed",
    "V7": "PLO/ABET 'addressed' agrees with the CLO→PLO mapping",
    "V8": "Assessments don't come before the CLO's topic is taught",
    "V9": "In-class assessments fall on class meeting days",
    "V10": "No leftover template text",
    "V11": "Description and additional info are about this course",
    "V12": "Required fields are present",
    "V13": "Grading scale is contiguous and covers 0–100",
    "EX": "Extraction problem",
}


@dataclass
class Flag:
    rule_id: str
    severity: Severity
    message: str
    key: str
    evidence: list[str] = field(default_factory=list)  # JSON Pointers into the record
    # Plan 1.13 "faculty choose a value": one-click fixes, each a label plus the
    # JSON-Patch ops it applies (logged as ordinary edits).
    choices: list[dict] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return f"{self.rule_id}:{self.key}"


def _fmt(nums) -> str:
    return "{" + ", ".join(str(n) for n in sorted(nums)) + "}"


def _pct(v: float | None) -> str:
    return "—" if v is None else (f"{v:g}%")


def _sched_ptr(ref: tuple[int, int]) -> str:
    return f"/weekly/{ref[0]}/assessments/{ref[1]}"


def _sched_label(rec: ExtractedSyllabus, ref: tuple[int, int]) -> str:
    w = rec.weekly[ref[0]]
    return f"'{w.assessments[ref[1]].name}' (week {w.week_no})"


# --------------------------------------------------------------------------- #
# V1–V6: assessments
# --------------------------------------------------------------------------- #

def v1_weights_sum(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    if not rec.weights:
        return []
    out = []
    missing = [i for i, w in enumerate(rec.weights) if w.weight_pct is None]
    for i in missing:
        out.append(Flag("V1", "error", f"Weight-table entry '{rec.weights[i].name}' has no weight.",
                        key=f"missing:{canonical_name(rec.weights[i].name)}", evidence=[f"/weights/{i}"]))
    total = sum(w.weight_pct or 0 for w in rec.weights)
    if not math.isclose(total, 100, abs_tol=0.01):
        out.append(Flag("V1", "error", f"Weight-table weights sum to {total:g}%, not 100%.",
                        key="sum", evidence=["/weights"]))
    return out


def v2_weights_match(rec: ExtractedSyllabus, m: Matching) -> list[Flag]:
    out = []
    for i, w in enumerate(rec.weights):
        match = m.weight_to_sched[i]
        if not match.sched or w.weight_pct is None:
            continue
        items = [rec.weekly[a].assessments[b] for a, b in match.sched]
        if all(it.weight_pct is None for it in items):
            continue
        total = sum(it.weight_pct or 0 for it in items)
        if math.isclose(total, w.weight_pct, abs_tol=0.01):
            continue
        listed = ", ".join(f"{_sched_label(rec, r)} {_pct(rec.weekly[r[0]].assessments[r[1]].weight_pct)}"
                           for r in match.sched)
        if match.by_category or len(items) > 1:
            msg = (f"Weight table gives '{w.name}' {_pct(w.weight_pct)}, but the schedule's matching items "
                   f"add up to {total:g}%: {listed}.")
        else:
            msg = f"Weight table gives '{w.name}' {_pct(w.weight_pct)}, but the schedule gives {listed}."
        choices = []
        if len(match.sched) == 1:  # a single schedule item: either side can be right
            (a, b), = match.sched
            sched_pct = rec.weekly[a].assessments[b].weight_pct
            choices = [
                {"label": f"Use the weight table's {_pct(w.weight_pct)}",
                 "ops": [{"op": "replace", "path": f"{_sched_ptr((a, b))}/weight_pct", "value": w.weight_pct}]},
                {"label": f"Use the schedule's {_pct(sched_pct)}",
                 "ops": [{"op": "replace", "path": f"/weights/{i}/weight_pct", "value": sched_pct}]},
            ]
        out.append(Flag("V2", "error", msg, key=canonical_name(w.name),
                        evidence=[f"/weights/{i}", *(_sched_ptr(r) for r in match.sched)], choices=choices))
    return out


def v3_presence(rec: ExtractedSyllabus, m: Matching) -> list[Flag]:
    out = []
    if rec.weekly and rec.weights:
        for i, w in enumerate(rec.weights):
            if not m.weight_to_sched[i].sched:
                out.append(Flag("V3", "error",
                                f"'{w.name}' ({_pct(w.weight_pct)}) is in the weight table but not in the weekly schedule.",
                                key=f"not_in_schedule:{canonical_name(w.name)}", evidence=[f"/weights/{i}"]))
        # Group unmatched schedule items by category so 'HW1..HW4' is one flag.
        groups: dict[str, list[tuple[int, int]]] = {}
        for ref in m.unmatched_sched:
            a = rec.weekly[ref[0]].assessments[ref[1]]
            groups.setdefault(category_of(a.name) or canonical_name(a.name), []).append(ref)
        for cat, refs in groups.items():
            names = ", ".join(f"{_sched_label(rec, r)} {_pct(rec.weekly[r[0]].assessments[r[1]].weight_pct)}"
                              for r in refs)
            total = sum(rec.weekly[r[0]].assessments[r[1]].weight_pct or 0 for r in refs)
            out.append(Flag("V3", "error",
                            f"The schedule lists {names} (total {total:g}%), but the weight table has no matching "
                            f"entry or category.",
                            key=f"not_in_weights:{cat}", evidence=[_sched_ptr(r) for r in refs]))
    # Matrix columns that match nothing in the weight table.
    if rec.weights:
        w_keys = {canonical_name(w.name) for w in rec.weights}
        for j, me in enumerate(rec.clo_matrix):
            if canonical_name(me.assessment) not in w_keys:
                out.append(Flag("V3", "warning",
                                f"CLO matrix column '{me.assessment}' has no matching weight-table entry.",
                                key=f"matrix_only:{canonical_name(me.assessment)}", evidence=[f"/clo_matrix/{j}"]))
    return out


def v4_unique_names(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    out = []

    def dupes(items: list[tuple[str, str, str]], where: str) -> None:
        seen: dict[str, list[tuple[str, str]]] = {}
        for name, ptr, desc in items:
            seen.setdefault(canonical_name(name), []).append((ptr, desc))
        for k, hits in seen.items():
            if len(hits) > 1:
                out.append(Flag("V4", "error",
                                f"{len(hits)} different assessments in the {where} share the name "
                                f"'{k}': " + "; ".join(d for _, d in hits) + ".",
                                key=f"{where}:{k}", evidence=[p for p, _ in hits]))

    dupes([(w.name, f"/weights/{i}", f"'{w.name}' {_pct(w.weight_pct)}") for i, w in enumerate(rec.weights)],
          "weight table")
    dupes([(a.name, _sched_ptr((wi, ai)), f"{_sched_label(rec, (wi, ai))} {_pct(a.weight_pct)}")
           for wi, ai, a in rec.scheduled_assessments()], "weekly schedule")
    dupes([(me.assessment, f"/clo_matrix/{j}", f"'{me.assessment}'") for j, me in enumerate(rec.clo_matrix)],
          "CLO matrix")
    return out


def _sched_clos(rec: ExtractedSyllabus, refs) -> set[int]:
    s: set[int] = set()
    for wi, _ in refs:
        s.update(rec.weekly[wi].clo_numbers)
    return s


def v5_matrix_vs_schedule(rec: ExtractedSyllabus, m: Matching) -> list[Flag]:
    out = []
    for j, me in enumerate(rec.clo_matrix):
        refs = m.matrix_to_sched[j].sched
        if not refs:
            continue
        sched = _sched_clos(rec, refs)
        matrix = set(me.clo_numbers)
        if not sched or not matrix:
            continue  # missing mapping on one side is V6's job
        # A row listing two assessments has one CLO list for both (CENG 401 week 5),
        # so that list is only an upper bound for each of them.
        shared = any(len(rec.weekly[wi].assessments) > 1 for wi, _ in refs)
        if shared and matrix <= sched:
            continue
        if sched != matrix:
            choices = [{"label": f"Use the schedule's CLOs {_fmt(sched)} in the matrix",
                        "ops": [{"op": "replace", "path": f"/clo_matrix/{j}/clo_numbers", "value": sorted(sched)}]}]
            if len(refs) == 1 and not shared:
                wi = refs[0][0]
                choices.append({"label": f"Use the matrix's CLOs {_fmt(matrix)} in the schedule",
                                "ops": [{"op": "replace", "path": f"/weekly/{wi}/clo_numbers",
                                         "value": sorted(matrix)}]})
            out.append(Flag("V5", "error",
                            f"'{me.assessment}': the CLO matrix maps CLOs {_fmt(matrix)}, the weekly schedule maps "
                            f"{_fmt(sched)}.",
                            key=canonical_name(me.assessment),
                            evidence=[f"/clo_matrix/{j}", *(f"/weekly/{wi}/clo_numbers" for wi, _ in refs)],
                            choices=choices))
    return out


def v6_coverage(rec: ExtractedSyllabus, m: Matching) -> list[Flag]:
    out = []
    matrix_by_key = {canonical_name(me.assessment): me for me in rec.clo_matrix}

    # Scheduled items with no CLO in the schedule's mapping column.
    unmapped_weeks: list[int] = []
    for wi, ai, a in rec.scheduled_assessments():
        if rec.weekly[wi].clo_numbers:
            continue
        me = matrix_by_key.get(canonical_name(a.name))
        tail = (f" (the CLO matrix maps it to {_fmt(me.clo_numbers)})" if me and me.clo_numbers
                else " and the CLO matrix has no CLO for it either")
        out.append(Flag("V6", "error" if not (me and me.clo_numbers) else "warning",
                        f"{_sched_label(rec, (wi, ai))} has no CLO in the schedule's mapping column{tail}.",
                        key=f"sched_no_clo:{canonical_name(a.name)}:w{rec.weekly[wi].week_no}",
                        evidence=[_sched_ptr((wi, ai)), f"/weekly/{wi}/clo_numbers"]))
        unmapped_weeks.append(rec.weekly[wi].week_no)

    # Weeks with a CLO mapping but no assessment: often a row shift.
    for wi, w in enumerate(rec.weekly):
        if w.clo_numbers and not w.assessments:
            hint = ""
            near = [n for n in unmapped_weeks if abs(n - w.week_no) <= 2]
            if near:
                hint = (f" Week(s) {', '.join(map(str, near))} nearby have an assessment with no CLOs; "
                        f"the mapping column may be shifted by a row.")
            out.append(Flag("V6", "warning",
                            f"Week {w.week_no} maps CLOs {_fmt(w.clo_numbers)} but lists no assessment.{hint}",
                            key=f"clo_no_assessment:w{w.week_no}", evidence=[f"/weekly/{wi}"]))

    # Weight-table entries with no CLO anywhere.
    for i, went in enumerate(rec.weights):
        j = m.weight_to_matrix.get(i)
        mclos = set(rec.clo_matrix[j].clo_numbers) if j is not None else set()
        sclos = _sched_clos(rec, m.weight_to_sched[i].sched)
        if not mclos and not sclos:
            out.append(Flag("V6", "error", f"'{went.name}' is not mapped to any CLO (neither matrix nor schedule).",
                            key=f"weight_no_clo:{canonical_name(went.name)}", evidence=[f"/weights/{i}"]))

    # Every CLO assessed at least once.
    assessed: set[int] = set()
    for me in rec.clo_matrix:
        assessed.update(me.clo_numbers)
    for w in rec.weekly:
        if w.assessments:
            assessed.update(w.clo_numbers)
    known = {c.number for c in rec.clos}
    for c in rec.clos:
        if c.number not in assessed and (rec.clo_matrix or rec.weekly):
            out.append(Flag("V6", "error", f"CLO {c.number} is not assessed by any assessment.",
                            key=f"clo_unassessed:{c.number}", evidence=[f"/clos/{rec.clos.index(c)}"]))
    referenced = assessed | {n for w in rec.weekly for n in w.clo_numbers}
    for n in sorted(referenced - known):
        if known:
            out.append(Flag("V6", "error", f"CLO {n} is referenced in the assessments but the syllabus lists only "
                                           f"CLOs {_fmt(known)}.", key=f"clo_unknown:{n}", evidence=["/clos"]))
    return out


# --------------------------------------------------------------------------- #
# V7: PLO / ABET
# --------------------------------------------------------------------------- #

def _tokens(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def _overlap(a: str, b: str) -> float:
    """Share of the shorter text's keywords found in the other. Programs word
    the same ABET outcome at different lengths (EAC vs CAC), so plain Jaccard
    under-rates them."""
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


def v7_plo(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    out = []
    clo_nums = {c.number for c in rec.clos}
    for pi, p in enumerate(rec.programs):
        mapped = {link.plo for link in p.clo_plo}
        addressed = set(p.abet_addressed)
        plo_nums = {x.number for x in p.plos}
        base = f"/programs/{pi}"
        if p.abet_addressed:
            for n in sorted(addressed - mapped):
                out.append(Flag("V7", "error",
                                f"{p.name}: outcome {n} is marked 'addressed', but no CLO maps to PLO {n}.",
                                key=f"{p.name}:addressed_unmapped:{n}", evidence=[f"{base}/abet_addressed", f"{base}/clo_plo"]))
            for n in sorted(mapped - addressed):
                clos = sorted({link.clo for link in p.clo_plo if link.plo == n})
                out.append(Flag("V7", "error",
                                f"{p.name}: CLO(s) {_fmt(clos)} map to PLO {n}, but outcome {n} is not marked 'addressed'.",
                                key=f"{p.name}:mapped_unaddressed:{n}", evidence=[f"{base}/abet_addressed", f"{base}/clo_plo"]))
        elif p.clo_plo:
            out.append(Flag("V7", "info", f"{p.name}: no 'outcomes addressed' table was found, so it can't be "
                                          f"cross-checked against the CLO→PLO mapping.",
                            key=f"{p.name}:no_addressed_table", evidence=[base]))
        for link in p.clo_plo:
            if clo_nums and link.clo not in clo_nums:
                out.append(Flag("V7", "error", f"{p.name}: mapping uses CLO {link.clo}, which the syllabus doesn't list.",
                                key=f"{p.name}:unknown_clo:{link.clo}", evidence=[f"{base}/clo_plo"]))
            if plo_nums and link.plo not in plo_nums:
                out.append(Flag("V7", "error", f"{p.name}: mapping uses PLO {link.plo}, which this program's PLO list "
                                               f"doesn't include.",
                                key=f"{p.name}:unknown_plo:{link.plo}", evidence=[f"{base}/clo_plo"]))
        if not p.plos:
            out.append(Flag("V7", "warning", f"{p.name}: no PLO list was found in the appendix.",
                            key=f"{p.name}:no_plos", evidence=[base]))

    # Same CLO→PLO pair, different strength across programs whose PLO wording matches.
    for i, a in enumerate(rec.programs):
        for b in rec.programs[i + 1:]:
            a_text = {x.number: x.text for x in a.plos}
            b_text = {x.number: x.text for x in b.plos}
            a_map = {(link.clo, link.plo): link.strength for link in a.clo_plo}
            for link in b.clo_plo:
                sa = a_map.get((link.clo, link.plo))
                if not sa or sa == link.strength:
                    continue
                if _overlap(a_text.get(link.plo, ""), b_text.get(link.plo, "")) < 0.6:
                    continue
                out.append(Flag("V7", "info",
                                f"CLO {link.clo}→PLO {link.plo} is {sa.capitalize()} for {a.name} but "
                                f"{link.strength.capitalize()} for {b.name}, though PLO {link.plo} has similar wording "
                                f"in both. Intentional?",
                                key=f"strength:{link.clo}:{link.plo}:{a.name}:{b.name}",
                                evidence=[f"/programs/{rec.programs.index(a)}/clo_plo",
                                          f"/programs/{rec.programs.index(b)}/clo_plo"]))
    return out


# --------------------------------------------------------------------------- #
# V8: assessed before taught (best effort)
# --------------------------------------------------------------------------- #

_STOP = {
    "students", "student", "will", "able", "with", "using", "apply", "applying", "understand", "understanding",
    "demonstrate", "describe", "explain", "analyze", "analyse", "evaluate", "identify", "concepts", "concept",
    "basic", "fundamental", "fundamentals", "principles", "methods", "techniques", "various", "different", "their",
    "this", "that", "these", "those", "from", "into", "such", "including", "introduction", "intro", "overview",
    "review", "chapter", "chapters", "course", "knowledge", "skills", "ability", "effective", "effectively",
    "appropriate", "problems", "problem", "solve", "solving", "simple", "data", "based", "within", "about", "used",
    "develop", "design", "systems", "system", "part", "continued", "cont",
}


def _clo_intro_weeks(rec: ExtractedSyllabus) -> dict[int, tuple[int, set[str]]]:
    """CLO -> (first week whose topics clearly cover it, matched tokens).

    Only returns CLOs with at least three distinctive keyword hits in some
    week's topics. Two hits was too weak on the real syllabi (CENG 401 raised
    six warnings from words like 'internet' and 'knowledge').
    """
    out: dict[int, tuple[int, set[str]]] = {}
    week_tokens = [(w.week_no, _tokens(" ".join(w.topics))) for w in rec.weekly]
    for c in rec.clos:
        ct = _tokens(c.text)
        scores = [(wk, len(ct & toks), ct & toks) for wk, toks in week_tokens]
        best = max((s for _, s, _ in scores), default=0)
        if best < 3:
            continue
        thresh = max(2, math.ceil(best / 2))
        first = min((wk, hit) for wk, s, hit in scores if s >= thresh)
        out[c.number] = first
    return out


def v8_before_taught(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    intro = _clo_intro_weeks(rec)
    if not intro:
        return []
    matrix_by_key = {canonical_name(me.assessment): set(me.clo_numbers) for me in rec.clo_matrix}
    early: dict[int, list[tuple[str, str]]] = {}  # CLO -> [(label, pointer)], one flag per CLO
    for wi, ai, a in rec.scheduled_assessments():
        due_week = a.due_week or rec.weekly[wi].week_no
        if category_of(a.name) == "final":
            continue
        clos = set(rec.weekly[wi].clo_numbers) | matrix_by_key.get(canonical_name(a.name), set())
        for c in sorted(clos):
            if c in intro and intro[c][0] > due_week:
                due = a.due_date.strftime("%d %b") if a.due_date else f"week {due_week}"
                early.setdefault(c, []).append((f"'{a.name}' (due {due})", _sched_ptr((wi, ai))))
    out = []
    numbers = [x.number for x in rec.clos]
    for c, items in sorted(early.items()):
        wk, _hits = intro[c]
        topic = "; ".join(next((w.topics for w in rec.weekly if w.week_no == wk), []))
        listed = ", ".join(label for label, _ in items)
        out.append(Flag("V8", "warning",
                        f"CLO {c}'s material seems to be taught first in week {wk} (“{topic}”), but "
                        f"{'these assessments are' if len(items) > 1 else 'this assessment is'} mapped to it earlier: "
                        f"{listed}. Best-effort check from topic keywords.",
                        key=f"clo{c}", evidence=[*(p for _, p in items), f"/clos/{numbers.index(c)}"]))
    return out


# --------------------------------------------------------------------------- #
# V9: in-class assessments on meeting days
# --------------------------------------------------------------------------- #

_DAY_NAMES = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
_WEEKDAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def v9_meeting_days(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    days = rec.meeting_days()
    if not days:
        return []
    out = []
    meet = "/".join(_DAY_NAMES[d] for d in _WEEKDAY if d in days)
    for wi, ai, a in rec.scheduled_assessments():
        if not a.due_date or category_of(a.name) not in IN_CLASS_CATEGORIES:
            continue  # finals are in the exam period; take-home work can be due any day
        wd = _WEEKDAY[a.due_date.weekday()]
        if wd not in days:
            out.append(Flag("V9", "warning",
                            f"'{a.name}' is on {_DAY_NAMES[wd]} {a.due_date.strftime('%d %b %Y')}, but the class meets "
                            f"{meet}.", key=f"{canonical_name(a.name)}:{a.due_date.isoformat()}",
                            evidence=[_sched_ptr((wi, ai)), "/offering/meetings"]))
    return out


# --------------------------------------------------------------------------- #
# V10: leftover template text
# --------------------------------------------------------------------------- #

_TEMPLATE_PATTERNS = [
    r"see\s+syllabus\s+guide",
    r"should\s+be\s+added\s+here",
    r"[\[(<]\s*insert\b",
    r"click\s+(?:or\s+tap\s+)?here\s+to\s+enter",
    r"lorem\s+ipsum",
    r"\btype\s+(?:here|text\s+here)\b",
    r"\[(?:course|instructor|faculty|name|date|title|code)[^\]]{0,30}\]",
    r"\badd\s+(?:text|details|information)\s+here\b",
]
_TEMPLATE_RE = re.compile("|".join(_TEMPLATE_PATTERNS), re.I)


def v10_template_text(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    out = []
    for section, text in rec.raw_sections.items():
        m = _TEMPLATE_RE.search(text or "")
        if m:
            s = max(0, m.start() - 40)
            snippet = text[s: m.end() + 40].replace("\n", " ")
            out.append(Flag("V10", "warning", f"'{section}' still contains template text: “…{snippet}…”",
                            key=section, evidence=[f"/raw_sections/{_ptr_escape(section)}"]))
    return out


def _ptr_escape(s: str) -> str:
    return s.replace("~", "~0").replace("/", "~1")


# --------------------------------------------------------------------------- #
# V11: description / additional info on-topic
# --------------------------------------------------------------------------- #

def _v11_heuristic(rec: ExtractedSyllabus, why: str = "no LLM configured") -> list[Flag]:
    context = " ".join([rec.course.title or "", *(c.text for c in rec.clos),
                        *(t for w in rec.weekly for t in w.topics), *(r for w in rec.weekly for r in w.readings)])
    ctx = _tokens(context)
    out = []
    for field_name, label in (("description", "Course Description"), ("additional_info", "Additional Information")):
        text = getattr(rec.course, field_name) or ""
        toks = _tokens(text)
        if len(toks) < 10 or not ctx:
            continue
        overlap = len(toks & ctx) / len(toks)
        if overlap < 0.12:
            out.append(Flag("V11", "warning",
                            f"{label} shares few terms with this course's title, CLOs and topics "
                            f"({overlap:.0%} overlap). It may have been pasted from another course. "
                            f"(Keyword heuristic; {why}.)",
                            key=field_name, evidence=[f"/course/{field_name}"]))
    return out


def v11_on_topic(rec: ExtractedSyllabus, llm: LLMGateway | None) -> list[Flag]:
    if not (rec.course.description or rec.course.additional_info):
        return []
    if llm is None or not llm.available:
        return _v11_heuristic(rec)
    try:
        v = llm.json(
            V11_ON_TOPIC, OnTopicVerdict,
            code=rec.course.code or "", title=rec.course.title or "",
            clos="\n".join(f"CLO {c.number}: {c.text}" for c in rec.clos) or "(none)",
            topics="\n".join(f"Week {w.week_no}: {'; '.join(w.topics)}" for w in rec.weekly) or "(none)",
            description=rec.course.description or "(empty)",
            additional_info=rec.course.additional_info or "(empty)",
        )
    except LLMError as e:
        # Free tiers rate-limit (429) and overload (503); say so rather than
        # implying no model is set up. Re-validating later retries the model.
        reason = "the model was rate-limited" if "429" in str(e) else "the model call failed"
        return _v11_heuristic(rec, f"{reason}, re-validate to retry")
    out = []
    other = f" It reads like {v.other_subject}." if v.other_subject else ""
    if not v.description_on_topic:
        out.append(Flag("V11", "warning", f"Course Description may not be about this course: {v.description_reason}{other}",
                        key="description", evidence=["/course/description"]))
    if not v.additional_info_on_topic:
        out.append(Flag("V11", "warning",
                        f"Additional Information may not be about this course: {v.additional_info_reason}{other}",
                        key="additional_info", evidence=["/course/additional_info"]))
    return out


# --------------------------------------------------------------------------- #
# V12: required fields
# --------------------------------------------------------------------------- #

_REQUIRED = [
    ("/course/code", "Course Code", lambda r: r.course.code),
    ("/course/title", "Course Title", lambda r: r.course.title),
    ("/course/credit_hours", "Credit Hours", lambda r: r.course.credit_hours),
    ("/course/prerequisites", "Prerequisite course(s)", lambda r: r.course.prerequisites),
    ("/course/description", "Course Description", lambda r: r.course.description),
    ("/offering/term", "Semester and Academic Year", lambda r: r.offering.term),
    ("/offering/meetings", "Class Timing(s)", lambda r: r.offering.meetings),
    ("/offering/instructor_name", "Faculty Name", lambda r: r.offering.instructor_name),
    ("/clos", "Course Learning Outcomes", lambda r: r.clos),
    ("/weights", "Assessment weight table", lambda r: r.weights),
    ("/weekly", "Weekly Course Information", lambda r: r.weekly),
    ("/programs", "Appendix (PLOs and CLO→PLO mapping)", lambda r: r.programs),
]


def v12_required(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    out = []
    for ptr, label, get in _REQUIRED:
        v = get(rec)
        if v is None or v == "" or v == []:
            extra = " If the course has none, enter 'None'." if ptr == "/course/prerequisites" else ""
            if ptr == "/offering/term" and rec.offering.term_raw:
                extra = f" The file says '{rec.offering.term_raw}', which couldn't be read as a term."
            out.append(Flag("V12", "warning", f"{label} is missing or blank.{extra}", key=ptr, evidence=[ptr]))
    # Plan 1.7: unknown date formats stay raw and are flagged.
    for wi, ai, a in rec.scheduled_assessments():
        raw = a.due_text_raw or ""
        if (raw and a.due_date is None and a.due_week is None
                and not re.search(r"\b(tba|tbd|to be (announced|determined)|in class|exam period)\b", raw, re.I)
                and re.search(r"\d", raw)):
            out.append(Flag("V12", "warning",
                            f"{_sched_label(rec, (wi, ai))}: the due date “{raw}” couldn't be read as a date or "
                            f"week. Enter the date (or the week) so date checks can run.",
                            key=f"due:{canonical_name(a.name)}:w{rec.weekly[wi].week_no}",
                            evidence=[_sched_ptr((wi, ai))]))
    return out


def v13_grading_scale(rec: ExtractedSyllabus, _m: Matching) -> list[Flag]:
    """Plan 4.4/D12: from Phase 4 letters depend on the scale. Runs only with
    grading on; the comparison with other syllabi of the term happens when the
    faculty member confirms the scale (it needs the other locked versions)."""
    from app.config import get_settings
    from app.grading.scale import problems

    if not get_settings().grading_enabled:
        return []
    return [Flag("V13", "warning", f"Grading scale: {p}", key=f"scale:{p[:80]}", evidence=["/grading_scale"])
            for p in problems(rec.grading_scale)]


def ex_notes(rec: ExtractedSyllabus) -> list[Flag]:
    return [Flag("EX", "warning", f"{n.where}: {n.message}", key=f"{i}:{n.where}:{n.message[:60]}",
                 evidence=[f"/notes/{i}"]) for i, n in enumerate(rec.notes)]


# --------------------------------------------------------------------------- #

_RULES = [v1_weights_sum, v2_weights_match, v3_presence, v4_unique_names, v5_matrix_vs_schedule,
          v6_coverage, v7_plo, v8_before_taught, v9_meeting_days, v10_template_text, v12_required,
          v13_grading_scale]


def validate(rec: ExtractedSyllabus, llm: LLMGateway | None = None, run_v11: bool = True) -> list[Flag]:
    """Run all rules. ``run_v11=False`` skips the (possibly LLM-backed) V11
    check, for re-validation after edits that don't touch the text it reads."""
    m = match_all(rec)
    flags: list[Flag] = []
    for rule in _RULES:
        flags.extend(rule(rec, m))
    if run_v11:
        flags.extend(v11_on_topic(rec, llm))
    flags.extend(ex_notes(rec))
    # De-duplicate identical fingerprints (keep first).
    seen: set[str] = set()
    uniq = []
    for f in flags:
        if f.fingerprint not in seen:
            seen.add(f.fingerprint)
            uniq.append(f)
    order = {"error": 0, "warning": 1, "info": 2}
    uniq.sort(key=lambda f: (order[f.severity], int(f.rule_id[1:]) if f.rule_id[1:].isdigit() else 99))
    return uniq
