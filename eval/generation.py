"""Offline generation eval set (IMPLEMENTATION_PLAN 2.12).

Generates N drafts per item type for a syllabus with the configured model,
runs the quality checks, and writes a review sheet (CSV) for the team to score
against a written rubric BEFORE pilot faculty see anything. Gate: ≥80% judged
acceptable internally.

    cd backend
    uv run python ../eval/generation.py "../fixtures/syllabi/CSCI 372 Course Syllabus.pdf" --per-type 5

Uses a throwaway SQLite database. Data hygiene (plan 11/14.10): with a free
hosted model, run this only on sample syllabi, never on real exam items.
The review sheet's last columns (acceptable, edit_needed, notes) are for the
team to fill in; `--score SHEET.csv` then prints the acceptance rate per type.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

RUBRIC = ("acceptable = usable after light edits (≤ ~20% changed); faithful to the CLO and week; correct key; "
          "appropriate Bloom level; no factual errors; English quality fine")


def synthetic_syllabus(name: str) -> Path:
    """Render one of the synthetic test syllabi (tests/synth) to a temp PDF, so the
    nightly CI run needs no real syllabus (those stay out of git)."""
    from tests.synth.render import to_pdf
    from tests.synth.specs import COURSES, build

    if name not in COURSES:
        raise SystemExit(f"Unknown synthetic syllabus {name}; choose from {', '.join(COURSES)}.")
    path = Path(tempfile.mkdtemp(prefix="eduforge-synth-")) / f"{name}.pdf"
    path.write_bytes(to_pdf(build(COURSES[name][0])))
    return path


def generate(path: Path, per_type: int, types: list[str], out: Path) -> float:
    from sqlalchemy.orm import sessionmaker

    from app import jobs
    from app.config import get_settings
    from app.db import Base, make_engine
    from app.drafts import service as drafts
    from app.drafts.quality import CHECK_LABELS, HARD_CHECKS
    from app.drafts.schemas import QUESTION_TYPES
    from app.models import Faculty, Item
    from app.services import course_versions as registry

    tmp = Path(tempfile.mkdtemp(prefix="eduforge-geneval-"))
    engine = make_engine(f"sqlite:///{tmp / 'eval.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = get_settings()
    s.storage_dir = tmp / "storage"
    s.worker_mode = "sync"
    jobs.session_factory = Session
    rows = []
    with Session() as db:
        me = Faculty(email="eval@example.edu", name="Eval")
        db.add(me)
        db.commit()
        cv = registry.create_from_upload(db, me, path.name, path.read_bytes())
        for f in cv.flags:  # the eval is about generation, not the syllabus
            if f.status == "open":
                f.status, f.resolution = "resolved", "accepted"
        registry.lock(db, cv, me)
        db.commit()
        clos = [c["number"] for c in cv.record["clos"]]
        for t in types:
            for i in range(per_type):
                clo = clos[i % len(clos)]
                try:
                    req = drafts.request_drafts(db, cv, me, t, [clo], [], 1, None, None, None,
                                                allow_skills_questions=t not in QUESTION_TYPES)
                    db.commit()
                except Exception as e:  # noqa: BLE001 - record and continue
                    db.rollback()
                    rows.append({"type": t, "clo": clo, "item_id": "", "error": str(e)[:300]})
                    continue
                for it in db.query(Item).filter(Item.request_id == req.id):
                    hard_ok = not any(q.check in HARD_CHECKS and q.outcome == "fail" for q in it.scores)
                    rows.append({
                        "hard_ok": hard_ok,
                        "type": t, "clo": clo, "item_id": it.id, "error": "",
                        "prompt_version": it.prompt_version, "model": it.model,
                        "checks": "; ".join(f"{CHECK_LABELS.get(q.check, q.check)}={q.outcome}" for q in it.scores),
                        "item": json.dumps({"body": it.body_json, "key": it.answer_key_json}, ensure_ascii=False),
                        "acceptable (y/n)": "", "edit_needed (none/light/heavy)": "", "notes": "",
                    })
    with out.open("w", newline="", encoding="utf-8") as fh:
        cols = ["type", "clo", "item_id", "prompt_version", "model", "checks", "item", "error",
                "acceptable (y/n)", "edit_needed (none/light/heavy)", "notes"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out}\nRubric: {RUBRIC}")
    made = [r for r in rows if r.get("item_id")]
    rate = sum(1 for r in made if r["hard_ok"]) / len(rows) if rows else 0.0
    print(f"Drafts generated: {len(made)}; generation errors: {len(rows) - len(made)}; "
          f"requests giving a draft that passes every required check: {rate:.0%}")
    return rate


def score(sheet: Path) -> int:
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with sheet.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = (r.get("acceptable (y/n)") or "").strip().lower()
            if v in {"y", "n"}:
                per[r["type"]][1] += 1
                per[r["type"]][0] += v == "y"
    if not per:
        print("No rows scored yet (fill in 'acceptable (y/n)').")
        return 1
    ok_all = n_all = 0
    for t, (ok, n) in sorted(per.items()):
        ok_all, n_all = ok_all + ok, n_all + n
        print(f"{t:<18} {ok}/{n} acceptable ({ok / n:.0%})")
    print(f"{'ALL':<18} {ok_all}/{n_all} ({ok_all / n_all:.0%})  gate 2.12 (≥80%): "
          f"{'PASS' if ok_all / n_all >= 0.8 else 'FAIL'}")
    return 0 if ok_all / n_all >= 0.8 else 2


def main() -> int:
    from app.drafts.schemas import ITEM_TYPES

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("syllabus", type=Path, nargs="?")
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--types", default=",".join(ITEM_TYPES))
    ap.add_argument("--out", type=Path, default=Path("generation_review.csv"))
    ap.add_argument("--score", type=Path, help="score a filled-in review sheet instead")
    ap.add_argument("--synthetic", help="use a synthetic test syllabus (e.g. STAT100) instead of a file")
    ap.add_argument("--min-pass", type=float, default=0.0,
                    help="exit 3 if fewer requests than this produce a draft passing every required check "
                         "(nightly regression signal; the ≥80%% gate itself needs human review)")
    a = ap.parse_args()
    if a.score:
        return score(a.score)
    if a.synthetic:
        a.syllabus = synthetic_syllabus(a.synthetic)
    if not a.syllabus:
        ap.error("give a syllabus file, --synthetic NAME, or --score SHEET.csv")
    rate = generate(a.syllabus, a.per_type, a.types.split(","), a.out)
    return 3 if rate < a.min_pass else 0


if __name__ == "__main__":
    sys.exit(main())
