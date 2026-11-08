import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, uploadWithProgress, waitJob } from "../api";
import { announceJob, JOB_FINISHED } from "../components/Activity";
import Icon from "../components/Icon";
import UploadPanel from "../components/UploadPanel";
import { enqueue } from "../components/uploads";
import { fmtDate } from "../components/util";
import type { Job, Material, VersionDetail } from "../types";

const KINDS: [Material["kind"], string][] = [
  ["slides", "Slides"],
  ["notes", "Notes"],
  ["past_exam", "Past exam"],
  ["textbook", "Textbook (commercial)"],
  ["other", "Other"],
];

const STATUS: Record<Material["status"], [string, string]> = {
  pending: ["Reading", "info"],
  indexed: ["Ready", "ok"],
  blocked: ["Needs a licence", "attention"],
  failed: ["Couldn't read", "danger"],
};

/** Slides and materials (plan 2.1–2.4): what new questions follow. */
export default function Materials() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [items, setItems] = useState<Material[] | null>(null);
  const [kind, setKind] = useState<Material["kind"]>("slides");
  const [week, setWeek] = useState<string>("");
  const [licensed, setLicensed] = useState(false);
  const [maxMb, setMaxMb] = useState(20);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.materials(cv).then(setItems).catch((e) => setErr(e.message)), [cv]);
  useEffect(() => {
    api.get(cv).then(setV).catch((e) => setErr(e.message));
    api.limits().then((l) => setMaxMb(l.max_upload_mb)).catch(() => undefined);
    load();
  }, [cv, load]);
  // Reading finishes in the background, possibly after the teacher came back.
  useEffect(() => {
    window.addEventListener(JOB_FINISHED, load);
    return () => window.removeEventListener(JOB_FINISHED, load);
  }, [load]);

  async function run(label: string, fn: () => Promise<{ id: number } | void>) {
    setBusy(label);
    setErr(null);
    try {
      const job = await fn();
      if (job && "id" in job) {
        announceJob();
        await waitJob(job.id, (j) => setBusy(j.message ?? label));
      }
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  /* Every chosen file joins the queue at once; the choices above apply to the files added now. */
  function add(files: FileList | File[] | null) {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    const meta = { kind, week_no: week ? Number(week) : null, licensed };
    enqueue(`materials:${cv}`, list, (file, onProgress) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", meta.kind);
      if (meta.week_no) fd.append("week_no", String(meta.week_no));
      fd.append("licensed", String(meta.licensed));
      return uploadWithProgress<Job>(`/api/course-versions/${cv}/materials`, fd, onProgress);
    }, () => load(), maxMb * 1048576);
    load();
    if (input.current) input.current.value = "";
  }

  if (!v) return err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>;
  const rec = v.record;
  const locked = v.status === "locked" || v.status === "superseded";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1 className="page-title"><Icon name="materials" size={26} /> Slides and materials</h1>
          <p className="lede">Add your slides and notes. New questions will follow your own wording.</p>
        </div>
      </div>

      {!locked ? (
        <div className="gate"><div className="grow small">Confirm the syllabus first; slides belong to the course.</div></div>
      ) : (
        <section className={`card stack drop-card ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setOver(false); }}
          onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
          <div className="card-head">
            <h2>Add files</h2>
            <span className="small muted">or drop them anywhere on this box</span>
          </div>
          <div className="req-grid">
            <div>
              <label className="lbl" htmlFor="m-kind">What they are</label>
              <select id="m-kind" value={kind} onChange={(e) => setKind(e.target.value as Material["kind"])}>
                {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="lbl" htmlFor="m-week">Week</label>
              <select id="m-week" value={week} onChange={(e) => setWeek(e.target.value)}>
                <option value="">Whole course</option>
                {rec.weekly.map((w) => (
                  <option key={w.week_no} value={w.week_no}>Week {w.week_no} · {w.topics[0] ?? ""}</option>
                ))}
              </select>
            </div>
            {kind === "textbook" && (
              <div style={{ alignSelf: "end" }}>
                <label className="small row" style={{ gap: 6 }}>
                  <input type="checkbox" checked={licensed} onChange={(e) => setLicensed(e.target.checked)} style={{ width: "auto" }} />
                  The university's licence allows this textbook to be used
                </label>
              </div>
            )}
            <div style={{ alignSelf: "end" }}>
              <input ref={input} id="m-files" type="file" multiple accept=".pdf,.pptx,.docx,.txt,.md" className="sr-only"
                aria-label="Choose files to add" tabIndex={-1}
                onChange={(e) => add(e.target.files)} />
              <button className="primary" onClick={() => input.current?.click()}>
                <Icon name="upload" size={16} /> Choose files
              </button>
            </div>
          </div>
          <p className="hint">
            PDF, PowerPoint (speaker notes included), Word or text files, up to {maxMb} MB each. Choose as many as you like;
            they upload together. Past exams stay inside EduForge's own index.
          </p>
        </section>
      )}

      <UploadPanel scope={`materials:${cv}`} title="Uploading" />
      {busy && <div className="card small" role="status">{busy}</div>}
      {err && <div className="error-box">{err}</div>}

      <section className="card flush">
        <table className="grid">
          <caption className="sr-only">Files added for this course</caption>
          <thead>
            <tr><th>File</th><th>What</th><th>Week</th><th>Status</th><th>Added</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {(items ?? []).map((m) => {
              const [label, tone] = STATUS[m.status];
              return (
                <tr key={m.id}>
                  <td>
                    {m.title}
                    {m.title !== m.filename && <div className="small muted">{m.filename}</div>}
                    {m.error && <div className="small err-text">{m.error}</div>}
                  </td>
                  <td>{KINDS.find(([k]) => k === m.kind)?.[1]}</td>
                  <td className="num">{m.week_no ?? "Whole course"}</td>
                  <td><span className={`pill ${tone}`}>{label}</span></td>
                  <td className="num small muted">{fmtDate(m.indexed_at ?? m.created_at)}</td>
                  <td className="num">
                    <span className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
                      {m.kind === "textbook" && !m.licensed && (
                        <button className="link small" disabled={!!busy}
                          onClick={() => confirm("Confirm the university's licence allows this textbook to be used?") &&
                            run("Reading the file", () => api.updateMaterial(m.id, { licensed: true }))}>
                          Mark as licensed
                        </button>
                      )}
                      <button className="link small danger-text" disabled={!!busy}
                        onClick={() => confirm(`Remove ${m.title}? Questions already written keep their wording.`) &&
                          run("Removing", () => api.deleteMaterial(m.id))}>
                        Remove
                      </button>
                      <details className="more-menu">
                        <summary className="link small">More</summary>
                        <div className="more-pop">
                          <button disabled={!!busy} onClick={() => run("Reading the file again", () => api.reindexMaterial(m.id))}>
                            Read again
                          </button>
                        </div>
                      </details>
                    </span>
                  </td>
                </tr>
              );
            })}
            {items && items.length === 0 && (
              <tr><td colSpan={6} className="muted">Nothing added yet. Until you add slides, questions are written from the syllabus alone.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
