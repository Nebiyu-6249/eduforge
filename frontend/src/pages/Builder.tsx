import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { fmtDate } from "../components/util";
import type { VersionDetail } from "../types";

const TYPES = ["mcq", "short_answer", "problem", "code_exercise", "practice_set", "case_study"];
const TYPE_LABEL: Record<string, string> = {
  mcq: "MCQ", short_answer: "Short answer", problem: "Problem", code_exercise: "Code", practice_set: "Practice set",
  case_study: "Case study",
};

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

/** Assessment Builder (plan 3.1–3.6): blueprint → forms (parallel versions) → review → approve → export. */
export default function Builder() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [bp, setBp] = useState<any | null>(null);
  const [versions, setVersions] = useState(1);
  const [sections, setSections] = useState("");
  const [forms, setForms] = useState<any[]>([]);
  const [pool, setPool] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () => {
    api.forms(cv).then(setForms).catch((e) => setErr(errText(e)));
    api.pool(cv).then(setPool).catch(() => setPool([]));
  };
  useEffect(() => {
    api.get(cv).then(setV).catch((e) => setErr(errText(e)));
    api.assessments(cv).then(setRows).catch((e) => setErr(errText(e)));
    reload();
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!v) return err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>;
  const rec = v.record;
  const weeks = rec.weekly.map((w) => w.week_no);

  return (
    <div className="stack">
      <div className="small">
        <Link to={`/v/${cv}`}>← {rec.course.code} {rec.offering.term}</Link> · <Link to={`/v/${cv}/drafts`}>Draft Studio</Link> · <Link to={`/v/${cv}/grading`}>Grading Assist</Link>
      </div>
      <h1>Assessment Builder · <span className="code" style={{ fontSize: 22 }}>{rec.course.code}</span></h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Build a quiz or exam from your <strong>approved</strong> items to match a row of the locked syllabus. Forms are drafts until
        you approve them; only approved forms export.
      </p>

      <div className="card stack">
        <h2>1 · Pick the assessment</h2>
        <div className="row wrap">
          {rows.map((r, i) => (
            <button key={i} disabled={busy} onClick={() => run(async () => setBp(await api.blueprint(cv, r.name, r.week)))}>
              {r.name}{r.week ? ` · wk ${r.week}` : ""}{r.weight_pct != null ? ` · ${r.weight_pct}%` : ""}
            </button>
          ))}
        </div>
      </div>

      {bp && (
        <div className="card stack">
          <h2>2 · Blueprint for {bp.assessment}</h2>
          <div className="req-grid">
            <div>
              <label className="lbl" htmlFor="bp-min">Minutes (0 = take-home)</label>
              <input id="bp-min" type="number" value={bp.minutes} onChange={(e) => setBp({ ...bp, minutes: Number(e.target.value) })} />
            </div>
            <div>
              <label className="lbl" htmlFor="bp-pts">Total points</label>
              <input id="bp-pts" type="number" value={bp.total_points} onChange={(e) => setBp({ ...bp, total_points: Number(e.target.value) })} />
            </div>
            <div>
              <label className="lbl" htmlFor="bp-ver">Parallel versions</label>
              <input id="bp-ver" type="number" min={1} max={8} value={versions} onChange={(e) => setVersions(Math.max(1, Math.min(8, Number(e.target.value) || 1)))} />
            </div>
            <div>
              <label className="lbl" htmlFor="bp-sec">Sections (comma-separated, optional)</label>
              <input id="bp-sec" value={sections} placeholder="e.g. 3:00, 4:30" onChange={(e) => setSections(e.target.value)} />
            </div>
          </div>
          <div>
            <span className="lbl">Items by type</span>
            <div className="row wrap">
              {TYPES.map((t) => (
                <label key={t} className="small row" style={{ gap: 4 }}>
                  {TYPE_LABEL[t]}
                  <input type="number" min={0} style={{ width: 64 }} aria-label={`${TYPE_LABEL[t]} count`}
                    value={bp.types[t] ?? 0} onChange={(e) => setBp({ ...bp, types: { ...bp.types, [t]: Number(e.target.value) } })} />
                </label>
              ))}
            </div>
          </div>
          <div>
            <span className="lbl">Weeks covered</span>
            <div className="week-picks">
              {weeks.map((w) => (
                <button key={w} type="button" className={bp.weeks.includes(w) ? "on" : ""}
                  onClick={() => setBp({ ...bp, weeks: bp.weeks.includes(w) ? bp.weeks.filter((x: number) => x !== w) : [...bp.weeks, w].sort((a: number, b: number) => a - b) })}>
                  {w}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span className="lbl">CLO shares</span>
            <div className="row wrap">
              {rec.clos.map((c) => (
                <label key={c.number} className="small row" style={{ gap: 4 }} title={c.text}>
                  CLO {c.number}
                  <input type="number" step="0.05" min={0} max={1} style={{ width: 72 }} aria-label={`CLO ${c.number} share`}
                    value={bp.clo_shares[String(c.number)] ?? 0}
                    onChange={(e) => {
                      const shares = { ...bp.clo_shares, [String(c.number)]: Number(e.target.value) };
                      if (!Number(e.target.value)) delete shares[String(c.number)];
                      setBp({ ...bp, clo_shares: shares });
                    }} />
                </label>
              ))}
            </div>
          </div>
          <div className="row">
            <button className="primary" disabled={busy}
              onClick={() => run(async () => {
                await api.buildForms(cv, { blueprint: bp, versions, sections: sections ? sections.split(",").map((s) => s.trim()) : undefined });
                reload();
              })}>
              {busy ? "Building…" : `Build ${versions} form${versions > 1 ? "s" : ""}`}
            </button>
            <span className="small muted">Items used in the last {bp.avoid_used_in_last_terms} term(s) and near-duplicates are skipped.</span>
          </div>
        </div>
      )}

      {err && <div className="error-box">{err}</div>}

      {forms.map((f) => (
        <FormCard key={f.id} f={f} pool={pool} busy={busy} run={run} reload={reload} />
      ))}
    </div>
  );
}

function FormCard({ f, pool, busy, run, reload }: { f: any; pool: any[]; busy: boolean; run: (fn: () => Promise<unknown>) => Promise<void>; reload: () => void }) {
  const [key, setKey] = useState(false);
  const cov = f.coverage;
  const onForm = new Set(f.items.map((i: any) => i.item_id));
  const move = (idx: number, d: number) => {
    const ids = f.items.map((i: any) => i.item_id);
    const j = idx + d;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    run(async () => { await api.editForm(f.id, { action: "reorder", item_ids: ids }); reload(); });
  };
  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>{f.assessment_name} · version {f.version_label}{f.section ? ` · section ${f.section}` : ""}</h2>
        <span className={`pill ${f.status === "approved" ? "locked" : "in_review"}`}>{f.status}</span>
      </div>
      <div className="small muted">
        {cov.items}/{cov.target_items} items · {cov.points} points · {cov.minutes} min{cov.minutes_cap ? ` of ${cov.minutes_cap}` : ""} ·
        CLOs {Object.entries(cov.clos).map(([c, x]: any) => `${c}: ${x.have}/${x.want}`).join(", ")}
        {f.approved_by && ` · approved by ${f.approved_by}, ${fmtDate(f.approved_at)}`}
      </div>
      {f.gaps.length > 0 && (
        <div className="gate">
          <div className="grow small">
            {f.gaps.map((g: any, i: number) => (
              <div key={i}>{g.warning ?? `${g.reason}: ${g.count} more ${g.type ? g.type.replace("_", " ") : "item"}${g.count > 1 ? "s" : ""} for CLO ${g.clo_numbers.join(", ")}${g.weeks?.length ? ` (weeks ${g.weeks[0]}–${g.weeks[g.weeks.length - 1]})` : ""}`}</div>
            ))}
            <div className="muted">Generate the missing items in Draft Studio, approve them, then build again.</div>
          </div>
        </div>
      )}
      <table className="grid">
        <thead><tr><th style={{ width: 40 }}>#</th><th>Item</th><th style={{ width: 90 }}>Type</th><th style={{ width: 70 }}>CLO</th><th style={{ width: 50 }}>Wk</th><th style={{ width: 80 }}>Points</th><th style={{ width: 210 }} /></tr></thead>
        <tbody>
          {f.items.map((it: any, idx: number) => (
            <tr key={it.item_id}>
              <td>{it.position}</td>
              <td className="small">#{it.item_id} {it.summary}{it.status !== "approved" && <span className="pill error"> {it.status}</span>}</td>
              <td className="small">{TYPE_LABEL[it.type] ?? it.type}</td>
              <td>{it.clo_numbers.join(", ")}</td>
              <td>{it.week_no ?? "—"}</td>
              <td>
                <input type="number" step="0.5" min={0} defaultValue={it.points} aria-label={`Points for item ${it.item_id}`} style={{ width: 70 }}
                  onBlur={(e) => Number(e.target.value) !== it.points && run(async () => { await api.editForm(f.id, { action: "points", item_id: it.item_id, points: Number(e.target.value) }); reload(); })} />
              </td>
              <td className="row">
                <button className="icon" aria-label="Move up" disabled={busy || idx === 0} onClick={() => move(idx, -1)}>↑</button>
                <button className="icon" aria-label="Move down" disabled={busy || idx === f.items.length - 1} onClick={() => move(idx, 1)}>↓</button>
                <select aria-label={`Swap item ${it.item_id}`} value="" disabled={busy}
                  onChange={(e) => e.target.value && run(async () => { await api.editForm(f.id, { action: "swap", item_id: it.item_id, replace_with: Number(e.target.value) }); reload(); })}>
                  <option value="">Swap…</option>
                  {pool.filter((p) => p.type === it.type && !onForm.has(p.item_id)).map((p) => (
                    <option key={p.item_id} value={p.item_id}>#{p.item_id} CLO {p.clo_numbers.join(",")} · {p.summary.slice(0, 50)}{p.mine ? "" : " (shared)"}</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row wrap">
        {f.status !== "approved" && <button className="primary" disabled={busy || !f.items.length} onClick={() => run(async () => { await api.editForm(f.id, { action: "approve" }); reload(); })}>Approve form</button>}
        <label className="small row" style={{ gap: 4 }}><input type="checkbox" style={{ width: "auto" }} checked={key} onChange={(e) => setKey(e.target.checked)} /> with answer key</label>
        {(["docx", "pdf", "qti"] as const).map((fmt) => (
          <button key={fmt} disabled={busy || f.status !== "approved"} title={f.status !== "approved" ? "Approve the form first" : ""}
            onClick={() => run(() => api.postDownload(`/api/forms/${f.id}/export`, { format: fmt, include_answer_key: key }, `form.${fmt === "qti" ? "zip" : fmt}`))}>
            Export {fmt === "qti" ? "QTI (Blackboard)" : fmt.toUpperCase()}
          </button>
        ))}
        {f.status !== "approved" && <button className="danger" disabled={busy} onClick={() => confirm("Delete this draft form?") && run(async () => { await api.deleteForm(f.id); reload(); })}>Delete</button>}
      </div>
    </div>
  );
}
