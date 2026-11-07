"""Release (plan 4.11): confirmed marks and approved feedback, nothing else.

The ZIP holds:

* ``grade_center.csv``: Blackboard Grade Center upload format (identity columns,
  one score column, "Feedback to Learner" + "Feedback Format"). Phase 5 adds
  direct passback;
* ``marks_detail.csv``: per-question confirmed marks, percentage and letter
  (from the confirmed grading scale);
* ``feedback/<student id>.pdf``: one page per student with marks and approved feedback.

Identities are decrypted here, for the course's faculty member, and the
release is logged (GradeRelease + audit log).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.extraction.schema import ExtractedSyllabus, GradeBand
from app.models import AssessmentForm, CourseVersion, Faculty, FeedbackDraft, GradeRelease, Section
from app.services.course_versions import WorkflowError

from . import scale as scale_mod
from . import service as svc
from .identity import Person


def _split_name(p: Person) -> tuple[str, str]:
    parts = (p.name or "").split()
    if not parts:
        return "", ""
    return " ".join(parts[:-1]), parts[-1]


def _username(p: Person) -> str:
    return p.email.split("@")[0] if p.email else p.external_id


def _pdf(title: str, rows: list[tuple[str, str, str]], overall: str | None, head: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    st = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, title=title)
    flow = [Paragraph(esc(title), st["Title"]), Paragraph(esc(head), st["Heading2"]), Spacer(1, 8)]
    if overall:
        flow += [Paragraph(esc(overall), st["BodyText"]), Spacer(1, 8)]
    data = [["Question", "Marks", "Feedback"]] + [[q, m, Paragraph(esc(f), st["BodyText"])] for q, m, f in rows]
    flow.append(Table(data, colWidths=[2.5 * cm, 2.5 * cm, 12 * cm], repeatRows=1))
    doc.build(flow)
    return buf.getvalue()


def release(db: Session, me: Faculty, form: AssessmentForm, section: Section) -> tuple[str, bytes]:
    problems = svc.blockers(db, form, section)
    if problems:
        raise WorkflowError("Can't release yet: " + " ".join(problems), 409, {"blockers": problems})
    cv = db.get(CourseVersion, form.course_version_id)
    assert cv is not None
    code = ExtractedSyllabus.model_validate(cv.record).course.code or "Course"
    bands = [GradeBand(letter=g.letter, min_pct=g.min_pct, max_pct=g.max_pct, points=g.points)
             for g in svc.confirmed_scale(db, form.course_version_id)]
    subs = svc.section_submissions(db, form, section)
    people = svc.reveal(db, me, section, why="release")
    fis = sorted(form.items, key=lambda f: f.position)
    mx = sum(fi.points for fi in fis)
    col = f"{form.assessment_name} {form.version_label} [Total Pts: {mx:g} Score]"

    gc, detail = io.StringIO(), io.StringIO()
    g = csv.writer(gc, quoting=csv.QUOTE_ALL)
    g.writerow(["Last Name", "First Name", "Username", "Student ID", col, "Feedback to Learner", "Feedback Format"])
    d = csv.writer(detail)
    d.writerow(["Student ID", "Name", *[f"Q{fi.position} (/{fi.points:g})" for fi in fis], "Total", "Percent", "Letter"])
    zbuf = io.BytesIO()
    marks: dict[str, float] = {}
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in subs:
            p = people[sub.student_id]
            cells = {sc.item_id: sc for sc in sub.scores}
            pts = [cells[fi.item_id].confirmed_points for fi in fis]
            if any(x is None for x in pts):  # blockers() already refuses this; never write an unconfirmed mark
                raise WorkflowError("An unconfirmed mark reached the release; nothing was released.", 500)
            total = round(sum(x or 0 for x in pts), 2)
            pct = 100 * total / mx if mx else 0.0
            letter = scale_mod.letter_for(pct, bands) or ""
            fbs = db.scalars(select(FeedbackDraft).where(FeedbackDraft.submission_id == sub.id,
                                                         FeedbackDraft.status == "approved")).all()
            per_item = {f.item_id: f.text for f in fbs if f.item_id is not None}
            overall = next((f.text for f in fbs if f.item_id is None), None)
            first, last = _split_name(p)
            g.writerow([last, first, _username(p), p.external_id, f"{total:g}", overall or "", "PLAIN_TEXT"])
            d.writerow([p.external_id, p.name or "", *[f"{x:g}" for x in pts if x is not None], f"{total:g}",
                        f"{pct:.1f}", letter])
            rows = [(f"Q{fi.position}", f"{cells[fi.item_id].confirmed_points:g} / {fi.points:g}",
                     per_item.get(fi.item_id, "")) for fi in fis]
            head = f"{p.name or p.external_id}: {total:g} / {mx:g} ({pct:.0f}%{', ' + letter if letter else ''})"
            safe = re.sub(r"[^A-Za-z0-9_-]+", "", p.external_id) or sub.student.pseudonym
            z.writestr(f"feedback/{safe}.pdf", _pdf(f"{code} · {form.assessment_name} {form.version_label}", rows,
                                                    overall, head))
            marks[sub.student.pseudonym] = total
        z.writestr("grade_center.csv", gc.getvalue())
        z.writestr("marks_detail.csv", detail.getvalue())
    db.add(GradeRelease(form_id=form.id, section_id=section.id, channel="csv", n_students=len(subs), marks=marks,
                        by_id=me.id))
    record(db, me, "grades_released", {"form_id": form.id, "section_id": section.id, "students": len(subs)})
    name = re.sub(r"[^A-Za-z0-9_-]+", "", f"{code}_{form.assessment_name}_{form.version_label}_{section.label}_grades")
    return f"{name}.zip", zbuf.getvalue()
