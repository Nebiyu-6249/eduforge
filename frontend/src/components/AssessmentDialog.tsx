import { useMemo, useRef, useState } from "react";
import Modal from "./Modal";
import type { AssessmentOverview, AssessmentRow, EditOp, SyllabusRecord } from "../types";

/* An assessment lives in three places in the record: the weight table, the
   CLO x assessment matrix and the weekly schedule. This dialog edits all
   three at once and saves them with one apply(ops) call, so settling V2-V6 or
   V9 is one save and one coherent set of edit-log entries. */

interface SchedDraft {
  uid: number;
  /** Where it is now in the record; null for one being added. */
  origin: { week_index: number; item_index: number } | null;
  week_index: number;
  name: string;
  weight: string;
  due_date: string;
  due_week: string;
  due_text_raw: string | null;
  removed: boolean;
}

interface Props {
  ov: AssessmentOverview;
  rec: SyllabusRecord;
  /** null opens the dialog empty, to add an assessment. */
  row: AssessmentRow | null;
  onClose: () => void;
  onSave: (ops: EditOp[]) => Promise<void>;
}

const DAY_INDEX = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const DAY_NAME: Record<string, string> = {
  sun: "Sunday", mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday",
};

const numOrNull = (s: string): number | null => (s.trim() === "" ? null : Number(s));
const txt = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
const same = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i]);

export default function AssessmentDialog({ ov, rec, row, onClose, onSave }: Props) {
  const uid = useRef(0);
  const adding = row === null;

  const [name, setName] = useState(row?.name ?? "");
  const [hasWeight, setHasWeight] = useState(adding ? true : row.weight !== null);
  const [weight, setWeight] = useState(txt(row?.weight?.weight_pct));
  const [hasMatrix, setHasMatrix] = useState(adding ? true : row.matrix !== null);
  const [matrixClos, setMatrixClos] = useState<number[]>(row?.matrix?.clo_numbers ?? []);
  const [sched, setSched] = useState<SchedDraft[]>(() =>
    adding
      ? [{ uid: uid.current++, origin: null, week_index: ov.weeks[0]?.index ?? 0, name: "", weight: "",
           due_date: "", due_week: "", due_text_raw: null, removed: false }]
      : row.schedule.map((c) => ({
          uid: uid.current++,
          origin: { week_index: c.week_index, item_index: c.item_index },
          week_index: c.week_index,
          name: c.name,
          weight: txt(c.weight_pct),
          due_date: c.due_date ?? "",
          due_week: txt(c.due_week),
          due_text_raw: c.due_text_raw,
          removed: false,
        })),
  );
  // The CLO list belongs to the week row, so entries in the same week share it.
  const [weekClos, setWeekClos] = useState<Record<number, number[]>>(() => {
    const m: Record<number, number[]> = {};
    for (const c of row?.schedule ?? []) m[c.week_index] = [...c.clo_numbers];
    return m;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const closOf = (wi: number) => weekClos[wi] ?? rec.weekly[wi]?.clo_numbers ?? [];
  const setClosOf = (wi: number, v: number[]) => setWeekClos((p) => ({ ...p, [wi]: v }));
  const live = sched.filter((s) => !s.removed);
  const weekIndexes = useMemo(() => [...new Set(live.map((s) => s.week_index))], [live]);

  const schedTotal = live.reduce((t, s) => t + (Number(s.weight) || 0), 0);
  const schedClos = [...new Set(weekIndexes.flatMap((wi) => closOf(wi)))].sort((a, b) => a - b);
  const weightNum = numOrNull(weight);
  const weightDisagrees = hasWeight && weightNum !== null && live.length > 0 &&
    live.some((s) => s.weight !== "") && Math.abs(schedTotal - weightNum) > 0.01;
  const closDisagree = hasMatrix && schedClos.length > 0 && matrixClos.length > 0 &&
    !same(matrixClos, schedClos);

  const setSchedField = (u: number, patch: Partial<SchedDraft>) =>
    setSched((p) => p.map((s) => (s.uid === u ? { ...s, ...patch } : s)));

  function renameAll(next: string) {
    const before = name;
    setName(next);
    // Keep the schedule entries matched to the weight row when they shared its name.
    setSched((p) => p.map((s) => (s.name === before || s.name === "" ? { ...s, name: next } : s)));
  }

  function copyWeightToSchedule() {
    if (weightNum === null || live.length === 0) return;
    const each = weightNum / live.length;
    const rounded = Math.round(each * 100) / 100;
    setSched((p) => {
      const ids = p.filter((s) => !s.removed).map((s) => s.uid);
      return p.map((s) => {
        if (s.removed) return s;
        const isLast = s.uid === ids[ids.length - 1];
        const v = isLast ? Math.round((weightNum - rounded * (ids.length - 1)) * 100) / 100 : rounded;
        return { ...s, weight: String(v) };
      });
    });
  }

  const copyScheduleToWeight = () => setWeight(String(Math.round(schedTotal * 100) / 100));
  const copyMatrixClosToSchedule = () => weekIndexes.forEach((wi) => setClosOf(wi, [...matrixClos]));
  const copyScheduleClosToMatrix = () => setMatrixClos(schedClos);

  function meetingWarning(date: string): string | null {
    if (!date || ov.meeting_days.length === 0) return null;
    const d = new Date(date + "T00:00:00");
    if (Number.isNaN(d.getTime())) return null;
    const day = DAY_INDEX[d.getDay()];
    if (ov.meeting_days.includes(day)) return null;
    return `${DAY_NAME[day]}, but the class meets ${ov.meeting_days_label}. An in-class assessment on a day with no class is worth a second look.`;
  }

  function buildOps(): EditOp[] {
    const replaces: EditOp[] = [];
    const removes: EditOp[] = [];
    const adds: EditOp[] = [];

    // 1. Weight table.
    if (row?.weight && hasWeight) {
      if (name !== row.weight.name) replaces.push({ op: "replace", path: `/weights/${row.weight.index}/name`, value: name });
      if (weightNum !== row.weight.weight_pct)
        replaces.push({ op: "replace", path: `/weights/${row.weight.index}/weight_pct`, value: weightNum });
    } else if (row?.weight && !hasWeight) {
      removes.push({ op: "remove", path: `/weights/${row.weight.index}` });
    } else if (!row?.weight && hasWeight) {
      adds.push({ op: "add", path: "/weights/-", value: { name, weight_pct: weightNum } });
    }

    // 2. CLO x assessment matrix.
    if (row?.matrix && hasMatrix) {
      if (name !== row.matrix.assessment)
        replaces.push({ op: "replace", path: `/clo_matrix/${row.matrix.index}/assessment`, value: name });
      if (!same(matrixClos, row.matrix.clo_numbers))
        replaces.push({ op: "replace", path: `/clo_matrix/${row.matrix.index}/clo_numbers`, value: matrixClos });
    } else if (row?.matrix && !hasMatrix) {
      removes.push({ op: "remove", path: `/clo_matrix/${row.matrix.index}` });
    } else if (!row?.matrix && hasMatrix) {
      adds.push({ op: "add", path: "/clo_matrix/-", value: { assessment: name, clo_numbers: matrixClos } });
    }

    // 3. The CLOs of each week row this assessment sits in.
    for (const [key, value] of Object.entries(weekClos)) {
      const wi = Number(key);
      if (!weekIndexes.includes(wi)) continue;
      if (!same(value, rec.weekly[wi]?.clo_numbers ?? []))
        replaces.push({ op: "replace", path: `/weekly/${wi}/clo_numbers`, value });
    }

    // 4. Schedule entries. Replaces use the indices as they are now, so they go
    //    first; removals then run deepest-first, and additions append.
    for (const s of sched) {
      const body = {
        name: s.name,
        weight_pct: numOrNull(s.weight),
        due_text_raw: s.due_text_raw,
        due_date: s.due_date || null,
        due_week: numOrNull(s.due_week),
      };
      if (s.origin && s.removed) {
        removes.push({ op: "remove", path: `/weekly/${s.origin.week_index}/assessments/${s.origin.item_index}` });
      } else if (s.origin && s.origin.week_index === s.week_index) {
        const before = row?.schedule.find(
          (c) => c.week_index === s.origin!.week_index && c.item_index === s.origin!.item_index);
        const unchanged = before && before.name === body.name && before.weight_pct === body.weight_pct &&
          (before.due_date ?? null) === body.due_date && (before.due_week ?? null) === body.due_week;
        if (!unchanged)
          replaces.push({ op: "replace", path: `/weekly/${s.origin.week_index}/assessments/${s.origin.item_index}`, value: body });
      } else if (s.origin) {
        removes.push({ op: "remove", path: `/weekly/${s.origin.week_index}/assessments/${s.origin.item_index}` });
        adds.push({ op: "add", path: `/weekly/${s.week_index}/assessments/-`, value: body });
      } else if (!s.removed) {
        adds.push({ op: "add", path: `/weekly/${s.week_index}/assessments/-`, value: body });
      }
    }
    removes.sort((a, b) => b.path.localeCompare(a.path, undefined, { numeric: true }));
    return [...replaces, ...removes, ...adds];
  }

  async function save() {
    setErr(null);
    if (!name.trim()) {
      setErr("Give the assessment a name.");
      return;
    }
    if (weight !== "" && Number.isNaN(Number(weight))) {
      setErr("The weight must be a number, or empty.");
      return;
    }
    if (!hasWeight && !hasMatrix && live.length === 0) {
      setErr("An assessment has to appear in at least one of the three places.");
      return;
    }
    const ops = buildOps();
    if (ops.length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    try {
      await onSave(ops);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const cloBoxes = (checked: number[], onChange: (v: number[]) => void, group: string, disabled = false) => (
    <div className="clo-boxes">
      {ov.clo_numbers.map((n) => (
        <label key={n} className={`clo-box ${checked.includes(n) ? "on" : ""}`}>
          <input
            type="checkbox"
            checked={checked.includes(n)}
            disabled={disabled}
            onChange={() => onChange(checked.includes(n) ? checked.filter((x) => x !== n) : [...checked, n].sort((a, b) => a - b))}
          />
          <span>Outcome {n}</span>
          <span className="sr-only">{group}</span>
        </label>
      ))}
      {ov.clo_numbers.length === 0 && <span className="muted small">No CLOs in this syllabus yet.</span>}
    </div>
  );

  return (
    <Modal
      title={adding ? "Add an assessment" : `Edit ${row?.name}`}
      description="The weight table, the assessment table and the weekly plan are saved together, as one change."
      onClose={onClose}
      footer={
        <>
          {err && <div className="error-box small grow">{err}</div>}
          <span className="grow" />
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </>
      }
    >
      {row && row.flags.length > 0 && (
        <section className="dlg-flags" aria-label="Flags on this assessment">
          <h3>What needs fixing here</h3>
          {row.flags.map((f) => (
            <p key={f.id} className={`dlg-flag ${f.severity}`}>
              <strong>{f.rule_id}</strong> {f.message}
            </p>
          ))}
        </section>
      )}

      <div className="dlg-grid">
        <div className="dlg-field">
          <label className="lbl" htmlFor="ad-name">Assessment name</label>
          <input id="ad-name" value={name} onChange={(e) => renameAll(e.target.value)} autoComplete="off" />
        </div>
        <div className="dlg-field">
          <label className="lbl" htmlFor="ad-weight">Weight table</label>
          <div className="row">
            <input id="ad-weight" type="number" step="any" min={0} max={100} value={weight} disabled={!hasWeight}
              onChange={(e) => setWeight(e.target.value)} style={{ width: 110 }} />
            <span className="small muted">%</span>
          </div>
          <label className="small row" style={{ gap: 6, marginTop: 6 }}>
            <input type="checkbox" checked={hasWeight} onChange={(e) => setHasWeight(e.target.checked)} />
            In the weight table
          </label>
        </div>
      </div>

      <section className="dlg-sect">
        <div className="dlg-sect-head">
          <h3>The weekly plan</h3>
          <button type="button" className="icon" onClick={() =>
            setSched((p) => [...p, { uid: uid.current++, origin: null,
              week_index: ov.weeks[0]?.index ?? 0, name, weight: "", due_date: "", due_week: "",
              due_text_raw: null, removed: false }])}>
            Add it to another week
          </button>
        </div>
        {live.length === 0 && <p className="muted small">Not in the weekly plan yet.</p>}
        {sched.map((s) => s.removed ? null : (
          <fieldset key={s.uid} className="dlg-entry">
            <legend className="sr-only">Schedule entry {s.name || "new"}</legend>
            <div className="dlg-entry-grid">
              <div>
                <label className="lbl" htmlFor={`ad-w-${s.uid}`}>Week</label>
                <select id={`ad-w-${s.uid}`} value={s.week_index}
                  onChange={(e) => setSchedField(s.uid, { week_index: Number(e.target.value) })}>
                  {ov.weeks.map((w) => (
                    <option key={w.index} value={w.index}>Week {w.week_no}{w.topics[0] ? ` — ${w.topics[0]}` : ""}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="lbl" htmlFor={`ad-n-${s.uid}`}>Name in the weekly plan</label>
                <input id={`ad-n-${s.uid}`} value={s.name} onChange={(e) => setSchedField(s.uid, { name: e.target.value })} />
              </div>
              <div>
                <label className="lbl" htmlFor={`ad-p-${s.uid}`}>Weight</label>
                <input id={`ad-p-${s.uid}`} type="number" step="any" min={0} max={100} value={s.weight}
                  onChange={(e) => setSchedField(s.uid, { weight: e.target.value })} />
              </div>
              <div>
                <label className="lbl" htmlFor={`ad-d-${s.uid}`}>Due date</label>
                <input id={`ad-d-${s.uid}`} type="date" value={s.due_date}
                  onChange={(e) => setSchedField(s.uid, { due_date: e.target.value })} />
              </div>
              <div>
                <label className="lbl" htmlFor={`ad-dw-${s.uid}`}>Due week</label>
                <input id={`ad-dw-${s.uid}`} type="number" min={1} value={s.due_week}
                  onChange={(e) => setSchedField(s.uid, { due_week: e.target.value })} />
              </div>
              <div className="dlg-entry-actions">
                <button type="button" className="icon danger" onClick={() => setSchedField(s.uid, { removed: true })}>
                  Remove from the weekly plan
                </button>
              </div>
            </div>
            {meetingWarning(s.due_date) && (
              <p className="dlg-warn" role="status">
                {new Date(s.due_date + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })} is a {meetingWarning(s.due_date)}
              </p>
            )}
            {s.due_text_raw && <p className="small muted">The file says: “{s.due_text_raw}”</p>}
            <div className="dlg-clos">
              <span className="lbl">Outcomes the weekly plan gives week {rec.weekly[s.week_index]?.week_no}</span>
              {cloBoxes(closOf(s.week_index), (v) => setClosOf(s.week_index, v), `in week ${rec.weekly[s.week_index]?.week_no}`)}
              {(rec.weekly[s.week_index]?.assessments.length ?? 0) > 1 && (
                <p className="small muted">
                  Week {rec.weekly[s.week_index]?.week_no} has more than one assessment in it, and the weekly
                  plan keeps one list of outcomes per week, so this list covers all of them.
                </p>
              )}
            </div>
          </fieldset>
        ))}
        {(weightDisagrees || live.length > 0) && (
          <div className="dlg-help">
            <span className="small">
              Weight table {hasWeight ? `${weightNum ?? "not set"}%` : "not listed"} · weekly plan {schedTotal}%
            </span>
            <button type="button" className="icon" onClick={copyWeightToSchedule} disabled={!hasWeight || weightNum === null || live.length === 0}>
              Use the weight table figure in the weekly plan
            </button>
            <button type="button" className="icon" onClick={copyScheduleToWeight} disabled={!hasWeight || live.length === 0}>
              Use the weekly plan total in the weight table
            </button>
          </div>
        )}
      </section>

      <section className="dlg-sect">
        <h3>The assessment table</h3>
        <label className="small row" style={{ gap: 6, marginBottom: 6 }}>
          <input type="checkbox" checked={hasMatrix} onChange={(e) => setHasMatrix(e.target.checked)} />
          Listed in the assessment table
        </label>
        {cloBoxes(matrixClos, setMatrixClos, "in the matrix", !hasMatrix)}
        <div className="dlg-help">
          {closDisagree && <span className="small">The assessment table and the weekly plan disagree.</span>}
          <button type="button" className="icon" onClick={copyMatrixClosToSchedule} disabled={!hasMatrix || weekIndexes.length === 0}>
            Copy these outcomes to the weekly plan
          </button>
          <button type="button" className="icon" onClick={copyScheduleClosToMatrix} disabled={!hasMatrix || weekIndexes.length === 0}>
            Copy the weekly plan outcomes here
          </button>
        </div>
      </section>
    </Modal>
  );
}
