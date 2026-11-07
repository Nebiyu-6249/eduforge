import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

interface Summary {
  drafts: number;
  approved: number;
  rejected: number;
  pending: number;
  approval_rate: number | null;
  median_edit_size: number | null;
  light_edit_rate: number | null;
  median_hours_to_review: number | null;
  rejection_reasons: string[];
}
interface Metrics {
  light_edit_threshold: number;
  overall: Summary;
  gate2_light_edit_rate: number | null;
  by_type: Record<string, Summary>;
  by_group: (Summary & { type: string; course: string; prompt_version: string })[];
}

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

/** Plan 2.11: team-only dashboard (not for faculty). */
export default function TeamMetrics() {
  const [m, setM] = useState<Metrics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.teamMetrics().then((x) => setM(x as Metrics)).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);
  if (err) return <div className="error-box">{err}</div>;
  if (!m) return <p className="muted">Loading…</p>;
  const g2 = m.gate2_light_edit_rate;
  return (
    <div className="stack">
      <h1>Team metrics</h1>
      <div className={`gate ${g2 != null && g2 >= 0.7 ? "ready" : ""}`}>
        <div className="grow">
          <strong>Gate 2: {pct(g2)} of approved drafts needed only light edits</strong>
          <div className="small">Target ≥70%. “Light” = edit size ≤ {m.light_edit_threshold} (set before the pilot starts).</div>
        </div>
      </div>
      <table className="list">
        <thead>
          <tr><th>Type</th><th>Course</th><th>Prompt</th><th>Drafts</th><th>Approved</th><th>Rejected</th><th>Approval</th>
            <th>Median edit</th><th>Light edits</th><th>Median h to review</th></tr>
        </thead>
        <tbody>
          {m.by_group.map((r) => (
            <tr key={`${r.type}-${r.course}-${r.prompt_version}`}>
              <td>{r.type}</td><td className="code">{r.course}</td><td className="code small">{r.prompt_version}</td>
              <td>{r.drafts}</td><td>{r.approved}</td><td>{r.rejected}</td><td>{pct(r.approval_rate)}</td>
              <td>{r.median_edit_size ?? "—"}</td><td>{pct(r.light_edit_rate)}</td><td>{r.median_hours_to_review ?? "—"}</td>
            </tr>
          ))}
          {m.by_group.length === 0 && <tr><td colSpan={10} className="muted">No drafts yet.</td></tr>}
        </tbody>
      </table>
      <div className="card">
        <h2>Recent rejection reasons</h2>
        <ul>{m.overall.rejection_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        {m.overall.rejection_reasons.length === 0 && <p className="muted">None yet.</p>}
      </div>
    </div>
  );
}
