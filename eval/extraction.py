"""Extraction evaluation harness (IMPLEMENTATION_PLAN 0.8).

Scores the extractor field by field against gold answers, per field group,
and checks that every known issue is flagged. One command prints the table:

    cd backend
    uv run python ../eval/extraction.py --synthetic      # 5 synthetic syllabi, gold from their specs
    uv run python ../eval/extraction.py                  # real files in fixtures/syllabi + gold in fixtures/gold

Gold files (plan 0.7) are JSON, one per syllabus, hand-checked by the team:

    {"file": "CSCI 372 Course Syllabus.pdf",       # file name in fixtures/syllabi
     "status": "verified",                          # "draft" files are skipped unless --include-drafts
     "course": {"code": ..., "title": ..., "credit_hours": ..., "prerequisites": ...},
     "offering": {"term": ...},
     "clos": [{"number": 1, "text": ...}],
     "weights": [{"name": ..., "weight_pct": ...}],
     "clo_matrix": [{"assessment": ..., "clo_numbers": [...]}],
     "weekly": [{"week_no": 1, "topics": [...], "readings": [...],
                 "assessments": [{"name": ..., "weight_pct": ...}], "clo_numbers": [...]}],
     "programs": [{"name": ..., "plos": [{"number": 1, "text": ...}],
                   "clo_plo": [{"clo": 1, "plo": 1, "strength": "high"}], "abet_addressed": [1, 2]}],
     "issues": [["V4", "quiz 1"]]}                  # rule id + substring of the expected flag

`make_gold_draft.py` writes a draft from the current extractor for the team
to correct by hand. A draft is NOT gold until a person has checked every value.

"Gate 1" in the plan is ≥90% of fields needing no correction on unseen
syllabi; that is the "recall" column (gold fields the extractor got right).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.extraction.normalize import canonical_name
from app.extraction.pipeline import extract
from app.validation.rules import validate

GROUPS = ["course", "offering", "clos", "weights", "clo_matrix", "weekly", "assessments", "programs"]


def norm(v):
    if isinstance(v, str):
        v = v.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
        return re.sub(r"\s+", " ", v).strip().casefold()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, list):
        return sorted(norm(x) for x in v) if all(not isinstance(x, (dict, list)) for x in v) else [norm(x) for x in v]
    return v


def atoms(rec: dict) -> dict[str, dict[str, object]]:
    """Flatten a record into {group: {field_key: value}} using natural keys, so a
    missing CLO doesn't shift every later one."""
    out: dict[str, dict[str, object]] = defaultdict(dict)
    for k in ("code", "title", "credit_hours", "prerequisites"):
        if k in rec.get("course", {}):
            out["course"][k] = rec["course"][k]
    if "term" in rec.get("offering", {}):
        out["offering"]["term"] = rec["offering"]["term"]
    for c in rec.get("clos", []):
        out["clos"][f"CLO {c['number']}"] = c["text"]
    for w in rec.get("weights", []):
        out["weights"][canonical_name(w["name"])] = w.get("weight_pct")
    for m in rec.get("clo_matrix", []):
        out["clo_matrix"][canonical_name(m["assessment"])] = m.get("clo_numbers", [])
    for wk in rec.get("weekly", []):
        n = wk["week_no"]
        out["weekly"][f"w{n}.topics"] = wk.get("topics", [])
        out["weekly"][f"w{n}.readings"] = wk.get("readings", [])
        out["weekly"][f"w{n}.clos"] = wk.get("clo_numbers", [])
        for a in wk.get("assessments", []):
            out["assessments"][f"w{n}.{canonical_name(a['name'])}.weight"] = a.get("weight_pct")
    for p in rec.get("programs", []):
        pn = norm(p["name"])
        for plo in p.get("plos", []):
            out["programs"][f"{pn}.plo{plo['number']}"] = plo["text"]
        for link in p.get("clo_plo", []):
            out["programs"][f"{pn}.clo{link['clo']}-plo{link['plo']}"] = link["strength"]
        out["programs"][f"{pn}.addressed"] = p.get("abet_addressed", [])
    return out


def score(gold: dict, pred: dict) -> dict[str, tuple[int, int, int]]:
    """group -> (gold fields, predicted fields, correct)."""
    g, p = atoms(gold), atoms(pred)
    res = {}
    for grp in GROUPS:
        gf, pf = g.get(grp, {}), p.get(grp, {})
        correct = sum(1 for k, v in gf.items() if k in pf and norm(pf[k]) == norm(v))
        res[grp] = (len(gf), len(pf), correct)
    return res


def issues_found(gold: dict, flags) -> tuple[int, int, list]:
    want = gold.get("issues", [])
    missing = [w for w in want if not any(f.rule_id == w[0] and w[1].lower() in f.message.lower() for f in flags)]
    return len(want) - len(missing), len(want), missing


# --------------------------------------------------------------------------- #
# Synthetic gold, built from the test specs (independent of the parser)
# --------------------------------------------------------------------------- #

def synthetic_cases():
    from tests.synth.render import to_docx, to_pdf
    from tests.synth.specs import COURSES, EXPECTED

    for code, (c, fmt) in COURSES.items():
        names, weights = c["assessment_table"][0][1:-1], c["assessment_table"][1][1:-1]
        clo_rows = c["assessment_table"][2:]
        gold = {
            "file": f"{code}.{fmt}",
            "course": {"code": c["code"], "title": c["title"], "credit_hours": 3,
                       "prerequisites": c["prereq"] or None},
            "offering": {"term": c["term"]},
            "clos": [{"number": i, "text": t} for i, t in enumerate(c["clos"], 1)],
            "weights": [{"name": n, "weight_pct": float(w.rstrip("%"))} for n, w in zip(names, weights)],
            "clo_matrix": [{"assessment": n, "clo_numbers": [int(r[0].split()[1]) for r in clo_rows if r[j + 1] == "X"]}
                           for j, n in enumerate(names)],
            "weekly": [],
            "programs": [],
            "issues": [list(x) for x in EXPECTED[code]],
        }
        for tbl in c["weekly_tables"]:
            for r in tbl:
                if not r[0]:
                    continue  # continuation row; its topic belongs to the week above
                wk = {"week_no": int(r[0]), "topics": [t.strip() for t in r[1].split(";")],
                      "readings": [r[2]] if r[2] else [],
                      "clo_numbers": [int(x) for x in re.findall(r"\d", r[4])], "assessments": []}
                for line in r[3].split("\n") if r[3] else []:
                    m = re.match(r"(.+?)\s*\((\d+)%\)", line)
                    if m:
                        wk["assessments"].append({"name": m.group(1), "weight_pct": float(m.group(2))})
                gold["weekly"].append(wk)
        # continuation rows (CSCI 372 week 15) add their topic to the week above
        for tbl in c["weekly_tables"]:
            for i, r in enumerate(tbl):
                if not r[0] and i:
                    prev = next(w for w in gold["weekly"] if w["week_no"] == int(tbl[i - 1][0]))
                    prev["topics"].append(r[1])
                    if r[2]:
                        prev["readings"].append(r[2])
        for prog in c["programs"]:
            gold["programs"].append({
                "name": prog["name"],
                "plos": [{"number": i, "text": t} for i, t in enumerate(prog["plos"], 1)],
                "clo_plo": [{"clo": clo, "plo": plo, "strength": {"H": "high", "M": "medium", "L": "low"}[s]}
                            for clo, m in prog["mapping"].items() for plo, s in m.items()],
                "abet_addressed": prog["addressed"],
            })
        data = to_pdf(build_items(c)) if fmt == "pdf" else to_docx(build_items(c))
        yield code, gold, gold["file"], data


def build_items(c):
    from tests.synth.specs import build
    return build(c)


def real_cases(gold_dir: Path, files_dir: Path, include_drafts: bool):
    for gp in sorted(gold_dir.glob("*.json")):
        gold = json.loads(gp.read_text(encoding="utf-8"))
        if gold.get("status") != "verified" and not include_drafts:
            print(f"skip {gp.name}: status '{gold.get('status')}' (hand-check it, then set \"status\": \"verified\")")
            continue
        f = files_dir / gold["file"]
        if not f.exists():
            print(f"skip {gp.name}: {f.name} not found")
            continue
        label = gp.stem + ("" if gold.get("status") == "verified" else " (UNVERIFIED)")
        yield label, gold, f.name, f.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--synthetic", action="store_true", help="score the 5 synthetic syllabi (gold from their specs)")
    ap.add_argument("--gold", type=Path, default=ROOT / "fixtures" / "gold")
    ap.add_argument("--files", type=Path, default=ROOT / "fixtures" / "syllabi")
    ap.add_argument("--include-drafts", action="store_true")
    ap.add_argument("--json", type=Path, help="also write the scores to this file")
    args = ap.parse_args()

    cases = synthetic_cases() if args.synthetic else real_cases(args.gold, args.files, args.include_drafts)
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    report = []
    iss_ok = iss_all = 0
    for label, gold, fname, data in cases:
        rec = extract(fname, data)
        flags = validate(rec)
        s = score(gold, rec.model_dump(mode="json"))
        ok, n, missing = issues_found(gold, flags)
        iss_ok, iss_all = iss_ok + ok, iss_all + n
        g = sum(v[0] for v in s.values())
        c = sum(v[2] for v in s.values())
        print(f"{label:<28} fields {c}/{g} correct ({c / g:.0%})   issues {ok}/{n}"
              + (f"   MISSING {missing}" if missing else ""))
        for grp, (gn, pn, cn) in s.items():
            t = totals[grp]
            t[0] += gn
            t[1] += pn
            t[2] += cn
        report.append({"case": label, "groups": s, "issues_found": ok, "issues_expected": n})

    if not report:
        print("No cases scored.")
        return 1
    print(f"\n{'group':<12}{'gold':>6}{'pred':>6}{'correct':>9}{'precision':>11}{'recall':>8}")
    G = P = C = 0
    for grp in GROUPS:
        gn, pn, cn = totals[grp]
        G, P, C = G + gn, P + pn, C + cn
        prec = f"{cn / pn:.0%}" if pn else "—"
        rec = f"{cn / gn:.0%}" if gn else "—"
        print(f"{grp:<12}{gn:>6}{pn:>6}{cn:>9}{prec:>11}{rec:>8}")
    print(f"{'ALL':<12}{G:>6}{P:>6}{C:>9}{(C / P if P else 0):>11.0%}{(C / G if G else 0):>8.0%}")
    print(f"\nKnown issues flagged: {iss_ok}/{iss_all}")
    print(f"Gate 1 (≥90% of fields need no correction): {'PASS' if G and C / G >= 0.9 else 'FAIL'} "
          f"({C / G if G else 0:.1%})")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if G and C / G >= 0.9 and iss_ok == iss_all else 2


if __name__ == "__main__":
    sys.exit(main())
