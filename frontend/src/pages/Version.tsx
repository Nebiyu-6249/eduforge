import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import AssessmentDialog from "../components/AssessmentDialog";
import FlagsPanel from "../components/FlagsPanel";
import SourcePanel, { SourceContext } from "../components/SourcePanel";
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
import { STATUS_LABEL, fmtDate, tabFor } from "../components/util";
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

const TABS = [
  ["course", "Course"],
  ["clos", "CLOs"],
  ["assessments", "Assessments"],
  ["weekly", "Weekly plan"],
  ["programs", "PLOs & mapping"],
  ["coverage", "Coverage"],
  ["source", "Source text"],
  ["log", "Edit log"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function Version() {
  const id = Number(useParams().id);
  const nav = useNavigate();
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
    setTimeout(() => setToast(null), 2600);
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

  // The reconciliation rows follow the record, so they are reloaded after every save.
  const loaded = !!v;
  useEffect(() => {
    if (!loaded) return;
    api.assessmentOverview(id).then(setOv).catch(() => setOv(null));
  }, [id, loaded, v?.updated_at, v?.edit_count]);

  // What is already done after locking, for the "Next steps" panel and the stepper.
  const locked = v?.status === "locked" || v?.status === "superseded";
  useEffect(() => {
    if (!locked) return;
    Promise.all([api.materials(id).catch(() => []), api.drafts(id).catch(() => [])])
      .then(([materials, items]) => setProgress({ materials, items }));
  }, [id, locked, v?.updated_at]);

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
        say(after < before ? `Saved · ${before - after} flag(s) cleared` : after > before ? `Saved · ${after - before} new flag(s)` : "Saved and logged");
      } catch (e) {
        if (e instanceof ApiError)
          throw new Error(e.items?.map((i) => `${i.loc ?? ""} ${i.msg ?? i.message ?? ""}`).join("; ") || e.message, { cause: e });
        throw e;
      }
    },
    [id, v],
  );
  const save = useCallback((path: string, value: unknown) => apply([{ op: "replace", path, value }]), [apply]);

  async function resolve(f: Flag, action: "accept" | "reopen", note?: string) {
    const nv = await api.resolve(id, f.id, action, note).catch((e) => {
      throw new Error(e.message);
    });
    setV(nv);
  }

  async function choose(f: Flag, choice: number) {
    const before = v?.flags.filter((x) => x.status === "open").length ?? 0;
    const nv = await api.choose(id, f.id, choice);
    setV(nv);
    const after = nv.flags.filter((x) => x.status === "open").length;
    say(after < before ? `Applied and logged · ${before - after} flag(s) cleared` : "Applied and logged");
  }

  function jump(ptr: string) {
    setSourcePtr(ptr);
    setTab(tabFor(ptr) as Tab);
    setFocus(null);
    setTimeout(() => setFocus(ptr), 30);
    setTimeout(() => setFocus((f) => (f === ptr ? null : f)), 4000);
  }

  /** The reconciliation row a flag belongs to, if its evidence names an assessment. */
  const rowOfFlag = useCallback(
    (f: Flag): AssessmentRow | null => ov?.rows.find((r) => r.flags.some((x) => x.id === f.id)) ?? null,
    [ov],
  );
  const openRow = (row: AssessmentRow | null) => {
    setTab("assessments");
    setDialog({ row });
  };

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
    return error ? <div className="error-box">{error.msg} <Link to="/">Back to my courses</Link></div> : <p className="muted">Loading…</p>;

  const rec = v.record;
  const props = { rec, editable, focus, save, apply };
  const assessProps = { ...props, overview: ov, onEdit: openRow, onAdd: () => openRow(null) };
  const blocking = v.flags.filter((f) => f.status === "open" && f.severity !== "info").length;
  const indexed = progress?.materials.filter((m) => m.status === "indexed") ?? [];
  const items = progress?.items ?? [];
  const toReview = items.filter((i) => i.status === "suggested" || i.status === "under_review" || i.status === "needs_review");
  const approved = items.filter((i) => i.status === "approved");
  const step = !locked ? (v.can_lock ? 2 : 1)
    : v.export_count > 0 ? 5
    : approved.length > 0 ? 4
    : 3;

  return (
    <div>
      <div className="vhead">
        <div className="title">
          <h1>
            <span className="code" style={{ fontSize: 22 }}>{rec.course.code ?? "Unknown code"}</span>{" "}
            {rec.course.title ?? <span className="muted">Untitled</span>}
          </h1>
          <div className="meta">
            <span>{rec.offering.term ?? "Term not read"}</span>
            <span className={`pill ${v.status}`}>{STATUS_LABEL[v.status]}</span>
            {v.version_no && <span>Version {v.version_no}</span>}
            <span className="muted small">
              {v.origin === "upload" ? "Uploaded" : v.origin === "revision" ? `Revision of #${v.parent_version_id}` : `Rolled over from #${v.parent_version_id}`}
              {" · "}{fmtDate(v.created_at)}
            </span>
            {v.source_filename && (
              <button className="link small" onClick={() => api.downloadSource(id, v.source_filename!).catch(fail)}>
                {v.source_filename}
              </button>
            )}
          </div>
        </div>
        <div className="lockbar">
          {(v.status === "locked" || v.status === "superseded") && (
            <>
              <Link to={`/v/${id}/drafts`} className="btn primary"><Icon name="drafts" size={16} /> Open Draft Studio</Link>
              <button disabled={busy} onClick={() => act(() => api.revise(id), (r) => `/v/${r.id}`)}>Create new version</button>
              <button
                disabled={busy}
                onClick={() => {
                  const t = prompt("Roll over to which term? (e.g. Spring 2027)");
                  if (t) act(() => api.rollover(id, t), (r) => `/v/${r.id}`);
                }}
              >
                Roll over to another term
              </button>
            </>
          )}
          {editable && (
            <button
              className="danger"
              disabled={busy}
              onClick={() => {
                if (confirm("Discard this unlocked version? The uploaded file and edit log are deleted with it."))
                  act(async () => { await api.discard(id); nav("/"); });
              }}
            >
              Discard
            </button>
          )}
        </div>
      </div>

      <Steps current={step} />

      {locked && (
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
      )}

      {editable ? (
        <div className={`gate ${v.can_lock ? "ready" : ""}`}>
          <div className="grow">
            <strong>Gate 1 · Lock the working version</strong>
            <div className="small">
              {v.can_lock
                ? `Everything is settled. Locking makes this the working version of ${rec.course.code} for ${rec.offering.term}; drafts are generated only from locked versions.`
                : `${blocking} flag(s) still need settling: correct the field, or accept it as is with a reason.`}
            </div>
          </div>
          <button className="primary" disabled={!v.can_lock || busy}
            onClick={() => { if (confirm(`Lock ${rec.course.code} ${rec.offering.term ?? ""} as the working version?`)) act(() => api.lock(id)); }}>
            Lock working version
          </button>
        </div>
      ) : (
        <div className="gate locked">
          <div className="grow">
            <strong>{v.status === "locked" ? "Working version" : "Superseded"}</strong>
            <div className="small">
              {v.status === "locked"
                ? `Locked ${fmtDate(v.locked_at)}. Read-only — to change it, create a new version.`
                : "A newer version replaced this one. Kept for the audit trail."}
            </div>
          </div>
        </div>
      )}

      {diff && (
        <div className="gate">
          <div className="grow small">
            <strong>Compared with {diff.from_term ?? "the previous version"}:</strong>{" "}
            {[diff.diff.clos_added.length && `CLO ${diff.diff.clos_added.join(", ")} added`,
              diff.diff.clos_removed.length && `CLO ${diff.diff.clos_removed.join(", ")} removed`,
              Object.keys(diff.diff.clos_changed).length && `CLO ${Object.keys(diff.diff.clos_changed).join(", ")} reworded`,
              Object.keys(diff.diff.weights_changed).length && `${Object.keys(diff.diff.weights_changed).length} weight(s) changed`,
              diff.diff.weeks_changed.length && `topics changed in week(s) ${diff.diff.weeks_changed.join(", ")}`]
              .filter(Boolean).join("; ") || "no changes to CLOs, weights or topics"}.
            {diff.affected_item_ids.length > 0 && ` ${diff.affected_item_ids.length} approved item(s) tied to changed CLOs now need review.`}
          </div>
        </div>
      )}
      {editable && v.previous && v.previous.matching_settled_flags > 0 && (
        <div className="gate">
          <div className="grow small">
            You locked {rec.course.code} {v.previous.term} (v{v.previous.version_no}) before.{" "}
            {v.previous.matching_settled_flags} open flag(s) here were already settled there.
          </div>
          <button disabled={busy} onClick={() => act(() => api.carryOver(id, v.previous!.id))}>
            Carry over those settlements
          </button>
        </div>
      )}

      {error && (
        <div className="error-box" style={{ marginBottom: 14 }}>
          {error.msg}
          {error.items && <ul>{error.items.map((m, i) => <li key={i}>{m}</li>)}</ul>}
        </div>
      )}

      <SourceContext.Provider value={setSourcePtr}>
      <div className="layout">
        <div className="card">
          <nav className="tabs">
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
          {tab === "log" && <EditLogTab edits={edits} onExport={() => api.download(`/api/course-versions/${id}/edits.csv`, "edit_log.csv").catch(fail)} />}
        </div>
        <div>
          {sourcePtr && (
            <SourcePanel cvId={id} rec={rec} ptr={sourcePtr} onClose={() => setSourcePtr(null)}
              isPdf={(v.source_filename ?? "").toLowerCase().endsWith(".pdf")} />
          )}
          <FlagsPanel flags={v.flags} editable={editable} onResolve={resolve} onChoose={choose} onJump={jump}
            fixable={(f) => rowOfFlag(f) !== null} onFix={(f) => openRow(rowOfFlag(f))} />
        </div>
      </div>
      </SourceContext.Provider>
      {dialog && ov && (
        <AssessmentDialog ov={ov} rec={rec} row={dialog.row} onClose={() => setDialog(null)} onSave={apply} />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

/** After locking, what to do next, with live counts and a button for each step. */
function NextSteps({ id, materials, materialsTotal, drafts, toReview, approved, exports, loading }: {
  id: number; materials: number; materialsTotal: number; drafts: number; toReview: number;
  approved: number; exports: number; loading: boolean;
}) {
  const steps = [
    {
      title: "Add course materials",
      optional: true,
      done: materials > 0,
      status: loading ? "Checking…"
        : materials > 0 ? `${materials} material${materials === 1 ? "" : "s"} indexed`
        : materialsTotal > 0 ? `${materialsTotal} uploaded, none indexed yet`
        : "None yet",
      body: "Optional. With your slides and notes indexed, drafts follow your own wording and cite the piece they came from. Without them, drafts come from the syllabus alone.",
      to: `/v/${id}/materials`,
      action: materials > 0 ? "Manage materials" : "Add materials",
    },
    {
      title: "Generate drafts in Draft Studio",
      done: drafts > 0,
      status: loading ? "Checking…" : drafts > 0 ? `${drafts} draft${drafts === 1 ? "" : "s"}` : "None yet",
      body: "Choose the item type, the CLOs and the weeks. Everything the model produces stays a draft until you approve it.",
      to: `/v/${id}/drafts`,
      action: drafts > 0 ? "Open Draft Studio" : "Generate drafts",
    },
    {
      title: "Review each draft: approve, edit or reject",
      done: drafts > 0 && toReview === 0,
      status: loading ? "Checking…"
        : drafts === 0 ? "Nothing to review yet"
        : toReview > 0 ? `${toReview} waiting for review` : "All reviewed",
      body: "Quality checks run on every draft. A failed required check has to be fixed before the item can be approved.",
      to: `/v/${id}/drafts`,
      action: "Review drafts",
    },
    {
      title: "Export approved items, or build a quiz or exam",
      done: exports > 0,
      status: loading ? "Checking…"
        : approved === 0 ? "No approved items yet"
        : exports > 0 ? `${approved} approved · ${exports} export${exports === 1 ? "" : "s"} so far`
        : `${approved} approved, ready to export`,
      body: "Export gives you a question paper and a separate answer key, as DOCX or PDF. Assessment Builder assembles a form that matches a row of your syllabus.",
      to: `/v/${id}/builder`,
      action: "Open Assessment Builder",
    },
  ];
  return (
    <section className="card nextsteps">
      <h2>What to do next</h2>
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
                <span className={`pill ${s.done ? "locked" : ""}`}>{s.status}</span>
              </div>
              <p className="small muted">{s.body}</p>
            </div>
            <Link className="btn" to={s.to}>{s.action}</Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

const STEPS = ["Upload syllabus", "Settle flags", "Lock working version", "Generate & review drafts", "Export approved items"];

/** Where this course sits in the faculty workflow (handoff section 6). */
function Steps({ current }: { current: number }) {
  return (
    <ol className="steps" aria-label="Workflow">
      {STEPS.map((s, i) => (
        <li key={s} className={i < current ? "done" : i === current ? "now" : ""} aria-current={i === current ? "step" : undefined}>
          <span className="dot">{i < current ? <Icon name="check" size={13} /> : i + 1}</span>
          <span className="lbl">{s}</span>
        </li>
      ))}
    </ol>
  );
}
