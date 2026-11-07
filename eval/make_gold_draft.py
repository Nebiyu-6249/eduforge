"""Write a gold DRAFT for a real syllabus (IMPLEMENTATION_PLAN 0.7), for the team to correct.

    cd backend
    uv run python ../eval/make_gold_draft.py "../fixtures/syllabi/CSCI 372 Course Syllabus - X.pdf"

The draft is the current extractor's output in the gold format, with
"status": "draft". It is NOT gold: a person must check every value against
the document, fix what's wrong, add the known issues, and only then set
"status": "verified". The harness skips drafts, because scoring the
extractor against its own output would always say 100%.

Output goes to fixtures/gold/ (git-ignored, like the syllabi: it can contain
faculty names).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.extraction.pipeline import extract


def main(path: str) -> None:
    src = Path(path)
    rec = extract(src.name, src.read_bytes()).model_dump(mode="json")
    gold = {
        "file": src.name,
        "status": "draft",
        "_instructions": "Check every value against the document; fix errors; list known issues; then set status to verified.",
        "course": {k: rec["course"][k] for k in ("code", "title", "credit_hours", "prerequisites")},
        "offering": {"term": rec["offering"]["term"]},
        "clos": rec["clos"],
        "weights": rec["weights"],
        "clo_matrix": rec["clo_matrix"],
        "weekly": [{"week_no": w["week_no"], "topics": w["topics"], "readings": w["readings"],
                    "assessments": [{"name": a["name"], "weight_pct": a["weight_pct"]} for a in w["assessments"]],
                    "clo_numbers": w["clo_numbers"]} for w in rec["weekly"]],
        "programs": rec["programs"],
        "issues": [],
    }
    out_dir = ROOT / "fixtures" / "gold"
    out_dir.mkdir(parents=True, exist_ok=True)
    code = (rec["course"]["code"] or src.stem).replace(" ", "")
    out = out_dir / f"{code}.json"
    if out.exists():
        sys.exit(f"{out} already exists; not overwriting (it may hold hand corrections).")
    out.write_text(json.dumps(gold, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out} — a DRAFT. Check it by hand before setting status to verified.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
