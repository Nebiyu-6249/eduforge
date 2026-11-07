"""Assessment Builder workflow (plan 3.1–3.6, 3.10).

Same faculty-in-the-loop invariants as items: forms start as drafts, only an
approved form exports, editing an approved form returns it to draft.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drafts import export as item_export
from app.extraction.schema import ExtractedSyllabus
from app.models import (
    AssessmentForm,
    CourseVersion,
    Export,
    Faculty,
    FormItem,
    Item,
    ItemUsage,
    SharedBankItem,
    utcnow,
)
from app.services.course_versions import WorkflowError

from . import assemble, blueprint, qti

LABELS = "ABCDEFGH"


def _owner(cv: CourseVersion, me: Faculty) -> None:
    if cv.faculty_id != me.id:
        raise WorkflowError("Not your course version.", 404)


def _rec(cv: CourseVersion) -> ExtractedSyllabus:
    return ExtractedSyllabus.model_validate(cv.record)


# --------------------------------------------------------------------------- #
# Item pool
# --------------------------------------------------------------------------- #

def pool(db: Session, cv: CourseVersion, me: Faculty) -> list[Item]:
    """Approved items this faculty member may use for this course: their own from
    every version of the course, plus colleagues' items shared to the course bank (3.10)."""
    if cv.course_id is None:
        return []
    mine = db.scalars(select(Item).join(CourseVersion, Item.course_version_id == CourseVersion.id).where(
        CourseVersion.course_id == cv.course_id, CourseVersion.faculty_id == me.id, Item.status == "approved")).all()
    shared = db.scalars(select(Item).join(SharedBankItem, SharedBankItem.item_id == Item.id).where(
        SharedBankItem.course_id == cv.course_id, Item.status == "approved")).all() if is_bank_member(db, cv, me) else []
    seen: dict[int, Item] = {i.id: i for i in mine}
    for i in shared:
        seen.setdefault(i.id, i)
    return list(seen.values())


def is_bank_member(db: Session, cv: CourseVersion, me: Faculty) -> bool:
    """Faculty who hold a locked version of the course share its bank (13.B pending:
    membership by teaching the course, sharing opt-in per item)."""
    if cv.course_id is None:
        return False
    return db.scalar(select(CourseVersion.id).where(
        CourseVersion.course_id == cv.course_id, CourseVersion.faculty_id == me.id,
        CourseVersion.status.in_(("locked", "superseded")))) is not None


def recently_used(db: Session, cv: CourseVersion, n_terms: int) -> set[int]:
    """Items that went out in an exported form in the last n_terms terms (3.5)."""
    if n_terms <= 0:
        return set()
    rows = db.execute(select(ItemUsage.item_id, ItemUsage.term).order_by(ItemUsage.used_at.desc())).all()
    terms: list[str | None] = []
    out: set[int] = set()
    for item_id, term in rows:
        if term not in terms:
            terms.append(term)
        if terms.index(term) < n_terms:
            out.add(item_id)
    return out


# --------------------------------------------------------------------------- #
# Blueprint + build
# --------------------------------------------------------------------------- #

def rows(cv: CourseVersion) -> list[dict]:
    return blueprint.assessment_rows(_rec(cv))


def default_blueprint(cv: CourseVersion, me: Faculty, name: str, week: int | None) -> dict:
    _owner(cv, me)
    try:
        return blueprint.derive(_rec(cv), name, week)
    except ValueError as e:
        raise WorkflowError(str(e), 422) from e


def build(db: Session, cv: CourseVersion, me: Faculty, bp: dict, versions: int = 1, sections: list[str] | None = None,
          allow_reuse: bool = False, allow_overlap: bool = False) -> list[AssessmentForm]:
    """Assemble `versions` parallel forms (3.2/3.3). Forms after the first avoid
    the items already used in earlier ones unless allow_overlap."""
    _owner(cv, me)
    if cv.status != "locked":
        raise WorkflowError("Build forms from the locked working version.", 409)
    if not 1 <= versions <= len(LABELS):
        raise WorkflowError(f"Build 1–{len(LABELS)} versions at a time.", 422)
    items = pool(db, cv, me)
    by_id = {i.id: i for i in items}
    used = recently_used(db, cv, int(bp.get("avoid_used_in_last_terms", 2)))
    taken: set[int] = set()
    forms = []
    for v in range(versions):
        built = assemble.assemble(bp, items, exclude=set() if allow_overlap else taken, recently_used=used,
                                  allow_reuse=allow_reuse)
        form = AssessmentForm(course_version_id=cv.id, assessment_name=bp.get("assessment", "Assessment"),
                              version_label=LABELS[v], section=(sections[v] if sections and v < len(sections) else None),
                              status="draft", blueprint=bp, gaps=built.gaps + [{"warning": w} for w in built.warnings],
                              created_by_id=me.id)
        db.add(form)
        db.flush()
        for pos, iid in enumerate(built.item_ids, 1):
            form.items.append(FormItem(item_id=iid, position=pos, points=built.points[iid],
                                       option_order=assemble.shuffle_options(by_id[iid], form.id)))
        taken |= set(built.item_ids)
        forms.append(form)
    db.flush()
    return forms


def coverage_report(form: AssessmentForm) -> dict:
    """How the form meets its blueprint: CLO counts, types, weeks, minutes, points."""
    from collections import Counter

    bp = form.blueprint
    items = [fi.item for fi in form.items]
    total = sum(int(n) for n in (bp.get("types") or {}).values())
    clo = Counter(c for it in items for c in it.clo_ids)
    types = Counter(it.type for it in items)
    return {
        "items": len(items), "target_items": total,
        "types": {t: {"have": types.get(t, 0), "want": int(n)} for t, n in (bp.get("types") or {}).items()},
        "clos": {c: {"have": clo.get(int(c), 0), "want": round(float(s) * total, 1)}
                 for c, s in (bp.get("clo_shares") or {}).items()},
        "minutes": sum(blueprint.MINUTES_PER_ITEM.get(it.type, 2) for it in items), "minutes_cap": bp.get("minutes"),
        "points": sum(fi.points for fi in form.items),
        "outside_weeks": [it.id for it in items if it.week_no and bp.get("weeks") and it.week_no not in bp["weeks"]],
        "meets_blueprint": not form.gaps or all("warning" in g for g in form.gaps),
    }


# --------------------------------------------------------------------------- #
# Form review (3.4)
# --------------------------------------------------------------------------- #

def _editable(form: AssessmentForm, me: Faculty) -> None:
    if form.created_by_id != me.id:
        raise WorkflowError("Not your form.", 404)
    if form.status == "approved":  # an edit returns the form to draft (same rule as items)
        form.status, form.approved_by_id, form.approved_at = "draft", None, None


def reorder(db: Session, form: AssessmentForm, me: Faculty, item_ids: list[int]) -> AssessmentForm:
    _editable(form, me)
    current = {fi.item_id: fi for fi in form.items}
    if sorted(item_ids) != sorted(current):
        raise WorkflowError("Reorder must list exactly the form's items.", 422)
    for pos, iid in enumerate(item_ids, 1):
        current[iid].position = pos
    db.flush()
    return form


def set_points(db: Session, form: AssessmentForm, me: Faculty, item_id: int, points: float) -> AssessmentForm:
    _editable(form, me)
    fi = next((f for f in form.items if f.item_id == item_id), None)
    if fi is None or points < 0:
        raise WorkflowError("No such item on the form, or negative points.", 422)
    fi.points = points
    db.flush()
    return form


def swap(db: Session, cv: CourseVersion, form: AssessmentForm, me: Faculty, out_id: int, in_id: int) -> AssessmentForm:
    _editable(form, me)
    fi = next((f for f in form.items if f.item_id == out_id), None)
    allowed = {i.id: i for i in pool(db, cv, me)}
    if fi is None or in_id not in allowed:
        raise WorkflowError("Swap needs an item on the form and an approved item from your bank.", 422)
    if any(f.item_id == in_id for f in form.items):
        raise WorkflowError("That item is already on the form.", 409)
    pos, pts = fi.position, fi.points
    form.items.remove(fi)
    db.flush()
    form.items.append(FormItem(item_id=in_id, position=pos, points=pts,
                               option_order=assemble.shuffle_options(allowed[in_id], form.id)))
    db.flush()
    return form


def approve(db: Session, form: AssessmentForm, me: Faculty) -> AssessmentForm:
    if form.created_by_id != me.id:
        raise WorkflowError("Not your form.", 404)
    if not form.items:
        raise WorkflowError("An empty form can't be approved.", 409)
    bad = [fi.item_id for fi in form.items if fi.item.status != "approved"]
    if bad:
        raise WorkflowError(f"Items {bad} are no longer approved (e.g. their CLO changed); swap them first.", 409)
    form.status, form.approved_by_id, form.approved_at = "approved", me.id, utcnow()
    db.flush()
    return form


# --------------------------------------------------------------------------- #
# Export + usage history (3.5, 3.6)
# --------------------------------------------------------------------------- #

def export_form(db: Session, cv: CourseVersion, form: AssessmentForm, me: Faculty, fmt: str,
                include_key: bool) -> tuple[bytes, str, str]:
    if form.created_by_id != me.id:
        raise WorkflowError("Not your form.", 404)
    if form.status != "approved":
        raise WorkflowError("Only an approved form can be exported.", 409)
    rec = _rec(cv)
    code = (rec.course.code or "course").replace(" ", "")
    import re

    name = re.sub(r"[^A-Za-z0-9_-]+", "", f"{code}_{form.assessment_name.replace(' ', '')}_{form.version_label}")
    ordered = sorted(form.items, key=lambda f: f.position)
    if fmt == "qti":
        data = qti.package(f"{rec.course.code} {form.assessment_name} {form.version_label}",
                           [(fi.item, fi.points, fi.option_order) for fi in ordered], as_test=True)
        out = (data, name + "_qti.zip", "application/zip")
    else:
        blocks = _form_blocks(rec, form, ordered, include_key)
        if fmt == "docx":
            out = (item_export.to_docx(blocks), name + ".docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif fmt == "pdf":
            out = (item_export.to_pdf(blocks), name + ".pdf", "application/pdf")
        else:
            raise WorkflowError(f"Unknown format '{fmt}'.", 422)
    for fi in ordered:  # usage history (3.5): exposure per term and section
        db.add(ItemUsage(item_id=fi.item_id, form_id=form.id, term=cv.term, section=form.section))
    db.add(Export(course_version_id=cv.id, format=fmt, item_ids=[fi.item_id for fi in ordered],
                  include_answer_key=include_key, by_id=me.id))
    db.flush()
    return out


def _relabel(it: Item, order: list[str] | None) -> tuple[list[dict], dict[str, str]]:
    """MCQ options in this version's order, relabelled A, B, C…; maps stored label -> shown label."""
    opts = {o["label"]: o["text"] for o in it.body_json.get("options", [])}
    order = order or list(opts)
    shown = {lbl: LABELS[i] for i, lbl in enumerate(order)}
    return [{"label": shown[lbl], "text": opts[lbl]} for lbl in order], shown


def _form_blocks(rec: ExtractedSyllabus, form: AssessmentForm, ordered: list[FormItem], include_key: bool):
    bp = form.blueprint
    total = sum(fi.points for fi in ordered)
    blocks: list[tuple] = [
        ("h1", f"{rec.course.code} {rec.course.title} — {form.assessment_name}"),
        ("p", f"{rec.offering.term or ''} · Version {form.version_label}"
              + (f" · Section {form.section}" if form.section else "")
              + (f" · {bp.get('minutes')} minutes" if bp.get("minutes") else "") + f" · {total:g} points"),
        ("small", "Assessment material: handle under the AURAK Honor Code."),
    ]
    key: list[tuple] = []
    for n, fi in enumerate(ordered, 1):
        it = fi.item
        if it.type == "mcq":
            opts, shown = _relabel(it, fi.option_order)
            blocks.append(("p", f"{n}. ({fi.points:g} pts) {it.body_json['stem']}"))
            blocks.append(("bullets", [f"{o['label']}. {o['text']}" for o in opts]))
            corr = (it.answer_key_json or {}).get("correct", "")
            key.append(("p", f"{n}. {shown.get(corr, '?')} — {(it.answer_key_json or {}).get('why_correct', '')}"))
        else:
            body = item_export._body_blocks(it, n)
            body = [b for b in body if b[0] != "small" or not str(b[1]).startswith("CLO ")]  # no tags on student copy
            if body and body[0][0] in {"p", "h3"}:
                body[0] = (body[0][0], body[0][1].replace(f"{n}. ", f"{n}. ({fi.points:g} pts) ", 1))
            blocks += body
            key += item_export._key_blocks(it, n)
    if include_key and key:
        blocks += [("pagebreak", None), ("h1", f"Answer key — version {form.version_label}"), *key]
    return blocks


# --------------------------------------------------------------------------- #
# Shared bank (3.10)
# --------------------------------------------------------------------------- #

def share(db: Session, item: Item, me: Faculty, on: bool) -> None:
    cv = item.course_version
    if cv.faculty_id != me.id:
        raise WorkflowError("Only your own items can be shared.", 404)
    if item.status != "approved":
        raise WorkflowError("Only approved items can be shared.", 409)
    if cv.course_id is None:
        raise WorkflowError("The course version isn't locked.", 409)
    existing = db.scalar(select(SharedBankItem).where(SharedBankItem.item_id == item.id))
    if on and existing is None:
        db.add(SharedBankItem(course_id=cv.course_id, item_id=item.id, shared_by_id=me.id))
    elif not on and existing is not None:
        db.delete(existing)
    db.flush()


def shared_bank(db: Session, cv: CourseVersion, me: Faculty) -> list[tuple[Item, SharedBankItem]]:
    _owner(cv, me)
    if not is_bank_member(db, cv, me):
        raise WorkflowError("Lock a version of this course to see its shared bank.", 403)
    return list(db.execute(select(Item, SharedBankItem).join(SharedBankItem, SharedBankItem.item_id == Item.id)
                           .where(SharedBankItem.course_id == cv.course_id, Item.status == "approved")).tuples())
