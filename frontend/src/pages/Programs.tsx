import { useEffect, useState } from "react";
import Icon from "../components/Icon";
import { api, ApiError } from "../api";

const SHORT: Record<string, string> = { high: "H", medium: "M", low: "L" };

/** Program-wide coverage (plan 3.11): PLO × course across locked syllabi of one term.
 * Also the main screen of the read-only QA/accreditation viewer (plan 3.12). */
export default function Programs({ qa = false }: { qa?: boolean }) {
  const [programs, setPrograms] = useState<{ id: number; name: string }[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [term, setTerm] = useState("");
  const [cov, setCov] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (qa ? api.qaPrograms() : api.programs()).then((p) => {
      setPrograms(p);
      if (p.length) setPid(p[0].id);
    }).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [qa]);
  useEffect(() => {
    if (pid == null) return;
    api.programCoverage(pid, term || undefined, qa).then(setCov).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [pid, term, qa]);

  return (
    <div className="stack">
      <h1 className="page-title"><Icon name="coverage" size={26} /> Program coverage</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        PLO × course, from every locked syllabus. PLOs are matched by program and number; where syllabi word a PLO
        differently, both wordings are shown (they are separate per-syllabus lists, D7).
      </p>
      <div className="row wrap">
        <label className="lbl" htmlFor="pg">Program</label>
        <select id="pg" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))} style={{ width: "auto" }}>
          {programs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <label className="lbl" htmlFor="tm">Term</label>
        <input id="tm" value={term} placeholder="All terms, or e.g. Fall 2026" onChange={(e) => setTerm(e.target.value)} style={{ width: 220 }} />
      </div>
      {err && <div className="error-box">{err}</div>}
      {cov && (
        <>
          <table className="grid">
            <thead>
              <tr><th>Course</th>{cov.plos.map((p: any) => <th key={p.number} className="c">PLO {p.number}</th>)}</tr>
            </thead>
            <tbody>
              {cov.courses.map((c: any) => (
                <tr key={c.course_version_id}>
                  <th>{c.code} <span className="small muted">{c.term}</span></th>
                  {cov.plos.map((p: any) => {
                    const cell = c.cells[String(p.number)];
                    return (
                      <td key={p.number} className="c" title={cell ? `CLO ${cell.clos.join(", ")}` : ""}>
                        {cell ? SHORT[cell.strength] : ""}{c.addressed.includes(p.number) ? " ✓" : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {cov.courses.length === 0 && <tr><td colSpan={cov.plos.length + 1} className="muted">No locked syllabi for this program{term ? ` in ${term}` : ""}.</td></tr>}
            </tbody>
          </table>
          <p className="small muted">H/M/L = strongest CLO→PLO mapping in that course; ✓ = marked “addressed”. Not covered: {cov.uncovered.length ? `PLO ${cov.uncovered.join(", ")}` : "none"}.</p>
          <div className="card">
            <h2>PLO wording by syllabus</h2>
            {cov.plos.map((p: any) => (
              <div key={p.number} style={{ marginBottom: 8 }}>
                <strong>PLO {p.number}</strong>
                {p.wordings.map((w: any, i: number) => (
                  <div key={i} className="small">{w.text} <span className="muted">— {w.courses.join(", ")}</span></div>
                ))}
                {p.wordings.length > 1 && <div className="small" style={{ color: "var(--warning)" }}>Worded differently across syllabi.</div>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** The whole app for a read-only QA/accreditation viewer: coverage and syllabi, never items or exams. */
export function QaApp({ name, onSignOut }: { name: string; onSignOut: () => void }) {
  const [syllabi, setSyllabi] = useState<any[]>([]);
  useEffect(() => {
    api.qaSyllabi().then(setSyllabi).catch(() => setSyllabi([]));
  }, []);
  return (
    <>
      <header className="topbar">
        <span className="brand">EduForge<small>QA / accreditation (read-only)</small></span>
        <span className="spacer" />
        <span className="who">{name}</span>
        <button onClick={onSignOut}>Sign out</button>
      </header>
      <main className="stack">
        <Programs qa />
        <div className="card">
          <h2>Locked syllabi</h2>
          <ul>{syllabi.map((s) => <li key={s.id}>{s.code} {s.title} · {s.term} · v{s.version_no}</li>)}</ul>
        </div>
      </main>
    </>
  );
}
