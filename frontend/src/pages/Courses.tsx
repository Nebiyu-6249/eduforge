import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import { STATUS_LABEL, fmtDate } from "../components/util";
import type { VersionSummary } from "../types";

function termKey(t: string | null): number {
  const m = /(Spring|Summer|Fall|Winter)\s+(\d{4})/.exec(t ?? "");
  if (!m) return -1;
  const order: Record<string, number> = { Winter: 0, Spring: 1, Summer: 2, Fall: 3 };
  return Number(m[2]) * 10 + order[m[1]];
}

export default function Courses() {
  const [items, setItems] = useState<VersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [over, setOver] = useState(false);
  const [showOld, setShowOld] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const load = () =>
    api
      .list()
      .then(setItems)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function upload(f: File | undefined) {
    if (!f) return;
    setBusy(true);
    setError(null);
    try {
      const job = await api.upload(f);
      const done = await waitJob(job.id, (j) => setStage(j.message ?? ""));
      nav(`/v/${done.result!.course_version_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  const visible = (items ?? []).filter((v) => showOld || v.status !== "superseded");
  const groups = new Map<string, VersionSummary[]>();
  for (const v of visible) {
    const k = v.term ?? "Term not read yet";
    groups.set(k, [...(groups.get(k) ?? []), v]);
  }
  const ordered = [...groups.entries()].sort((a, b) => termKey(b[0]) - termKey(a[0]));
  const superseded = (items ?? []).filter((v) => v.status === "superseded").length;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h1>My courses</h1>
          <div className="muted">Upload a vetted syllabus, settle what the validator flags, then lock the working version for the term.</div>
        </div>
      </div>

      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(e.dataTransfer.files[0]);
        }}
      >
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          style={{ display: "none" }}
          onChange={(e) => upload(e.target.files?.[0])}
        />
        {busy ? (
          <div role="status">{stage || "Uploading…"}</div>
        ) : (
          <>
            <div style={{ marginBottom: 8 }}>
              <strong>Drop a vetted syllabus here</strong> <span className="muted">(PDF or DOCX)</span>
            </div>
            <button className="primary" onClick={() => input.current?.click()}>Choose file</button>
            <div className="small muted" style={{ marginTop: 8 }}>
              Course and term are read from the file. Syllabi must already be vetted by admin.
            </div>
          </>
        )}
      </div>
      {error && <div className="error-box" style={{ marginTop: 12 }}>{error}</div>}

      {items && items.length === 0 && <p className="muted" style={{ marginTop: 24 }}>No courses yet.</p>}

      {ordered.map(([term, vs]) => (
        <section className="term-group" key={term}>
          <h2>{term}</h2>
          <table className="list">
            <thead>
              <tr>
                <th style={{ width: 120 }}>Course</th>
                <th>Title</th>
                <th style={{ width: 130 }}>Status</th>
                <th style={{ width: 170 }}>Needs settling</th>
                <th style={{ width: 170 }}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {vs.map((v) => (
                <tr key={v.id} className="clickable" onClick={() => nav(`/v/${v.id}`)}>
                  <td className="code">{v.course_code ?? "—"}</td>
                  <td>
                    {v.course_title ?? <span className="muted">{v.source_filename}</span>}
                    {v.origin !== "upload" && <span className="small muted"> · {v.origin} of #{v.parent_version_id}</span>}
                  </td>
                  <td>
                    <span className={`pill ${v.status}`}>{STATUS_LABEL[v.status]}</span>
                    {v.version_no && <span className="small muted"> v{v.version_no}</span>}
                  </td>
                  <td>
                    {v.status === "locked" || v.status === "superseded" ? (
                      <span className="muted">—</span>
                    ) : v.open_blocking ? (
                      <span className="pill warning">{v.open_blocking} open</span>
                    ) : (
                      <span className="pill locked">Ready to lock</span>
                    )}
                  </td>
                  <td className="muted">{fmtDate(v.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {superseded > 0 && (
        <p style={{ marginTop: 16 }}>
          <button className="link" onClick={() => setShowOld(!showOld)}>
            {showOld ? "Hide" : "Show"} {superseded} superseded version{superseded > 1 ? "s" : ""}
          </button>
        </p>
      )}
    </div>
  );
}
