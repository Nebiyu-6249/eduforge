import { useEffect, useRef, useState, type ReactNode } from "react";
import Icon from "../components/Icon";
import { useParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import { announceJob } from "../components/Activity";
import { fmtDate } from "../components/util";
import type { Job, VersionDetail } from "../types";

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

const METHOD: Record<string, string> = {
  key: "marked against the answer key", code: "marked by running the code tests",
  llm: "suggested against the rubric", manual: "no suggestion: this one is yours",
};
const TYPE_LABEL: Record<string, string> = {
  mcq: "Multiple choice", short_answer: "Short answer", problem: "Problem", code_exercise: "Code",
  practice_set: "Practice set", case_study: "Case study",
};

/** Marking: add the class, add their answers, check every suggested mark,
 *  release. The tool only ever suggests; the teacher confirms each mark.
 *  The page reads top to bottom in that order: the four steps, then the card
 *  for each step, the finished ones folded away. */
export default function Grading() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [status, setStatus] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const [forms, setForms] = useState<any[]>([]);
  const [sections, setSections] = useState<any[]>([]);
  const [formId, setFormId] = useState<number | null>(null);
  const [sectionId, setSectionId] = useState<number | null>(null);
  const [grid, setGrid] = useState<any | null>(null);
  const [subId, setSubId] = useState<number | null>(null);
  const [marking, setMarking] = useState<Job | null>(null);  // suggestions being worked out, in the background

  useEffect(() => {
    api.get(cv).then(setV).catch((e) => setErr(errText(e)));
    api.gradingStatus().then((s) => {
      setStatus(s);
      if (!s.enabled) return;
      api.gradingForms(cv).then((f) => { setForms(f); if (f.length) setFormId(f[0].id); }).catch((e) => setErr(errText(e)));
      loadSections();
      // Came back while marks were still being worked out: pick that up again.
      api.activeJobs().then((js) => {
        const j = js.find((x) => x.kind === "grade" && x.course_version_id === cv);
        if (j) watch(j.id);
      }).catch(() => undefined);
    }).catch((e) => setErr(errText(e)));
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadSections = () =>
    api.gradingSections(cv).then((s) => {
      setSections(s);
      setSectionId((cur) => cur ?? s.find((x: any) => !x.calibration)?.id ?? null);
    }).catch((e) => setErr(errText(e)));
  /* Switching papers while the last request is still in flight used to show
     the other paper's grid, because whichever answer came back last won. Only
     the newest request is allowed to set the grid. */
  const gridReq = useRef(0);
  const loadGrid = () => {
    const mine = ++gridReq.current;
    if (!formId || !sectionId) {
      setGrid(null);
      return;
    }
    api.grid(formId, sectionId)
      .then((g) => { if (gridReq.current === mine) setGrid(g); })
      .catch((e) => { if (gridReq.current === mine) setErr(errText(e)); });
  };
  useEffect(loadGrid, [formId, sectionId]);

  /* Follow a marking run without blocking the page: the grid fills in as each
     student is done, and the run carries on if the teacher leaves. */
  const watching = useRef<number | null>(null);
  async function watch(jobId: number) {
    announceJob();
    watching.current = jobId;
    let j = await api.job(jobId).catch(() => null);
    while (j && (j.status === "queued" || j.status === "running") && watching.current === jobId) {
      setMarking(j);
      loadGrid();
      await new Promise((r) => setTimeout(r, 2500));
      j = await api.job(jobId).catch(() => j);
    }
    if (watching.current !== jobId) return;
    setMarking(null);
    loadGrid();
    loadSections();
    if (j?.status === "done") setNote("The suggested marks are in. Check each one below.");
    else if (j?.status === "failed") setErr(j.error ?? "The marks could not be worked out. Try again.");
  }
  useEffect(() => () => { watching.current = null; }, []);

  async function run(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      await fn();
      if (done) setNote(done);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!v || !status) return err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>;
  const rec = v.record;
  if (!status.enabled) {
    return (
      <div className="stack">
        <h1>Marking</h1>
        <div className="empty">
          <h3>Marking is switched off</h3>
          <p>
            It handles real student work, so it stays off until the university's data-protection approval is
            in place. An administrator switches it on.
          </p>
        </div>
      </div>
    );
  }

  const section = sections.find((s) => s.id === sectionId);
  const haveStudents = (section?.students ?? 0) > 0;
  const haveAnswers = !!grid && grid.rows.length > 0;
  const haveSuggestions = haveAnswers && grid.rows.some((r: any) => Object.keys(r.cells).length > 0);
  const allConfirmed = haveSuggestions && grid.blockers.length === 0;
  const released = !!grid?.released_at;
  // 0 Add students · 1 Add answers · 2 Check marks · 3 Release
  // Answers in but no suggestions yet: step 3 is current, and its card says why the cells are empty.
  const at = released || allConfirmed ? 3 : haveAnswers ? 2 : haveStudents ? 1 : 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Marking · {rec.course.code}</h1>
          <p className="lede">
            EduForge suggests a mark for every answer. <strong>You confirm each one</strong>, and nothing reaches a
            student until you do.
          </p>
        </div>
      </div>
      <GradingSteps at={at} released={released} />
      {err && <div className="error-box" role="alert">{err}</div>}
      {note && <div className="msg ok" role="status"><Icon name="check" size={18} /><div className="grow">{note}</div></div>}

      <section className="card picker-bar">
        <div>
          <label className="lbl" htmlFor="g-form">Which paper</label>
          <select id="g-form" value={formId ?? ""} onChange={(e) => { setFormId(Number(e.target.value)); setSubId(null); }}>
            {forms.length === 0 && <option value="">No approved paper yet</option>}
            {forms.map((f) => <option key={f.id} value={f.id}>{f.assessment_name} · version {f.version_label} · {f.items} question{f.items === 1 ? "" : "s"}</option>)}
          </select>
        </div>
        <div>
          <label className="lbl" htmlFor="g-sec">Which class</label>
          <select id="g-sec" value={sectionId ?? ""} onChange={(e) => { setSectionId(Number(e.target.value)); setSubId(null); }}>
            {sections.length === 0 && <option value="">No class yet: add one in step 1</option>}
            {sections.filter((s) => !s.calibration).map((s) => <option key={s.id} value={s.id}>{s.label} · {s.students} students</option>)}
          </select>
        </div>
      </section>
      {!forms.length && (
        <div className="msg info"><Icon name="info" size={18} />
          <div className="grow"><strong>No approved paper yet</strong>Create a quiz or exam and approve it; then it can be marked here.</div>
        </div>
      )}

      <StepCard n={1} title="Add your students" at={at} done={haveStudents}
        summary={section ? `${section.students} student${section.students === 1 ? "" : "s"} in ${section.label}` : "No class yet"}>
        <SectionsCard cv={cv} sections={sections} reload={loadSections} run={run} busy={busy} />
      </StepCard>

      <StepCard n={2} title="Add their answers" at={at} done={haveAnswers}
        summary={haveAnswers ? `${grid.rows.length} answer sheet${grid.rows.length === 1 ? "" : "s"} added` : ""}>
        {formId && sectionId ? (
          <div className="stack-tight">
            <div className="row wrap">
              <label className="lbl" htmlFor="g-subs">Their answers</label>
              <input id="g-subs" type="file" accept=".csv,.pdf,.docx,.txt,.zip" disabled={busy} style={{ width: "auto" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) run(async () => {
                    const r = await api.uploadSubmissions(formId, sectionId, f);
                    setNote(`Took in ${r.submissions} answer sheet${r.submissions === 1 ? "" : "s"}, and removed ${r.redactions} name${r.redactions === 1 ? "" : "s"} or number${r.redactions === 1 ? "" : "s"} from them.`
                      + (r.unmatched_files?.length ? ` These file names matched nobody on the class list: ${r.unmatched_files.join(", ")}.` : ""));
                    loadSections();
                    watch(r.job.id);
                  });
                }} />
            </div>
            <p className="hint">A CSV with a column per question (Student ID, Q1, Q2 …), or one file per student with their ID in the file name, or a ZIP of those.</p>
            {grid && grid.rows.length === 0 && status.sample_class && (
              <div className="msg info">
                <Icon name="people" size={18} />
                <div className="grow">
                  <strong>Want to see how marking works first?</strong>
                  EduForge can fill this class with 30 invented students and their answers. They are made up: no real student data is involved.
                </div>
                <button className="btn" disabled={busy}
                  onClick={() => run(async () => {
                    const r = await api.sampleClass(formId!, sectionId!);
                    setNote(`Added ${r.students} invented students and their answers.`);
                    loadSections();
                    watch(r.job.id);
                  })}>
                  Try it with a sample class of 30 students
                </button>
              </div>
            )}
          </div>
        ) : <p className="muted small">Pick a paper and a class above.</p>}
      </StepCard>

      <StepCard n={3} title="Check the suggested marks" at={at} done={allConfirmed}
        summary={allConfirmed ? "Every mark confirmed" : ""}>
        {marking && (
          <div className="msg info" role="status">
            <div className="spinner" aria-hidden="true" style={{ margin: 0, width: 20, height: 20 }} />
            <div className="grow">
              <strong>Working out the suggested marks · {marking.time_left ?? "starting"}</strong>
              The grid fills in as each student is done. You can leave this page; it carries on.
              <div className="progress" style={{ marginTop: 8 }} role="progressbar" aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={marking.progress} aria-label="Working out the suggested marks">
                <span style={{ width: `${Math.max(4, marking.progress)}%` }} />
              </div>
            </div>
          </div>
        )}
        {!marking && haveAnswers && !haveSuggestions && (
          <div className="msg warn">
            <Icon name="warning" size={18} />
            <div className="grow">
              <strong>No marks have been suggested for these answers yet</strong>
              EduForge works out a suggested mark for every answer. Start it now; it takes a minute or two.
            </div>
            <button className="primary" disabled={busy}
              onClick={() => run(async () => { const j = await api.rescore(formId!, sectionId!, false); watch(j.id); })}>
              Suggest marks
            </button>
          </div>
        )}
        {grid && haveAnswers && <Grid grid={grid} busy={busy} run={run} reload={loadGrid} formId={formId!} sectionId={sectionId!}
          selected={subId} onSelect={setSubId} onRescore={(id) => watch(id)} />}
        {subId && <SubmissionPanel id={subId} grid={grid} run={run} busy={busy} reload={loadGrid} />}
        {!haveAnswers && <p className="muted small">The answers you add in step 2 appear here with a suggested mark each.</p>}
      </StepCard>

      <StepCard n={4} title="Release the marks" at={at} done={released}
        summary={released ? `Released on ${fmtDate(grid.released_at)}` : ""}>
        <ReleaseCard cv={cv} grid={grid} formId={formId} sectionId={sectionId} run={run} busy={busy} reload={loadGrid} />
      </StepCard>

      {formId && (
        <details className="card advanced">
          <summary><strong>Advanced:</strong> check the suggestions against your own marks</summary>
          <CalibrationCard formId={formId} run={run} busy={busy} />
        </details>
      )}
    </div>
  );
}

/** A step of the page: open while it is the current one, folded away once done. */
function StepCard({ n, title, at, done, summary, children }: {
  n: number; title: string; at: number; done: boolean; summary: string; children: ReactNode;
}) {
  const current = at === n - 1;
  return (
    <details className={`card step-card ${current ? "now" : done ? "done" : "later"}`} open={current || undefined}>
      <summary>
        <span className="step-n">{done && !current ? <Icon name="check" size={14} /> : n}</span>
        <span className="step-title">Step {n} · {title}</span>
        {summary && !current && <span className="small muted">{summary}</span>}
      </summary>
      <div className="step-body">{children}</div>
    </details>
  );
}

type Run = (fn: () => Promise<unknown>, done?: string) => Promise<void>;

/** Where marking has got to, in four steps. */
function GradingSteps({ at, released }: { at: number; released: boolean }) {
  const labels = ["Add your students", "Add their answers", "Check the suggested marks", "Release the marks"];
  return (
    <div className="steps-wrap">
      <ol className="steps" aria-label="Where marking has got to">
        {labels.map((label, i) => {
          const done = i < at || (released && i === 3);
          return (
            <li key={label} className={done ? "done" : i === at ? "now" : ""} aria-current={i === at ? "step" : undefined}>
              <span className="dot">{done ? <Icon name="check" size={13} /> : i + 1}</span>
              <span>{label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Step 4: the grading scale the letters come from, then release. */
function ReleaseCard({ cv, grid, formId, sectionId, run, busy, reload }: {
  cv: number; grid: any; formId: number | null; sectionId: number | null; run: Run; busy: boolean; reload: () => void;
}) {
  const [why, setWhy] = useState<string | null>(null);
  const blockers: string[] = grid?.blockers ?? ["Add the answers first."];
  const ready = !!grid && grid.rows.length > 0 && blockers.length === 0;
  return (
    <div className="stack-tight">
      <ScaleCard cv={cv} run={run} busy={busy} />
      {grid?.pending_feedback > 0 && (
        <p className="small muted">
          {grid.pending_feedback} comment{grid.pending_feedback === 1 ? " is" : "s are"} still waiting for your approval,
          so {grid.pending_feedback === 1 ? "it" : "they"} will not be sent.
        </p>
      )}
      {grid?.released_at && <p className="small">Last released on {fmtDate(grid.released_at)}. To change a mark now, record an appeal.</p>}
      <div>
        <button className={`primary ${ready ? "" : "soft-disabled"}`} aria-disabled={ready ? undefined : "true"}
          onClick={() => {
            if (!ready || !formId || !sectionId) {
              setWhy(blockers.join(" "));
              return;
            }
            setWhy(null);
            run(async () => { await api.releaseGrades(formId, sectionId); reload(); },
              "Released. A Grade Center file, a marks sheet and a feedback letter for each student have been downloaded.");
          }}>
          Release the marks
        </button>
      </div>
      {why && <p className="why" role="alert"><Icon name="info" size={16} /> Not ready to release yet: {why}</p>}
    </div>
  );
}

function ScaleCard({ cv, run, busy }: { cv: number; run: Run; busy: boolean }) {
  const [view, setView] = useState<any | null>(null);
  const [bands, setBands] = useState<any[]>([]);
  const [ack, setAck] = useState(false);
  const load = () => api.gradingScale(cv).then((s) => { setView(s); setBands(s.confirmed.length ? s.confirmed : s.extracted); });
  useEffect(() => { load(); }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!view) return null;
  const hasPoints = bands.some((b) => b.points !== null && b.points !== undefined);
  const set = (i: number, k: string, val: string) =>
    setBands(bands.map((b, j) => (j === i ? { ...b, [k]: k === "letter" ? val : val === "" ? null : Number(val) } : b)));
  return (
    <details className="scale-box" open={!view.confirmed.length || undefined}>
      <summary>
        <strong>Grading scale used for letters</strong>{" "}
        {view.confirmed.length ? <span className="pill ok">Confirmed</span> : <span className="pill attention">Check it before you release</span>}
      </summary>
      <p className="small muted">
        Read from your syllabus. Letter grades come from it, so check it before you release any marks.
        {view.confirmed_at && ` You confirmed this on ${fmtDate(view.confirmed_at)}.`}</p>
      <div className="scroll-x">
      <table className="grid" style={{ width: "auto" }}>
        <thead><tr><th>Letter</th><th>From %</th><th>To %</th>{hasPoints && <th>Grade points</th>}</tr></thead>
        <tbody>
          {bands.map((b, i) => (
            <tr key={i}>
              <td><input aria-label={`Letter ${i + 1}`} value={b.letter} onChange={(e) => set(i, "letter", e.target.value)} style={{ width: 60 }} /></td>
              <td><input aria-label={`${b.letter} from`} type="number" value={b.min_pct} onChange={(e) => set(i, "min_pct", e.target.value)} style={{ width: 80 }} /></td>
              <td><input aria-label={`${b.letter} to`} type="number" value={b.max_pct} onChange={(e) => set(i, "max_pct", e.target.value)} style={{ width: 80 }} /></td>
              {hasPoints && <td><input aria-label={`${b.letter} grade points`} type="number" value={b.points ?? ""} onChange={(e) => set(i, "points", e.target.value)} style={{ width: 80 }} /></td>}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {view.problems.length > 0 && <div className="error-box"><ul>{view.problems.map((p: string) => <li key={p}>{p}</li>)}</ul></div>}
      {view.others.length > 0 && (
        <div className="small">
          <strong>This differs from your other syllabuses this term</strong>
          <ul>{view.others.map((o: any) => <li key={o.course}>{o.course}: {o.scale}</li>)}</ul>
          <label><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ width: "auto" }} /> This is the scale that applies to this course</label>
        </div>
      )}
      <div><button disabled={busy || !bands.length}
        onClick={() => run(async () => { await api.confirmScale(cv, bands, ack); await load(); }, "Grading scale confirmed.")}>Confirm the scale</button></div>
    </details>
  );
}

function SectionsCard({ cv, sections, reload, run, busy }: { cv: number; sections: any[]; reload: () => void; run: Run; busy: boolean }) {
  const [label, setLabel] = useState("");
  const [shown, setShown] = useState<Record<number, any[]>>({});
  return (
    <div className="stack-tight">
      <p className="small muted" style={{ marginTop: 0 }}>
        A class list as a CSV file with a student ID, a name and an email. Names are stored encrypted and the
        rest of EduForge only ever sees a code name. Each time you reveal who is who, that is recorded.</p>
      <div className="scroll-x">
      <table className="grid">
        <thead><tr><th>Class</th><th>Students</th><th>Class list</th><th>Who is who</th></tr></thead>
        <tbody>
          {sections.filter((s) => !s.calibration).map((s) => (
            <tr key={s.id}>
              <th>{s.label}</th>
              <td>{s.students}</td>
              <td><input aria-label={`Roster for ${s.label}`} type="file" accept=".csv" disabled={busy} style={{ width: "auto" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) run(async () => { const r = await api.uploadRoster(s.id, f); reload(); return r; }, "Class list added.");
                }} /></td>
              <td>
                {shown[s.id] ? (
                  <>
                    <button onClick={() => setShown({ ...shown, [s.id]: undefined as any })}>Hide</button>
                    <ul className="small">{shown[s.id].map((r) => <li key={r.pseudonym}>{r.pseudonym}: {r.name} ({r.student_id})</li>)}</ul>
                  </>
                ) : (
                  <button disabled={busy || !s.students} onClick={() => run(async () => setShown({ ...shown, [s.id]: await api.roster(s.id, true) }))}>
                    Show their names
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <div className="row">
        <label className="lbl" htmlFor="new-sec">Add a class</label>
        <input id="new-sec" value={label} placeholder="e.g. S1" onChange={(e) => setLabel(e.target.value)} style={{ width: 120 }} />
        <button disabled={busy || !label.trim()} onClick={() => run(async () => { await api.addSection(cv, label); setLabel(""); reload(); })}>Add</button>
      </div>
    </div>
  );
}

function cellClass(c: any) {
  if (!c) return "";
  if (c.confirmed !== null) return "cell-ok";
  return c.needs_faculty ? "cell-flag" : "cell-todo";
}

function Grid({ grid, busy, run, reload, formId, sectionId, selected, onSelect, onRescore }: {
  grid: any; busy: boolean; run: Run; reload: () => void; formId: number; sectionId: number;
  selected: number | null; onSelect: (id: number) => void; onRescore: (jobId: number) => void;
}) {
  const anyCells = grid.rows.some((r: any) => Object.keys(r.cells).length > 0);
  const keyTodo = grid.rows.reduce((n: number, r: any) => n + Object.values(r.cells).filter(
    (c: any) => c.method === "key" && !c.needs_faculty && c.confirmed === null && c.suggested !== null).length, 0);
  return (
    <div className="stack">
      <div className="row wrap">
        {anyCells && (keyTodo > 0 ? (
          <button disabled={busy} onClick={() => run(async () => { await api.confirmKey(formId, sectionId); reload(); })}>
            Confirm the {keyTodo} marks from the answer key
          </button>
        ) : <span className="small muted">All answer-key marks are confirmed.</span>)}
        <span className="spacer" style={{ flex: 1 }} />
        <details className="more-menu">
          <summary className="btn"><Icon name="more" size={16} /> More</summary>
          <div className="more-pop">
            <button disabled={busy || !grid.rows.length}
              onClick={() => run(async () => { const j = await api.rescore(formId, sectionId, true); onRescore(j.id); })}>
              Suggest marks again (your confirmed marks stay)
            </button>
          </div>
        </details>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="grid">
          <thead>
            <tr>
              <th>Student</th>
              {grid.items.map((i: any) => <th key={i.item_id} className="c">Q{i.position}<div className="small muted">{TYPE_LABEL[i.type] ?? i.type} · {i.points} point{i.points === 1 ? "" : "s"}</div></th>)}
              <th className="c">Total</th>
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((r: any) => (
              <tr key={r.submission_id} className={selected === r.submission_id ? "sel" : ""}>
                <th className="nowrap"><button className="link nowrap" onClick={() => onSelect(r.submission_id)}>{r.pseudonym}</button>
                  {r.appeal_open && <span className="pill warning" style={{ marginLeft: 6 }}>appeal</span>}</th>
                {grid.items.map((i: any) => {
                  const c = r.cells[String(i.item_id)];
                  return (
                    <td key={i.item_id} className={`c ${cellClass(c)}`}
                      title={c ? `${METHOD[c.method]}${c.note ? ": " + c.note : ""}` : "not scored"}>
                      {!c ? "–" : c.confirmed !== null ? <strong>{c.confirmed}</strong> : c.suggested !== null ? `${c.suggested}?` : "?"}
                      {c?.needs_faculty && c.confirmed === null && <span className="sr-only"> needs you</span>}
                    </td>
                  );
                })}
                <td className="c">{r.confirmed_total ?? (Object.keys(r.cells).length ? <span className="muted">{r.suggested_total}?</span> : "–")}</td>
              </tr>
            ))}
            {!grid.rows.length && <tr><td colSpan={grid.items.length + 2} className="muted">No answers yet.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="small muted">
          <strong>Bold</strong> is a mark you have confirmed. A number with a question mark is a suggestion
          waiting for you. Amber means EduForge is not confident enough to suggest anything, so that one is
          yours to mark.
        </p>
      {grid.outliers.length > 0 && (
        <div className="small">
          <strong>Similar answers with different marks</strong> — worth a second look
          <ul>{grid.outliers.map((o: any, i: number) => (
            <li key={i}>Q{o.position}: {o.students.join(" vs ")} ({o.points.join(" vs ")}){o.identical ? ", identical answers" : ""}</li>))}</ul>
        </div>
      )}
    </div>
  );
}

function SubmissionPanel({ id, grid, run, busy, reload }: { id: number; grid: any; run: Run; busy: boolean; reload: () => void }) {
  const [sub, setSub] = useState<any | null>(null);
  const [pts, setPts] = useState<Record<number, string>>({});
  const [why, setWhy] = useState<Record<number, string>>({});
  const [edit, setEdit] = useState<Record<number, string>>({});
  const [appeal, setAppeal] = useState({ item: "", reason: "" });
  const [decide, setDecide] = useState<Record<number, { outcome: string; points: string }>>({});
  const load = () => api.submission(id).then((s) => {
    setSub(s);
    setPts(Object.fromEntries(s.answers.filter((a: any) => a.score).map((a: any) =>
      [a.score.id, String(a.score.confirmed ?? a.score.suggested ?? "")])));
  });
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!sub) return <p className="muted">Loading…</p>;
  const after = () => { load(); reload(); };
  const fbFor = (item: number | null) => sub.feedback.filter((f: any) => f.item_id === item);

  const feedback = (f: any) => (
    <div key={f.id} className={`fb ${f.status}`}>
      {edit[f.id] !== undefined ? (
        <textarea aria-label="Edit feedback" value={edit[f.id]} onChange={(e) => setEdit({ ...edit, [f.id]: e.target.value })} rows={3} />
      ) : <div>{f.text}</div>}
      <div className="row small">
        <span className="muted">{f.source} · {f.status}</span>
        {edit[f.id] !== undefined ? (
          <button disabled={busy} onClick={() => run(async () => { await api.feedbackAction(f.id, "edit", edit[f.id]); setEdit({ ...edit, [f.id]: undefined as any }); after(); })}>Save</button>
        ) : (
          <>
            {f.status !== "approved" && <button disabled={busy} onClick={() => run(async () => { await api.feedbackAction(f.id, "approve"); after(); })}>Approve</button>}
            <button disabled={busy} onClick={() => setEdit({ ...edit, [f.id]: f.text })}>Edit</button>
            {f.status !== "rejected" && <button disabled={busy} onClick={() => run(async () => { await api.feedbackAction(f.id, "reject"); after(); })}>Drop</button>}
          </>
        )}
      </div>
    </div>
  );

  return (
    <div className="card stack" style={{ background: "#fbfaf6" }}>
      <h3>{sub.pseudonym} <span className="small muted">· from a {sub.source} file · {sub.redactions === 0 ? "nothing to remove" : `${sub.redactions} name${sub.redactions === 1 ? "" : "s"} or number${sub.redactions === 1 ? "" : "s"} removed`}</span></h3>
      {sub.answers.map((a: any) => {
        const s = a.score;
        return (
          <div key={a.item_id} className="answer">
            <div className="small muted">Question {a.position} · {TYPE_LABEL[a.type] ?? a.type}</div>
            <div className="small" style={{ whiteSpace: "pre-wrap" }}>{a.question}</div>
            <pre className="code" style={{ whiteSpace: "pre-wrap" }}>{a.text || "(no answer)"}</pre>
            {s && (
              <div className="small stack">
                <div>Suggested: <strong>{s.suggested ?? "—"}</strong> / {s.max} · {METHOD[s.method]}
                  {s.confidence !== null && ` · confidence ${Math.round(s.confidence * 100)}%`}
                  {s.needs_faculty && <span className="pill warning" style={{ marginLeft: 6 }}>needs you</span>}</div>
                {s.note && <div className="muted">{s.note}</div>}
                {s.criteria?.some((c: any) => c.level) && (
                  <ul>{s.criteria.map((c: any) => (
                    <li key={c.criterion}>{c.criterion}: <strong>{c.level ?? "—"}</strong> ({c.points ?? "?"})
                      {c.evidence?.length > 0 && <> — “{c.evidence.join("”, “")}”</>}</li>))}</ul>
                )}
                {s.evidence?.length > 0 && !s.criteria?.some((c: any) => c.level) && <div className="muted">{s.evidence.join(" · ")}</div>}
                <div className="row wrap">
                  <label htmlFor={`pts-${s.id}`}>Mark</label>
                  <input id={`pts-${s.id}`} type="number" min={0} max={s.max} step="0.5" value={pts[s.id] ?? ""} style={{ width: 90 }}
                    onChange={(e) => setPts({ ...pts, [s.id]: e.target.value })} />
                  <input aria-label="Reason (needed when overriding a confident suggestion)" placeholder="Reason (optional)"
                    value={why[s.id] ?? ""} onChange={(e) => setWhy({ ...why, [s.id]: e.target.value })} style={{ width: 260 }} />
                  <button className="primary" disabled={busy || pts[s.id] === "" || pts[s.id] === undefined}
                    onClick={() => run(async () => { await api.confirmScore(s.id, Number(pts[s.id]), why[s.id]); after(); })}>
                    {s.confirmed !== null ? "Update" : "Confirm"}
                  </button>
                  {s.confirmed !== null && <span className="pill locked">you confirmed {s.confirmed}</span>}
                </div>
                {s.history?.length > 0 && (
                  <details><summary>History ({s.history.length})</summary>
                    <ul>{s.history.map((h: any, i: number) => <li key={i}>{fmtDate(h.at)} · {h.by} · {h.kind}: {h.points}{h.reason ? ` (${h.reason})` : ""}</li>)}</ul>
                  </details>
                )}
              </div>
            )}
            {fbFor(a.item_id).map(feedback)}
          </div>
        );
      })}
      <div>
        <h3>Overall feedback</h3>
        {fbFor(null).length === 0 && <p className="small muted">Appears once every mark is confirmed.</p>}
        {fbFor(null).map(feedback)}
      </div>
      <div className="stack">
        <h3>Appeals</h3>
        {sub.appeals.map((ap: any) => (
          <div key={ap.id} className="small">
            <strong>{ap.item_id ? `Q${grid?.items.find((i: any) => i.item_id === ap.item_id)?.position}` : "Whole assessment"}</strong>: {ap.reason}
            {" · "}<span className="pill info">{ap.status}</span>{ap.outcome && ` · ${ap.outcome}`}
            {ap.status === "open" && (
              <div className="row wrap">
                <input aria-label="Outcome" placeholder="Outcome" value={decide[ap.id]?.outcome ?? ""}
                  onChange={(e) => setDecide({ ...decide, [ap.id]: { ...decide[ap.id], outcome: e.target.value } })} style={{ width: 240 }} />
                {ap.item_id && <input aria-label="New mark" type="number" placeholder="New mark" value={decide[ap.id]?.points ?? ""}
                  onChange={(e) => setDecide({ ...decide, [ap.id]: { ...decide[ap.id], points: e.target.value } })} style={{ width: 100 }} />}
                <button disabled={busy || !decide[ap.id]?.outcome}
                  onClick={() => run(async () => {
                    const d = decide[ap.id];
                    await api.decideAppeal(ap.id, d.outcome, ap.item_id && d.points !== undefined && d.points !== "" ? { [ap.item_id]: Number(d.points) } : {});
                    after();
                  })}>Decide</button>
              </div>
            )}
          </div>
        ))}
        <div className="row wrap">
          <select aria-label="Appeal question" value={appeal.item} onChange={(e) => setAppeal({ ...appeal, item: e.target.value })} style={{ width: "auto" }}>
            <option value="">Whole assessment</option>
            {sub.answers.map((a: any) => <option key={a.item_id} value={a.item_id}>Q{a.position}</option>)}
          </select>
          <input aria-label="Appeal reason" placeholder="Student's reason" value={appeal.reason}
            onChange={(e) => setAppeal({ ...appeal, reason: e.target.value })} style={{ width: 300 }} />
          <button disabled={busy || !appeal.reason.trim()}
            onClick={() => run(async () => { await api.appeal(id, appeal.item ? Number(appeal.item) : null, appeal.reason); setAppeal({ item: "", reason: "" }); after(); })}>
            Record appeal
          </button>
        </div>
      </div>
    </div>
  );
}

function CalibrationCard({ formId, run, busy }: { formId: number; run: Run; busy: boolean }) {
  const [sets, setSets] = useState<any[]>([]);
  const [desc, setDesc] = useState("");
  const load = () => api.calibrations(formId).then(setSets).catch(() => setSets([]));
  useEffect(() => { load(); }, [formId]); // eslint-disable-line react-hooks/exhaustive-deps
  const cols = ["n", "suggested", "exact", "within_one", "qwk", "mae", "mean_diff", "length_bias_r"];
  return (
    <div className="stack-tight" style={{ marginTop: 12 }}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Before trusting the suggestions on a new kind of question, mark a few papers yourself and upload them with
        your marks (columns Student ID, Q1…, M1…). EduForge then shows how closely its suggestions agree with you.
        These practice sets are never released to students.</p>
      <div className="row wrap">
        <input aria-label="Name for this practice set" placeholder="Name, e.g. Fall 2027 Quiz 1" value={desc}
          onChange={(e) => setDesc(e.target.value)} style={{ width: 280 }} />
        <input aria-label="Answers with your own marks (CSV)" type="file" accept=".csv" disabled={busy} style={{ width: "auto" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) run(async () => { const r = await api.calibrate(formId, f, desc); await waitJob(r.job.id); await load(); }, "Practice set checked against your marks.");
          }} />
      </div>
      {sets.map((s) => (
        <div key={s.id} className="small">
          <strong>Set {s.id}</strong> {s.description} · {fmtDate(s.created_at)}
          {s.gate_misses.length ? <span className="pill warning" style={{ marginLeft: 6 }}>Not close enough yet: {s.gate_misses.join("; ")}</span>
            : <span className="pill locked" style={{ marginLeft: 6 }}>Close enough to rely on</span>}
          <div className="scroll-x">
            <table className="grid">
              <thead><tr><th>Group</th>{cols.map((c) => <th key={c} className="c">{c.replace(/_/g, " ")}</th>)}</tr></thead>
              <tbody>{Object.entries(s.report).map(([g, r]: [string, any]) => (
                <tr key={g}><th>{g}</th>{cols.map((c) => <td key={c} className="c">{r[c] ?? "—"}</td>)}</tr>))}</tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
