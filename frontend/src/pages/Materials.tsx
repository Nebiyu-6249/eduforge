import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import { fmtDate } from "../components/util";
import type { Material, VersionDetail } from "../types";

const KINDS: [Material["kind"], string][] = [
  ["slides", "Slides"],
  ["notes", "Notes"],
  ["past_exam", "Past exam"],
  ["textbook", "Textbook (commercial)"],
  ["other", "Other"],
];

const STATUS_PILL: Record<Material["status"], string> = {
  pending: "extracted",
  indexed: "locked",
  blocked: "warning",
  failed: "error",
};

/** Course materials library (plan 2.1–2.4): what drafts are grounded in. */
export default function Materials() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [items, setItems] = useState<Material[] | null>(null);
  const [kind, setKind] = useState<Material["kind"]>("slides");
  const [week, setWeek] = useState<string>("");
  const [licensed, setLicensed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = () => api.materials(cv).then(setItems).catch((e) => setErr(e.message));
  useEffect(() => {
    api.get(cv).then(setV).catch((e) => setErr(e.message));
    load();
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(label: string, fn: () => Promise<{ id: number } | void>) {
    setBusy(label);
    setErr(null);
    try {
      const job = await fn();
      if (job && "id" in job) await waitJob(job.id, (j) => setBusy(j.message ?? label));
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function upload(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      await run(`Indexing ${f.name}`, () =>
        api.uploadMaterial(cv, f, { kind, week_no: week ? Number(week) : null, licensed }),
      );
    }
    if (input.current) input.current.value = "";
  }

  if (!v) return err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>;
  const rec = v.record;
  const locked = v.status === "locked" || v.status === "superseded";

  return (
    <div className="stack">
      <div className="small">
        <Link to={`/v/${cv}`}>← {rec.course.code} {rec.offering.term}</Link> · <Link to={`/v/${cv}/drafts`}>Draft Studio</Link>
      </div>
      <h1>
        Course materials · <span className="code" style={{ fontSize: 22 }}>{rec.course.code}</span> {rec.course.title}
      </h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Drafts are grounded in these files: a request&apos;s CLOs and weeks pull the most relevant pieces into the prompt, and
        each draft records which pieces it used. Materials belong to the course, so later terms reuse them.
      </p>
      {!locked ? (
        <div className="gate">
          <div className="grow small">Lock this course version first; materials belong to the course.</div>
        </div>
      ) : (
        <div className="card stack">
          <h2>Add material</h2>
          <div className="req-grid">
            <div>
              <label className="lbl" htmlFor="m-kind">Kind</label>
              <select id="m-kind" value={kind} onChange={(e) => setKind(e.target.value as Material["kind"])}>
                {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="lbl" htmlFor="m-week">Week (optional)</label>
              <select id="m-week" value={week} onChange={(e) => setWeek(e.target.value)}>
                <option value="">Whole course</option>
                {rec.weekly.map((w) => (
                  <option key={w.week_no} value={w.week_no}>Week {w.week_no} · {w.topics[0] ?? ""}</option>
                ))}
              </select>
            </div>
            <div style={{ alignSelf: "end" }}>
              <label className="small row" style={{ gap: 6 }}>
                <input type="checkbox" checked={licensed} onChange={(e) => setLicensed(e.target.checked)} style={{ width: "auto" }} />
                The university holds a licence that allows this (needed for commercial textbooks)
              </label>
            </div>
            <div style={{ alignSelf: "end" }}>
              <input ref={input} type="file" multiple accept=".pdf,.pptx,.docx,.txt,.md" style={{ display: "none" }}
                onChange={(e) => upload(e.target.files)} />
              <button className="primary" disabled={!!busy} onClick={() => input.current?.click()}>Choose files</button>
            </div>
          </div>
          <div className="small muted">
            PDF, PPTX (with speaker notes), DOCX, TXT or MD. Past exams are never sent to a hosted model unless the deployment
            uses a no-retention provider; they stay in the local index.
          </div>
        </div>
      )}
      {busy && <div className="card small" role="status">{busy}</div>}
      {err && <div className="error-box">{err}</div>}
      <table className="list">
        <thead>
          <tr>
            <th>Title</th><th style={{ width: 120 }}>Kind</th><th style={{ width: 90 }}>Week</th>
            <th style={{ width: 160 }}>Status</th><th style={{ width: 160 }}>Indexed</th><th style={{ width: 200 }} />
          </tr>
        </thead>
        <tbody>
          {(items ?? []).map((m) => (
            <tr key={m.id}>
              <td>
                {m.title}
                {m.title !== m.filename && <div className="small muted">{m.filename}</div>}
                {m.error && <div className="small" style={{ color: "var(--warning)" }}>{m.error}</div>}
              </td>
              <td>{KINDS.find(([k]) => k === m.kind)?.[1]}</td>
              <td>{m.week_no ?? "—"}</td>
              <td>
                <span className={`pill ${STATUS_PILL[m.status]}`}>{m.status}</span>
                {m.status === "indexed" && <span className="small muted"> {m.chunk_count} chunks</span>}
              </td>
              <td className="small muted">{fmtDate(m.indexed_at)}</td>
              <td className="row">
                {m.kind === "textbook" && !m.licensed && (
                  <button className="icon" disabled={!!busy}
                    onClick={() => confirm("Confirm the university licence allows indexing this textbook?") &&
                      run("Indexing", () => api.updateMaterial(m.id, { licensed: true }))}>
                    Mark licensed
                  </button>
                )}
                <button className="icon" disabled={!!busy} onClick={() => run("Re-indexing", () => api.reindexMaterial(m.id))}>
                  Re-index
                </button>
                <button className="icon danger" disabled={!!busy}
                  onClick={() => confirm(`Delete ${m.title}?`) && run("Deleting", () => api.deleteMaterial(m.id))}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {items && items.length === 0 && (
            <tr><td colSpan={6} className="muted">No materials yet. Drafts will be marked “ungrounded” until you add some.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
