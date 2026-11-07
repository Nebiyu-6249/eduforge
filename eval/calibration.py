"""Grading calibration report (IMPLEMENTATION_PLAN 4.13, Gate 4).

Compares the tool's suggested marks with the faculty member's own marks on
every calibration set in the database (or one set, or one form), and prints
exact and within-one-level agreement, quadratic weighted kappa, mean absolute
error, leniency and an answer-length bias check, per item type.

    cd backend
    uv run python ../eval/calibration.py             # every set
    uv run python ../eval/calibration.py --set 3     # one set
    uv run python ../eval/calibration.py --json

Calibration sets are created in the app (Grading → Calibration) from a CSV of
anonymised answers plus the faculty member's marks (columns Q1… and M1…), then
scored by the normal suggestion pipeline. Exit code 1 if a proposed Gate 4
threshold is missed (within-one ≥ 90% and QWK ≥ 0.8 for open answers; 100%
for key-scored items), so a scheduled run can alert.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.grading import calibration as cal
    from app.models import CalibrationSet

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", type=int, help="one calibration set id")
    ap.add_argument("--form", type=int, help="every set of one assessment form")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        q = select(CalibrationSet).order_by(CalibrationSet.id)
        if args.set:
            q = q.where(CalibrationSet.id == args.set)
        if args.form:
            q = q.where(CalibrationSet.form_id == args.form)
        sets = db.scalars(q).all()
        if not sets:
            print("No calibration sets found.")
            return 0
        all_pairs, out = [], []
        for s in sets:
            pairs = cal.pairs_for(db, s)
            all_pairs += pairs
            out.append({"set": s.id, "form": s.form_id, "description": s.description, "report": cal.report(pairs)})
        overall = cal.report(all_pairs)
    misses = cal.gate(overall)
    if args.json:
        print(json.dumps({"sets": out, "overall": overall, "gate_misses": misses}, indent=2, default=str))
    else:
        for o in out:
            print(f"\n== Set {o['set']} (form {o['form']}) {o['description']}")
            print(cal.table(o["report"]))
        if len(out) > 1:
            print("\n== All sets")
            print(cal.table(overall))
        print("\nGate 4 (proposed): " + ("met" if not misses else "MISSED: " + "; ".join(misses)))
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
