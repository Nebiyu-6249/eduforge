import { useEffect, useState } from "react";
import Icon from "../components/Icon";
import { useParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import { fmtDate } from "../components/util";
import type { VersionDetail } from "../types";

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

/** Blackboard integration (plan 14.8): connect → link course → push approved forms → pull submissions →
 * dry-run → write confirmed grades. */
export default function Blackboard() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [status, setStatus] = useState<{ mode: string; connected: boolean } | null>(null);
  const [grading, setGrading] = useState(false);
  const [courses, setCourses] = useState<any[]>([]);
  const [links, setLinks] = useState<any[]>([]);
  const [forms, setForms] = useState<any[]>([]);
  const [sections, setSections] = useState<any[]>([]);
  const [pick, setPick] = useState({ course: "", section: "" });
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadLinks = () => api.lmsLinks(cv).then(setLinks).catch((e) => setErr(errText(e)));
  const loadAll = (s: { mode: string; connected: boolean }) => {
    if (s.mode === "off" || !s.connected) return;
    api.lmsCourses().then(setCourses).catch((e) => setErr(errText(e)));
    loadLinks();
  };
  useEffect(() => {
    api.get(cv).then(setV).catch((e) => setErr(errText(e)));
    api.forms(cv).then((f) => setForms(f.filter((x: any) => x.status === "approved"))).catch(() => setForms([]));
    api.gradingStatus().then((g) => {
      setGrading(g.enabled);
      if (g.enabled) api.gradingSections(cv).then((s) => setSections(s.filter((x: any) => !x.calibration))).catch(() => setSections([]));
    }).catch(() => setGrading(false));
    api.lmsStatus().then((s) => { setStatus(s); loadAll(s); }).catch((e) => setErr(errText(e)));
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

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
  return (
    <div className="stack">
      <h1 className="page-title"><Icon name="lms" size={26} /> Blackboard · {rec.course.code}</h1>
      {err && <div className="error-box" role="alert">{err}</div>}
      {note && <div className="card small" role="status">{note}</div>}
      {status.mode === "off" ? (
        <div className="card">
          <p>Blackboard integration is <strong>off</strong> until IT registers the Blackboard REST application (plan 13.C).
            Until then, export forms as QTI from the Assessment Builder, and release grades as a Grade Center CSV from Grading Assist.</p>
        </div>
      ) : (
        <>
          <div className="card row wrap">
            <span>{status.connected ? "Your Blackboard account is connected." : "Connect your Blackboard account: actions run as you."}</span>
            {status.mode === "mock" && <span className="pill info">mock Blackboard</span>}
            <span style={{ flex: 1 }} />
            {status.connected ? (
              <button disabled={busy} onClick={() => run(async () => { await api.lmsDisconnect(); setStatus({ ...status, connected: false }); })}>Disconnect</button>
            ) : (
              <button className="primary" disabled={busy} onClick={() => run(async () => {
                const r = await api.lmsConnect();
                if (r.authorize_url) { window.location.href = r.authorize_url; return; }
                const s = { ...status, connected: true };
                setStatus(s);
                loadAll(s);
              })}>Connect Blackboard</button>
            )}
          </div>

          {status.connected && (
            <div className="card stack">
              <h2>Link a Blackboard course</h2>
              <p className="small muted" style={{ marginTop: 0 }}>Only your own Blackboard courses are listed. The course code and term must
                match this syllabus ({rec.course.code}, {rec.offering.term}).</p>
              <div className="row wrap">
                <select aria-label="Blackboard course" value={pick.course} onChange={(e) => setPick({ ...pick, course: e.target.value })} style={{ width: "auto" }}>
                  <option value="">Choose a course…</option>
                  {courses.map((c) => <option key={c.id} value={c.id}>{c.course_id} · {c.name}{c.term ? ` · ${c.term}` : ""}</option>)}
                </select>
                {sections.length > 0 && (
                  <select aria-label="Section" value={pick.section} onChange={(e) => setPick({ ...pick, section: e.target.value })} style={{ width: "auto" }}>
                    <option value="">No section</option>
                    {sections.map((s) => <option key={s.id} value={s.id}>Section {s.label}</option>)}
                  </select>
                )}
                <button className="primary" disabled={busy || !pick.course}
                  onClick={() => run(async () => { await api.lmsLink(cv, pick.course, pick.section ? Number(pick.section) : null); await loadLinks(); }, "Linked.")}>
                  Link
                </button>
              </div>
            </div>
          )}

          {links.map((ln) => <LinkCard key={ln.id} ln={ln} forms={forms} sections={sections} grading={grading}
            run={run} busy={busy} reload={loadLinks} />)}
        </>
      )}
    </div>
  );
}

type Run = (fn: () => Promise<unknown>, done?: string) => Promise<void>;

function LinkCard({ ln, forms, sections, grading, run, busy, reload }: {
  ln: any; forms: any[]; sections: any[]; grading: boolean; run: Run; busy: boolean; reload: () => void;
}) {
  const [cols, setCols] = useState<any[] | null>(null);
  const [diff, setDiff] = useState<Record<number, any>>({});
  const [overwrite, setOverwrite] = useState<Record<number, string[]>>({});
  const [syncs, setSyncs] = useState<any[]>([]);
  const loadSyncs = () => api.lmsSyncs(ln.id).then(setSyncs).catch(() => setSyncs([]));
  useEffect(() => { loadSyncs(); }, [ln.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const section = ln.section_id ? sections.find((s) => s.id === ln.section_id) : null;
  const colFor = (fid: number) => ln.columns.find((c: any) => c.form_id === fid);
  const after = () => { reload(); loadSyncs(); };

  return (
    <div className="card stack">
      <h2>{ln.lms_course_code} <span className="small muted">{ln.lms_course_name}{ln.lms_term ? ` · ${ln.lms_term}` : ""}
        {section ? ` · section ${section.label}` : ""}</span></h2>
      <div className="row">
        <span className="small muted">Linked {fmtDate(ln.linked_at)}</span>
        <span style={{ flex: 1 }} />
        <button disabled={busy} onClick={() => confirm("Remove this link? Nothing in Blackboard changes.") && run(async () => { await api.lmsUnlink(ln.id); reload(); })}>Unlink</button>
      </div>
      {!forms.length && <p className="muted small">No approved forms yet.</p>}
      <table className="grid">
        <thead><tr><th>Approved form</th><th>Grade Center column</th><th>Actions</th></tr></thead>
        <tbody>
          {forms.map((f) => {
            const col = colFor(f.id);
            const d = diff[f.id];
            return (
              <tr key={f.id}>
                <th>{f.assessment_name} · version {f.version_label}</th>
                <td>
                  {col ? col.column_name : <span className="muted">none yet</span>}
                  {!col && cols && (
                    <select aria-label={`Existing column for ${f.assessment_name} ${f.version_label}`} defaultValue=""
                      onChange={(e) => e.target.value && run(async () => { await api.lmsAttach(ln.id, f.id, e.target.value); after(); }, "Column attached.")}
                      style={{ width: "auto", marginLeft: 8 }}>
                      <option value="">…or use an existing column</option>
                      {cols.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  )}
                </td>
                <td className="stack">
                  <div className="row wrap">
                    <button disabled={busy} onClick={() => run(async () => { const s = await api.lmsPush(ln.id, f.id); after(); return s; },
                      "Column ready in Blackboard. Import the form's QTI export (Assessment Builder) as a test or pool: Blackboard's API can't import pools.")}>
                      {col ? "Push again" : "Push to Blackboard"}
                    </button>
                    {!col && !cols && <button disabled={busy} onClick={() => run(async () => setCols(await api.lmsColumns(ln.id)))}>Pick existing column</button>}
                    {grading && col && (
                      <>
                        <button disabled={busy || !ln.section_id} title={ln.section_id ? "" : "Link with a section to pull submissions"}
                          onClick={() => run(async () => {
                            const r = await api.lmsPull(ln.id, f.id, ln.section_id);
                            await waitJob(r.job.id);
                            after();
                            return r;
                          }, "Submissions pulled and anonymised; suggestions are ready in Grading Assist.")}>Pull submissions</button>
                        <button disabled={busy || !ln.section_id}
                          onClick={() => run(async () => { setDiff({ ...diff, [f.id]: await api.lmsPassback(ln.id, f.id, ln.section_id, true) }); loadSyncs(); })}>
                          Preview grade upload
                        </button>
                      </>
                    )}
                  </div>
                  {d && (
                    <div className="stack small">
                      <table className="grid">
                        <thead><tr><th>Student</th><th>ID</th><th className="c">In Blackboard before</th><th className="c">Confirmed</th><th>Action</th></tr></thead>
                        <tbody>
                          {d.summary.rows.map((r: any) => {
                            const conflict = r.action.startsWith("changed");
                            const ow = overwrite[f.id] ?? [];
                            return (
                              <tr key={r.pseudonym}>
                                <td>{r.pseudonym}</td><td>{r.student_id}</td>
                                <td className="c">{r.current ?? "—"}</td><td className="c">{r.new}</td>
                                <td>{r.result ?? r.action}
                                  {conflict && !r.result && (
                                    <label style={{ marginLeft: 8 }}><input type="checkbox" style={{ width: "auto" }} checked={ow.includes(r.pseudonym)}
                                      onChange={(e) => setOverwrite({ ...overwrite, [f.id]: e.target.checked ? [...ow, r.pseudonym] : ow.filter((x) => x !== r.pseudonym) })} /> overwrite</label>
                                  )}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {d.kind === "grade_dry_run" && (
                        <div><button className="primary" disabled={busy}
                          onClick={() => run(async () => {
                            const r = await api.lmsPassback(ln.id, f.id, ln.section_id, false, overwrite[f.id] ?? []);
                            setDiff({ ...diff, [f.id]: r });
                            loadSyncs();
                          }, "Grades written to Blackboard.")}>Write confirmed grades to Blackboard</button></div>
                      )}
                      {d.kind === "grade_push" && d.status === "partial" && <div className="error-box">Some writes failed; run it again: only missing grades are written.</div>}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {syncs.length > 0 && (
        <details>
          <summary className="small">Sync log ({syncs.length})</summary>
          <ul className="small">{syncs.map((s) => (
            <li key={s.id}>{fmtDate(s.at)} · {s.kind.replace(/_/g, " ")} · <span className={`pill ${s.status === "ok" ? "locked" : "warning"}`}>{s.status}</span> · {s.requests} request(s)
              {s.summary?.counts && ` · ${Object.entries(s.summary.counts).map(([k, n]) => `${n} ${k}`).join(", ")}`}
              {s.summary?.stored !== undefined && ` · ${s.summary.stored} of ${s.summary.blackboard_students} students stored`}</li>))}</ul>
        </details>
      )}
    </div>
  );
}
