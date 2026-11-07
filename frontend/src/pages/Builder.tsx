import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import { fmtDate, fmtPct } from "../components/util";
import type { VersionDetail } from "../types";

const TYPES = ["mcq", "short_answer", "problem", "code_exercise", "practice_set", "case_study"];
const TYPE_LABEL: Record<string, string> = {
  mcq: "Multiple choice", short_answer: "Short answer", problem: "Problem", code_exercise: "Code",
  practice_set: "Practice set", case_study: "Case study",
};

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/**
 * Assessment Builder (plan 3.1–3.6). The page follows the order the work
 * happens in: pick an assessment from the locked syllabus, read its blueprint,
 * build the forms, review and approve them, then export the paper and the key.
 */
export default function Builder() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [picked, setPicked] = useState<any | null>(null);
  const [bp, setBp] = useState<any | null>(null);
  const [editingBp, setEditingBp] = useState(false);
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

  const formsByAssessment = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const f of forms) (m[f.assessment_name] ??= []).push(f);
    return m;
  }, [forms]);

  if (!v) return err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>;
  const rec = v.record;
  const weeks = rec.weekly.map((w) => w.week_no);
  const approvedInPool = pool.length;

  const pick = (r: any) =>
    run(async () => {
      setPicked(r);
      setBp(await api.blueprint(cv, r.name, r.week));
    });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1 className="page-title"><Icon name="builder" size={26} /> Assessment Builder</h1>
          <p className="lede">
            Build a quiz or exam from your approved items to match one row of the locked syllabus.
          </p>
          <p className="muted small" style={{ maxWidth: "70ch", marginTop: 0 }}>
            {rec.course.code} {rec.course.title} · {approvedInPool} approved item{approvedInPool === 1 ? "" : "s"} available.
            A form stays a draft until you approve it, and only approved forms export.
          </p>
        </div>
        <Link className="btn" to={`/v/${cv}/drafts`}>Open Draft Studio</Link>
      </div>

      {err && <div className="error-box">{err}</div>}

      <section className="card">
        <h2>1. Pick the assessment</h2>
        {rows.length === 0 ? (
          <div className="empty">
            <p>The locked syllabus lists no assessments to build from.</p>
            <Link className="btn" to={`/v/${cv}`}>Open the syllabus</Link>
          </div>
        ) : (
          <div className="scroll-x">
            <table className="grid">
              <thead>
                <tr>
                  <th>Assessment</th>
                  <th style={{ width: 80 }}>Week</th>
                  <th style={{ width: 90 }}>Weight</th>
                  <th style={{ width: 130 }}>CLOs</th>
                  <th style={{ width: 150 }}>Forms built</th>
                  <th style={{ width: 110 }} />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const built = formsByAssessment[r.name] ?? [];
                  const on = picked?.name === r.name && picked?.week === r.week;
                  return (
                    <tr key={i} className={on ? "sel" : undefined}>
                      <th scope="row">{r.name}</th>
                      <td className="num">{r.week ?? "—"}</td>
                      <td className="num">{fmtPct(r.weight_pct)}</td>
                      <td>{r.clos.length ? `CLO ${r.clos.join(", ")}` : <span className="muted">none</span>}</td>
                      <td>
                        {built.length === 0 ? <span className="muted">none</span> : (
                          <>
                            {built.length} ({built.filter((f: any) => f.status === "approved").length} approved)
                          </>
                        )}
                      </td>
                      <td className="c">
                        <button className={on ? "" : "primary"} disabled={busy} onClick={() => pick(r)}>
                          {built.length ? "Build another" : "Build"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {bp && (
        <section className="card stack">
          <div className="row between wrap">
            <h2>2. Blueprint for {bp.assessment}</h2>
            <button onClick={() => setEditingBp(true)}>Change the blueprint</button>
          </div>
          <BlueprintSummary bp={bp} rec={rec} />
          <div className="dlg-grid">
            <div>
              <label className="lbl" htmlFor="bp-ver">Parallel versions</label>
              <input id="bp-ver" type="number" min={1} max={8} value={versions}
                onChange={(e) => setVersions(Math.max(1, Math.min(8, Number(e.target.value) || 1)))} />
              <p className="small muted">Several forms of the same blueprint with as little overlap as possible.</p>
            </div>
            <div>
              <label className="lbl" htmlFor="bp-sec">Section labels (optional)</label>
              <input id="bp-sec" value={sections} placeholder="e.g. 3:00, 4:30" onChange={(e) => setSections(e.target.value)} />
              <p className="small muted">One label per version, comma separated.</p>
            </div>
          </div>
          <div className="row wrap">
            <button className="primary" disabled={busy}
              onClick={() => run(async () => {
                await api.buildForms(cv, {
                  blueprint: bp, versions,
                  sections: sections ? sections.split(",").map((s) => s.trim()) : undefined,
                });
                reload();
              })}>
              {busy ? "Building…" : `Build ${versions} form${versions > 1 ? "s" : ""}`}
            </button>
            <span className="small muted">
              Items used in the last {bp.avoid_used_in_last_terms} term(s) and near-duplicates are skipped.
            </span>
          </div>
        </section>
      )}

      {editingBp && bp && (
        <BlueprintDialog bp={bp} rec={rec} weeks={weeks} onClose={() => setEditingBp(false)}
          onSave={(next) => { setBp(next); setEditingBp(false); }} />
      )}

      {forms.length > 0 && (
        <section className="stack">
          <h2>3. Review, approve and export</h2>
          {Object.entries(formsByAssessment).map(([name, group]) => (
            <FormGroup key={name} name={name} forms={group} pool={pool} busy={busy} run={run} reload={reload} cv={cv} />
          ))}
        </section>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
function BlueprintSummary({ bp, rec }: { bp: any; rec: VersionDetail["record"] }) {
  const texts = Object.fromEntries(rec.clos.map((c) => [String(c.number), c.text]));
  const items = Object.values(bp.types as Record<string, number>).reduce((a, b) => a + b, 0);
  const weeks = bp.weeks as number[];
  const span = weeks.length ? (weeks.length === 1 ? `week ${weeks[0]}` : `weeks ${weeks[0]}–${weeks[weeks.length - 1]}`) : "any week";
  return (
    <div className="bp-summary">
      <dl>
        <div><dt>Covers</dt><dd>{span}</dd></div>
        <div><dt>Items</dt><dd>{items} in total</dd></div>
        <div><dt>Points</dt><dd>{bp.total_points}</dd></div>
        <div><dt>Time</dt><dd>{bp.minutes ? `${bp.minutes} minutes` : "take-home"}</dd></div>
        <div><dt>Share of the grade</dt><dd>{fmtPct(bp.weight_pct)}</dd></div>
      </dl>
      <div className="bp-split">
        <div>
          <h3>Item mix</h3>
          <ul className="tight">
            {Object.entries(bp.types as Record<string, number>).filter(([, n]) => n > 0).map(([t, n]) => (
              <li key={t}>{n} × {TYPE_LABEL[t] ?? t}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Outcomes covered</h3>
          <ul className="tight">
            {Object.entries(bp.clo_shares as Record<string, number>).map(([c, share]) => (
              <li key={c}><strong>CLO {c}</strong> {pct(share)} of the marks — <span className="muted">{texts[c]}</span></li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
function BlueprintDialog({ bp, rec, weeks, onClose, onSave }: {
  bp: any; rec: VersionDetail["record"]; weeks: number[]; onClose: () => void; onSave: (bp: any) => void;
}) {
  const [draft, setDraft] = useState<any>(() => structuredClone(bp));
  return (
    <Modal
      title={`Blueprint for ${bp.assessment}`}
      description="What the built form has to match: length, points, item mix, weeks and the share of the marks per outcome."
      onClose={onClose}
      footer={
        <>
          <span className="grow" />
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" onClick={() => onSave(draft)}>Use this blueprint</button>
        </>
      }
    >
      <div className="dlg-grid">
        <div>
          <label className="lbl" htmlFor="bd-min">Minutes (0 for take-home)</label>
          <input id="bd-min" type="number" min={0} value={draft.minutes}
            onChange={(e) => setDraft({ ...draft, minutes: Number(e.target.value) })} />
        </div>
        <div>
          <label className="lbl" htmlFor="bd-pts">Total points</label>
          <input id="bd-pts" type="number" min={1} value={draft.total_points}
            onChange={(e) => setDraft({ ...draft, total_points: Number(e.target.value) })} />
        </div>
      </div>

      <section className="dlg-sect">
        <h3>How many of each item type</h3>
        <div className="row wrap">
          {TYPES.map((t) => (
            <label key={t} className="small count-field">
              <span>{TYPE_LABEL[t]}</span>
              <input type="number" min={0} aria-label={`${TYPE_LABEL[t]} count`} value={draft.types[t] ?? 0}
                onChange={(e) => setDraft({ ...draft, types: { ...draft.types, [t]: Number(e.target.value) } })} />
            </label>
          ))}
        </div>
      </section>

      <section className="dlg-sect">
        <h3>Weeks the assessment covers</h3>
        <div className="week-picks">
          {weeks.map((w) => (
            <button key={w} type="button" aria-pressed={draft.weeks.includes(w)}
              className={draft.weeks.includes(w) ? "on" : ""}
              onClick={() => setDraft({
                ...draft,
                weeks: draft.weeks.includes(w)
                  ? draft.weeks.filter((x: number) => x !== w)
                  : [...draft.weeks, w].sort((a: number, b: number) => a - b),
              })}>
              {w}
            </button>
          ))}
        </div>
      </section>

      <section className="dlg-sect">
        <h3>Share of the marks per outcome</h3>
        <div className="stack">
          {rec.clos.map((c) => {
            const key = String(c.number);
            const value = draft.clo_shares[key] ?? 0;
            return (
              <label key={c.number} className="share-row">
                <span className="share-label"><strong>CLO {c.number}</strong> <span className="muted small">{c.text}</span></span>
                <input type="number" step={5} min={0} max={100} aria-label={`CLO ${c.number} share, percent`}
                  value={Math.round(value * 100)}
                  onChange={(e) => {
                    const shares = { ...draft.clo_shares, [key]: Number(e.target.value) / 100 };
                    if (!Number(e.target.value)) delete shares[key];
                    setDraft({ ...draft, clo_shares: shares });
                  }} />
                <span className="small muted">%</span>
              </label>
            );
          })}
        </div>
      </section>
    </Modal>
  );
}

// --------------------------------------------------------------------------
function FormGroup({ name, forms, pool, busy, run, reload, cv }: {
  name: string; forms: any[]; pool: any[]; busy: boolean;
  run: (fn: () => Promise<unknown>) => Promise<void>; reload: () => void; cv: number;
}) {
  const [tab, setTab] = useState(forms[0]?.id);
  const current = forms.find((f) => f.id === tab) ?? forms[0];
  if (!current) return null;
  return (
    <div className="card stack">
      <div className="row between wrap">
        <h3>{name}</h3>
        <span className="small muted">{forms.length} parallel version{forms.length === 1 ? "" : "s"}</span>
      </div>
      {forms.length > 1 && (
        <nav className="tabs" aria-label={`Versions of ${name}`}>
          {forms.map((f) => (
            <button key={f.id} className={f.id === current.id ? "active" : ""} onClick={() => setTab(f.id)}>
              Version {f.version_label}
              {f.section ? ` · ${f.section}` : ""}
              <span className="count">{f.status}</span>
            </button>
          ))}
        </nav>
      )}
      <FormCard f={current} pool={pool} busy={busy} run={run} reload={reload} cv={cv} />
    </div>
  );
}

function FormCard({ f, pool, busy, run, reload, cv }: {
  f: any; pool: any[]; busy: boolean; run: (fn: () => Promise<unknown>) => Promise<void>;
  reload: () => void; cv: number;
}) {
  const cov = f.coverage;
  const onForm = new Set(f.items.map((i: any) => i.item_id));
  const move = (idx: number, d: number) => {
    const ids = f.items.map((i: any) => i.item_id);
    const j = idx + d;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    run(async () => { await api.editForm(f.id, { action: "reorder", item_ids: ids }); reload(); });
  };
  const gapText = (g: any) =>
    g.warning ??
    `${g.count} more ${g.type ? (TYPE_LABEL[g.type] ?? g.type).toLowerCase() : "item"}${g.count > 1 ? "s" : ""}` +
    ` for CLO ${g.clo_numbers.join(", ")}` +
    (g.weeks?.length ? `, weeks ${g.weeks[0]}–${g.weeks[g.weeks.length - 1]}` : "") +
    ` (${g.reason})`;

  return (
    <div className="stack">
      <div className="row wrap between">
        <div className="small muted">
          {cov.items} of {cov.target_items} items · {cov.points} points ·{" "}
          {cov.minutes} min{cov.minutes_cap ? ` of ${cov.minutes_cap}` : ""} ·{" "}
          {Object.entries(cov.clos).map(([c, x]: any) => `CLO ${c}: ${x.have}/${x.want}`).join(", ")}
          {f.approved_by && ` · approved by ${f.approved_by}, ${fmtDate(f.approved_at)}`}
        </div>
        <span className={`pill ${f.status === "approved" ? "locked" : "in_review"}`}>{f.status}</span>
      </div>

      {f.gaps.length > 0 && (
        <div className="note-box warn">
          <div className="grow">
            <strong>This form does not yet match the blueprint</strong>
            <ul className="tight small">
              {f.gaps.map((g: any, i: number) => <li key={i}>{gapText(g)}</li>)}
            </ul>
          </div>
          <Link className="btn" to={`/v/${cv}/drafts`}>Generate the missing items</Link>
        </div>
      )}

      <div className="scroll-x">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th>Item</th>
              <th style={{ width: 110 }}>Type</th>
              <th style={{ width: 70 }}>CLO</th>
              <th style={{ width: 50 }}>Week</th>
              <th style={{ width: 80 }}>Points</th>
              <th style={{ width: 96 }}>Order</th>
              <th style={{ width: 150 }}>Swap</th>
            </tr>
          </thead>
          <tbody>
            {f.items.map((it: any, idx: number) => (
              <tr key={it.item_id}>
                <td className="num">{it.position}</td>
                <td className="small">
                  {it.summary}
                  {it.status !== "approved" && <span className="pill error"> {it.status}</span>}
                </td>
                <td className="small">{TYPE_LABEL[it.type] ?? it.type}</td>
                <td className="num">{it.clo_numbers.join(", ")}</td>
                <td className="num">{it.week_no ?? "—"}</td>
                <td>
                  <input type="number" step="0.5" min={0} defaultValue={it.points}
                    aria-label={`Points for item ${it.position}`} style={{ width: 70 }}
                    onBlur={(e) => Number(e.target.value) !== it.points &&
                      run(async () => { await api.editForm(f.id, { action: "points", item_id: it.item_id, points: Number(e.target.value) }); reload(); })} />
                </td>
                <td className="row">
                  <button className="icon" aria-label={`Move item ${it.position} up`} disabled={busy || idx === 0}
                    onClick={() => move(idx, -1)}>Up</button>
                  <button className="icon" aria-label={`Move item ${it.position} down`}
                    disabled={busy || idx === f.items.length - 1} onClick={() => move(idx, 1)}>Down</button>
                </td>
                <td>
                  <select aria-label={`Swap item ${it.position}`} value="" disabled={busy}
                    onChange={(e) => e.target.value && run(async () => {
                      await api.editForm(f.id, { action: "swap", item_id: it.item_id, replace_with: Number(e.target.value) });
                      reload();
                    })}>
                    <option value="">Swap for…</option>
                    {pool.filter((p) => p.type === it.type && !onForm.has(p.item_id)).map((p) => (
                      <option key={p.item_id} value={p.item_id}>
                        CLO {p.clo_numbers.join(",")} · {p.summary.slice(0, 50)}{p.mine ? "" : " (shared)"}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="row wrap between">
        <div className="row wrap">
          {f.status !== "approved" && (
            <button className="primary" disabled={busy || !f.items.length}
              onClick={() => run(async () => { await api.editForm(f.id, { action: "approve" }); reload(); })}>
              Approve this form
            </button>
          )}
          {f.status !== "approved" && (
            <button className="danger" disabled={busy}
              onClick={() => confirm("Delete this draft form?") && run(async () => { await api.deleteForm(f.id); reload(); })}>
              Delete
            </button>
          )}
        </div>
        <div className="row wrap">
          <div className="export-group">
            <span className="small">Question paper</span>
            {(["docx", "pdf"] as const).map((fmt) => (
              <button key={fmt} disabled={busy || f.status !== "approved"}
                title={f.status !== "approved" ? "Approve the form first" : ""}
                onClick={() => run(() => api.postDownload(`/api/forms/${f.id}/export`, { format: fmt, part: "paper" }, `question_paper.${fmt}`))}>
                {fmt.toUpperCase()}
              </button>
            ))}
          </div>
          <div className="export-group">
            <span className="small">Answer key</span>
            {(["docx", "pdf"] as const).map((fmt) => (
              <button key={fmt} disabled={busy || f.status !== "approved"}
                title={f.status !== "approved" ? "Approve the form first" : ""}
                onClick={() => run(() => api.postDownload(`/api/forms/${f.id}/export`, { format: fmt, part: "key" }, `answer_key.${fmt}`))}>
                {fmt.toUpperCase()}
              </button>
            ))}
          </div>
          <button disabled={busy || f.status !== "approved"} title={f.status !== "approved" ? "Approve the form first" : ""}
            onClick={() => run(() => api.postDownload(`/api/forms/${f.id}/export`, { format: "qti" }, "form_qti.zip"))}>
            QTI for Blackboard
          </button>
        </div>
      </div>
    </div>
  );
}
