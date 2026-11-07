import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import { fmtDate } from "../components/util";
import Icon from "../components/Icon";
import type { Status, VersionSummary } from "../types";

/** Plain words for each state of a syllabus. */
const STATE: Record<Status, { label: string; tone: string }> = {
  extracted: { label: "Being checked", tone: "info" },
  in_review: { label: "Being checked", tone: "info" },
  locked: { label: "Confirmed", tone: "ok" },
  superseded: { label: "Replaced", tone: "neutral" },
};

function termKey(t: string | null): number {
  const m = /(Spring|Summer|Fall|Winter)\s+(\d{4})/.exec(t ?? "");
  if (!m) return -1;
  const order: Record<string, number> = { Winter: 0, Spring: 1, Summer: 2, Fall: 3 };
  return Number(m[2]) * 10 + order[m[1]];
}

type Sort = "updated" | "course" | "term";

interface Props {
  /** "questions" and "grading" turn the page into a course chooser for those
   *  sections, which only make sense inside one course. */
  pick?: "questions" | "grading";
}

export default function Courses({ pick }: Props) {
  const [items, setItems] = useState<VersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [over, setOver] = useState(false);
  const [showOld, setShowOld] = useState(false);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("updated");
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const load = () => api.list().then(setItems).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

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

  const rows = useMemo(() => {
    let xs = (items ?? []).filter((v) => showOld || v.status !== "superseded");
    if (pick) xs = xs.filter((v) => v.status === "locked");
    const needle = q.trim().toLowerCase();
    if (needle) {
      xs = xs.filter((v) => `${v.course_code ?? ""} ${v.course_title ?? ""} ${v.term ?? ""}`
        .toLowerCase().includes(needle));
    }
    const by: Record<Sort, (a: VersionSummary, b: VersionSummary) => number> = {
      updated: (a, b) => b.updated_at.localeCompare(a.updated_at),
      course: (a, b) => (a.course_code ?? "").localeCompare(b.course_code ?? ""),
      term: (a, b) => termKey(b.term) - termKey(a.term) || (a.course_code ?? "").localeCompare(b.course_code ?? ""),
    };
    return [...xs].sort(by[sort]);
  }, [items, showOld, q, sort, pick]);

  const superseded = (items ?? []).filter((v) => v.status === "superseded").length;

  if (pick) {
    const where = pick === "questions" ? "Question bank" : "Marking";
    const what = pick === "questions"
      ? "Questions belong to a course. Choose the course whose question bank you want to open."
      : "Marking belongs to a course. Choose the course whose marks you want to work on.";
    return (
      <div className="stack">
        <div className="page-head">
          <div>
            <h1>{where}</h1>
            <p className="lede">{what}</p>
          </div>
        </div>
        {items === null ? <p className="muted">Loading your courses…</p> : rows.length === 0 ? (
          <div className="empty">
            <h3>No confirmed syllabus yet</h3>
            <p>
              {where} opens once a syllabus is confirmed for the term. Upload a syllabus, settle anything the
              tool lists, then confirm it.
            </p>
            <Link className="btn primary" to="/courses">Go to my courses</Link>
          </div>
        ) : (
          <div className="pick-grid">
            {rows.map((v) => (
              <Link key={v.id} className="pick" to={`/v/${v.id}/${pick}`}>
                <b>{v.course_code}</b>
                <span>{v.course_title}</span>
                <span style={{ display: "block", marginTop: 6 }}>{v.term}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>My courses</h1>
          <p className="lede">
            One syllabus per course and term. Upload the version your department has approved; EduForge reads the
            course from it and lists anything that does not add up.
          </p>
        </div>
        <div className="actions">
          <button className="primary" disabled={busy} onClick={() => input.current?.click()}>
            <Icon name="plus" size={16} /> Upload a syllabus
          </button>
        </div>
      </div>

      <input
        ref={input}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        style={{ display: "none" }}
        onChange={(e) => upload(e.target.files?.[0])}
      />

      {(busy || (items && items.length === 0)) && (
        <div
          className={`dropzone ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}
        >
          {busy ? (
            <div role="status"><div className="spinner" aria-hidden="true" />{stage || "Reading the file…"}</div>
          ) : (
            <>
              <div className="muted" style={{ marginBottom: 8 }}><Icon name="upload" size={30} /></div>
              <h3>Drop a syllabus here, or choose a file</h3>
              <p className="muted small" style={{ maxWidth: "52ch", margin: "8px auto 16px" }}>
                A PDF or Word file. The course code, the term, the learning outcomes and the weekly plan are
                all read from it, so there is nothing to type in.
              </p>
              <button className="primary" onClick={() => input.current?.click()}>Choose a file</button>
            </>
          )}
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {items === null && !error && <p className="muted">Loading your courses…</p>}

      {items && items.length > 0 && (
        <>
          <div className="row wrap between">
            <div className="row">
              <label className="sr-only" htmlFor="course-filter">Filter courses</label>
              <input id="course-filter" type="search" value={q} placeholder="Filter by code, title or term"
                style={{ width: 280 }} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="row">
              <label className="small muted" htmlFor="course-sort">Sort by</label>
              <select id="course-sort" value={sort} style={{ width: "auto" }}
                onChange={(e) => setSort(e.target.value as Sort)}>
                <option value="updated">Last changed</option>
                <option value="course">Course code</option>
                <option value="term">Term</option>
              </select>
            </div>
          </div>

          <div className="scroll-x">
            <table className="list">
              <caption className="sr-only">Your syllabuses</caption>
              <thead>
                <tr>
                  <th style={{ width: 130 }}>Course</th>
                  <th>Title</th>
                  <th style={{ width: 120 }}>Term</th>
                  <th style={{ width: 140 }}>State</th>
                  <th style={{ width: 190 }}>What it needs</th>
                  <th style={{ width: 170 }}>Last changed</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((v) => (
                  <tr key={v.id} className="clickable" tabIndex={0} onClick={() => nav(`/v/${v.id}`)}
                    onKeyDown={(e) => { if (e.key === "Enter") nav(`/v/${v.id}`); }}
                    aria-label={`Open ${v.course_code ?? v.source_filename} ${v.term ?? ""}`}>
                    <td className="code">{v.course_code ?? "Not read"}</td>
                    <td>
                      {v.course_title ?? <span className="muted">{v.source_filename}</span>}
                      {v.origin !== "upload" && (
                        <span className="small muted"> · {v.origin === "revision" ? "new version" : "rolled over"}</span>
                      )}
                    </td>
                    <td>{v.term ?? <span className="muted">Not read</span>}</td>
                    <td><span className={`pill ${STATE[v.status].tone}`}>{STATE[v.status].label}</span></td>
                    <td>
                      {v.status === "locked" || v.status === "superseded" ? (
                        <span className="muted">Nothing</span>
                      ) : v.open_blocking ? (
                        <span className="pill attention">
                          {v.open_blocking} thing{v.open_blocking === 1 ? "" : "s"} to check
                        </span>
                      ) : (
                        <span className="pill brand">Ready to confirm</span>
                      )}
                    </td>
                    <td className="muted small">{fmtDate(v.updated_at)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={6} className="muted">Nothing matches “{q}”.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {superseded > 0 && (
        <p>
          <button className="link" onClick={() => setShowOld(!showOld)}>
            {showOld ? "Hide" : "Show"} {superseded} replaced version{superseded > 1 ? "s" : ""}
          </button>
        </p>
      )}
    </div>
  );
}
