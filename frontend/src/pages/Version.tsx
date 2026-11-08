import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import AssessmentDialog from "../components/AssessmentDialog";
import SourcePanel, { SourceContext } from "../components/SourcePanel";
import ThingsToCheck from "../components/ThingsToCheck";
import {
  AssessmentsTab,
  ClosTab,
  CourseTab,
  CoverageTab,
  EditLogTab,
  ProgramsTab,
  SourceTab,
  WeeklyTab,
} from "../components/RecordTabs";
import { fmtDate, tabFor } from "../components/util";
import Icon from "../components/Icon";
import { VERSION_CHANGED } from "../App";
import type {
  AssessmentOverview,
  AssessmentRow,
  Coverage,
  DraftItem,
  EditEntry,
  EditOp,
  Flag,
  Material,
  VersionDetail,
} from "../types";

/** The record's sections, named the way a teacher would. */
const TABS = [
  ["course", "Course details"],
  ["clos", "Learning outcomes"],
  ["assessments", "Assessments"],
  ["weekly", "Weekly plan"],
  ["programs", "Programme outcomes"],
  ["coverage", "Coverage"],
  ["source", "Text from the file"],
  ["log", "Changes you made"],
] as const;
type Tab = (typeof TABS)[number][0];

const STEPS = ["Upload the syllabus", "Check what the tool found", "Confirm it for the term",
               "Write and review questions", "Download or send out"];

export default function Version({ tab: view = "overview" }: { tab?: "overview" | "syllabus" }) {
  const id = Number(useParams().id);
  const nav = useNavigate();
  /* Jumping here from the overview changes the route, which remounts this
     page, so "open this assessment" and "show me this line" travel as
     navigation state rather than as state set before the jump. */
  const loc = useLocation();
  const handoff = (loc.state ?? null) as { ptr?: string; openRow?: string } | null;
  const [v, setV] = useState<VersionDetail | null>(null);
  const [tab, setTab] = useState<Tab>("course");
  const [focus, setFocus] = useState<string | null>(null);
  const [error, setError] = useState<{ msg: string; items?: string[] } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [edits, setEdits] = useState<EditEntry[] | null>(null);
  const [cov, setCov] = useState<Coverage | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourcePtr, setSourcePtr] = useState<string | null>(null);
  const [diff, setDiff] = useState<any | null>(null);
  const [ov, setOv] = useState<AssessmentOverview | null>(null);
  const [dialog, setDialog] = useState<{ row: AssessmentRow | null } | null>(null);
  const [progress, setProgress] = useState<{ materials: Material[]; items: DraftItem[] } | null>(null);

  const say = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3000);
  };
  const fail = (e: unknown) => {
    if (e instanceof ApiError)
      setError({ msg: e.message, items: e.items?.map((i) => i.message ?? `${i.loc}: ${i.msg}`) });
    else setError({ msg: String(e) });
  };

  useEffect(() => {
    setV(null);
    setOv(null);
    setProgress(null);
    api.get(id).then(setV).catch(fail);
    api.termDiff(id).then(setDiff).catch(() => setDiff(null));
  }, [id]);

  useEffect(() => {
    if (tab === "log") api.edits(id).then(setEdits).catch(fail);
    if (tab === "coverage") api.coverage(id).then(setCov).catch(fail);
  }, [tab, id, v?.updated_at]);

  const loaded = !!v;
  useEffect(() => {
    if (!loaded) return;
    api.assessmentOverview(id).then(setOv).catch(() => setOv(null));
  }, [id, loaded, v?.updated_at, v?.edit_count]);

  const confirmed = v?.status === "locked" || v?.status === "superseded";
  useEffect(() => {
    if (!confirmed) return;
    Promise.all([api.materials(id).catch(() => []), api.drafts(id).catch(() => [])])
      .then(([materials, items]) => setProgress({ materials, items }));
  }, [id, confirmed, v?.updated_at]);

  const editable = !!v && (v.status === "extracted" || v.status === "in_review");
  const status = v?.status;
  useEffect(() => {
    if (status) window.dispatchEvent(new Event(VERSION_CHANGED));
  }, [status]);

  const apply = useCallback(
    async (ops: EditOp[]) => {
      setError(null);
      try {
        const nv = await api.edit(id, ops);
        const before = v?.flags.filter((f) => f.status === "open").length ?? 0;
        const after = nv.flags.filter((f) => f.status === "open").length;
        setV(nv);
        say(after < before
          ? `Saved. ${before - after} thing${before - after === 1 ? "" : "s"} to check cleared.`
          : after > before ? `Saved. That raised ${after - before} new thing${after - before === 1 ? "" : "s"} to check.`
          : "Saved.");
      } catch (e) {
        if (e instanceof ApiError)
          throw new Error(e.items?.map((i) => `${i.loc ?? ""} ${i.msg ?? i.message ?? ""}`).join("; ") || e.message, { cause: e });
        throw e;
      }
    },
    [id, v],
  );
  const save = useCallback((path: string, value: unknown) => apply([{ op: "replace", path, value }]), [apply]);

  async function keep(f: Flag, note?: string) {
    const action = f.status === "open" ? "accept" : "reopen";
    const nv = await api.resolve(id, f.id, action, note).catch((e) => {
      throw new Error(e.message);
    });
    setV(nv);
    say(action === "accept" ? "Kept as it is." : "Back on the list.");
  }

  async function choose(f: Flag, i: number) {
    const before = v?.flags.filter((x) => x.status === "open").length ?? 0;
    const nv = await api.choose(id, f.id, i);
    setV(nv);
    const after = nv.flags.filter((x) => x.status === "open").length;
    say(after < before ? `Fixed. ${before - after} fewer thing${before - after === 1 ? "" : "s"} to check.` : "Saved.");
  }

  const highlight = useCallback((ptr: string) => {
    setSourcePtr(ptr);
    setTab(tabFor(ptr) as Tab);
    setFocus(null);
    setTimeout(() => setFocus(ptr), 60);
    setTimeout(() => setFocus((f) => (f === ptr ? null : f)), 5000);
  }, []);

  function showInSyllabus(ptr: string) {
    if (!ptr) return;
    if (view !== "syllabus") nav(`/v/${id}/syllabus`, { state: { ptr } });
    else highlight(ptr);
  }

  const rowOfFlag = useCallback(
    (f: Flag): AssessmentRow | null => ov?.rows.find((r) => r.flags.some((x) => x.id === f.id)) ?? null,
    [ov],
  );
  const openRow = useCallback((row: AssessmentRow | null) => {
    setTab("assessments");
    setDialog({ row });
  }, []);

  /* Act on what the overview asked for, once the data it needs is here. */
  useEffect(() => {
    if (!handoff?.ptr) return;
    highlight(handoff.ptr);
    nav(".", { replace: true, state: null });
  }, [handoff?.ptr, highlight, nav]);
  useEffect(() => {
    if (!handoff?.openRow || !ov) return;
    openRow(ov.rows.find((r) => r.key === handoff.openRow) ?? null);
    nav(".", { replace: true, state: null });
  }, [handoff?.openRow, ov, openRow, nav]);

  async function act(fn: () => Promise<VersionDetail | void>, goto?: (r: VersionDetail) => string) {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      if (r && goto) nav(goto(r));
      else if (r) setV(r);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  if (!v)
    return error
      ? <div className="error-box">{error.msg} <Link to="/courses">Back to my courses</Link></div>
      : <p className="muted">Loading…</p>;

  const rec = v.record;
  const props = { rec, editable, focus, save, apply };
  const assessProps = { ...props, overview: ov, onEdit: openRow, onAdd: () => openRow(null) };
  const blocking = v.flags.filter((f) => f.status === "open" && f.severity !== "info").length;
  const indexed = progress?.materials.filter((m) => m.status === "indexed") ?? [];
  const items = progress?.items ?? [];
  const toReview = items.filter((i) => ["suggested", "under_review", "needs_review"].includes(i.status));
  const approved = items.filter((i) => i.status === "approved");
  const step = !confirmed ? (v.can_lock ? 2 : 1)
    : v.export_count > 0 ? 5
    : approved.length > 0 ? 4
    : 3;

  const checks = (
    <ThingsToCheck
      flags={v.flags}
      editable={editable}
      onKeep={keep}
      onChoose={choose}
      fixable={(f) => rowOfFlag(f) !== null}
      onFix={(f) => {
        const row = rowOfFlag(f);
        if (view !== "syllabus") nav(`/v/${id}/syllabus`, { state: { openRow: row?.key } });
        else openRow(row);
      }}
      onShowInSyllabus={showInSyllabus}
    />
  );

  const header = (
    <div className="page-head">
      <div>
        <h1>{rec.course.code ?? "Course code not read"} {rec.course.title ?? ""}</h1>
        <p className="lede" style={{ marginBottom: 4 }}>
          {rec.offering.term ?? "Term not read"} ·{" "}
          {confirmed ? "Confirmed for this term" : blocking ? `${blocking} thing${blocking === 1 ? "" : "s"} to check` : "Ready to confirm"}
        </p>
        <p className="small muted" style={{ margin: 0 }}>
          Read from {v.source_filename ? (
            <button className="link" onClick={() => api.downloadSource(id, v.source_filename!).catch(fail)}>
              {v.source_filename}
            </button>
          ) : "the uploaded file"} on {fmtDate(v.created_at)}
          {v.version_no ? ` · version ${v.version_no}` : ""}
        </p>
      </div>
      <div className="actions">
        {confirmed ? (
          <>
            <Link to={`/v/${id}/quiz/new`} className="btn primary"><Icon name="quiz" size={16} /> Create a quiz or exam</Link>
            <button disabled={busy} onClick={() => act(() => api.revise(id), (r) => `/v/${r.id}`)}>
              Change the syllabus
            </button>
          </>
        ) : (
          <button className="primary" disabled={!v.can_lock || busy}
            title={v.can_lock ? "" : "Settle everything that must be fixed first"}
            onClick={() => {
              if (confirm(`Confirm ${rec.course.code} ${rec.offering.term ?? ""} as the syllabus for this term?`))
                act(() => api.lock(id));
            }}>
            Confirm syllabus for this term
          </button>
        )}
      </div>
    </div>
  );

  // ---- the syllabus itself ------------------------------------------------
  if (view === "syllabus") {
    return (
      <div>
        {header}
        {error && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            {error.msg}
            {error.items && <ul>{error.items.map((m, i) => <li key={i}>{m}</li>)}</ul>}
          </div>
        )}
        <SourceContext.Provider value={setSourcePtr}>
          <div className="layout">
            <div className="card">
              <nav className="tabs" aria-label="Parts of the syllabus">
                {TABS.map(([k, label]) => (
                  <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
                    {label}
                    {k === "clos" && <span className="count">{rec.clos.length}</span>}
                    {k === "weekly" && <span className="count">{rec.weekly.length}</span>}
                    {k === "log" && <span className="count">{v.edit_count}</span>}
                  </button>
                ))}
              </nav>
              {tab === "course" && <CourseTab {...props} />}
              {tab === "clos" && <ClosTab {...props} />}
              {tab === "assessments" && <AssessmentsTab {...assessProps} />}
              {tab === "weekly" && <WeeklyTab {...assessProps} />}
              {tab === "programs" && <ProgramsTab {...props} />}
              {tab === "coverage" && <CoverageTab cov={cov} />}
              {tab === "source" && <SourceTab rec={rec} focus={focus} />}
              {tab === "log" && (
                <EditLogTab edits={edits}
                  onExport={() => api.download(`/api/course-versions/${id}/edits.csv`, "changes.csv").catch(fail)} />
              )}
            </div>
            <div className="side-panel stack-tight">
              {sourcePtr && (
                <SourcePanel cvId={id} rec={rec} ptr={sourcePtr} onClose={() => setSourcePtr(null)}
                  isPdf={(v.source_filename ?? "").toLowerCase().endsWith(".pdf")} />
              )}
              {checks}
            </div>
          </div>
        </SourceContext.Provider>
        {dialog && ov && (
          <AssessmentDialog ov={ov} rec={rec} row={dialog.row} onClose={() => setDialog(null)} onSave={apply} />
        )}
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    );
  }

  // ---- the course overview ------------------------------------------------
  return (
    <div className="stack">
      {header}

      <ol className="steps" aria-label="Where this course has got to" tabIndex={0}>
        {STEPS.map((s, i) => (
          <li key={s} className={i < step ? "done" : i === step ? "now" : ""}
            aria-current={i === step ? "step" : undefined}>
            <span className="dot">{i < step ? <Icon name="check" size={13} /> : i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      {error && (
        <div className="error-box">
          {error.msg}
          {error.items && <ul>{error.items.map((m, i) => <li key={i}>{m}</li>)}</ul>}
        </div>
      )}

      {diff && (
        <div className="msg info">
          <Icon name="info" size={18} />
          <div className="grow">
            <strong>Compared with {diff.from_term ?? "the version before"}</strong>
            {[diff.diff.clos_added.length && `outcome ${diff.diff.clos_added.join(", ")} added`,
              diff.diff.clos_removed.length && `outcome ${diff.diff.clos_removed.join(", ")} removed`,
              Object.keys(diff.diff.clos_changed).length && `outcome ${Object.keys(diff.diff.clos_changed).join(", ")} reworded`,
              Object.keys(diff.diff.weights_changed).length && `${Object.keys(diff.diff.weights_changed).length} weight(s) changed`,
              diff.diff.weeks_changed.length && `topics changed in week(s) ${diff.diff.weeks_changed.join(", ")}`]
              .filter(Boolean).join("; ") || "nothing changed in the outcomes, weights or topics"}.
            {diff.affected_item_ids.length > 0 &&
              ` ${diff.affected_item_ids.length} approved question(s) tied to changed outcomes need another look.`}
          </div>
        </div>
      )}

      {editable && v.previous && v.previous.matching_settled_flags > 0 && (
        <div className="msg info">
          <Icon name="info" size={18} />
          <div className="grow">
            <strong>You have done some of this before</strong>
            You settled {v.previous.matching_settled_flags} of these in {v.previous.term}. Copying those
            decisions saves you going through them again.
          </div>
          <button className="btn" disabled={busy} onClick={() => act(() => api.carryOver(id, v.previous!.id))}>
            Copy them over
          </button>
        </div>
      )}

      {confirmed ? (
        <section className="card nextsteps">
          <div className="card-head"><h2>What to do next</h2></div>
          <NextSteps
            id={id}
            materials={indexed.length}
            materialsTotal={progress?.materials.length ?? 0}
            drafts={items.length}
            toReview={toReview.length}
            approved={approved.length}
            exports={v.export_count}
            loading={progress === null}
          />
        </section>
      ) : (
        <div className="layout">
          <div className="stack-tight">
            <div className="msg info">
              <Icon name="info" size={18} />
              <div className="grow">
                <strong>EduForge has read your syllabus</strong>
                It compared the three places your assessments appear and listed anything that does not add up.
                Settle each one, then confirm the syllabus so you can start writing questions.
              </div>
              <Link className="btn" to={`/v/${id}/syllabus`}>Open the syllabus</Link>
            </div>
            {checks}
          </div>
          <div className="side-panel">
            <section className="card">
              <div className="card-head"><h3>What EduForge read</h3></div>
              <dl className="stack-tight" style={{ margin: 0 }}>
                <Fact label="Course" value={`${rec.course.code ?? "not read"} ${rec.course.title ?? ""}`} />
                <Fact label="Term" value={rec.offering.term ?? "not read"} />
                <Fact label="Learning outcomes" value={`${rec.clos.length}`} />
                <Fact label="Weeks in the plan" value={`${rec.weekly.length}`} />
                <Fact label="Assessments" value={`${ov?.rows.length ?? rec.weights.length}`} />
                <Fact label="Changes you have made" value={`${v.edit_count}`} />
              </dl>
              <p className="hint">
                Something wrong? Open the syllabus and correct it; every change is recorded against the
                original file.
              </p>
              {editable && (
                <button className="danger" style={{ marginTop: 8 }} disabled={busy}
                  onClick={() => {
                    if (confirm("Delete this syllabus? The file you uploaded and the list of your changes go with it."))
                      act(async () => { await api.discard(id); nav("/courses"); });
                  }}>
                  Delete this syllabus
                </button>
              )}
            </section>
          </div>
        </div>
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="row between">
      <dt className="small muted">{label}</dt>
      <dd className="num" style={{ margin: 0, fontWeight: 600 }}>{value}</dd>
    </div>
  );
}

/** After confirming, what to do next, with live counts and one button each. */
function NextSteps({ id, materials, materialsTotal, drafts, toReview, approved, exports, loading }: {
  id: number; materials: number; materialsTotal: number; drafts: number; toReview: number;
  approved: number; exports: number; loading: boolean;
}) {
  const steps = [
    {
      title: "Add your slides and notes",
      optional: true,
      done: materials > 0,
      status: loading ? "Checking…"
        : materials > 0 ? `${materials} added`
        : materialsTotal > 0 ? `${materialsTotal} uploaded, not ready yet`
        : "None yet",
      body: "Optional, but worth it: with your own slides added, the questions follow your wording and show you the passage they came from.",
      to: `/v/${id}/materials`,
      action: materials > 0 ? "Manage slides" : "Add slides",
    },
    {
      title: "Create a quiz or exam",
      done: drafts > 0,
      status: loading ? "Checking…" : drafts > 0 ? `${drafts} question${drafts === 1 ? "" : "s"} written` : "None yet",
      body: "Say which assessment, which weeks and how many questions of each kind. EduForge writes them all in one go.",
      to: drafts > 0 ? `/v/${id}/quiz` : `/v/${id}/quiz/new`,
      action: drafts > 0 ? "See quizzes and exams" : "Create a quiz",
    },
    {
      title: "Review each question",
      done: drafts > 0 && toReview === 0,
      status: loading ? "Checking…"
        : drafts === 0 ? "Nothing to review yet"
        : toReview > 0 ? `${toReview} waiting for you` : "All reviewed",
      body: "Approve, change, or ask for a different one. Every answer is checked independently before you see it.",
      to: `/v/${id}/questions`,
      action: "Review questions",
    },
    {
      title: "Download the paper and the answer key",
      done: exports > 0,
      status: loading ? "Checking…"
        : approved === 0 ? "No approved questions yet"
        : exports > 0 ? `${approved} approved · downloaded ${exports} time${exports === 1 ? "" : "s"}`
        : `${approved} approved, ready to download`,
      body: "Two separate files, as Word or PDF: the question paper with no answers on it, and the answer key for you.",
      to: `/v/${id}/quiz`,
      action: "Open quizzes and exams",
    },
  ];
  return (
    <ol>
      {steps.map((s, i) => (
        <li key={s.title} className={s.done ? "done" : ""}>
          <span className="dot" aria-hidden="true">{s.done ? <Icon name="check" size={13} /> : i + 1}</span>
          <div className="grow">
            <div className="row wrap between">
              <h3>
                {s.title}
                {s.optional && <span className="chip">optional</span>}
              </h3>
              <span className={`pill ${s.done ? "ok" : "neutral"}`}>{s.status}</span>
            </div>
            <p className="small muted">{s.body}</p>
          </div>
          <Link className="btn" to={s.to}>{s.action}</Link>
        </li>
      ))}
    </ol>
  );
}
