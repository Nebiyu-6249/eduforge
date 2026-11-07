import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import ItemView from "../components/ItemView";
import JsonEditor from "../components/JsonEditor";
import { fmtDate } from "../components/util";
import type { DraftContext, DraftItem, DraftType, ItemStatus, VersionDetail } from "../types";

const STATUS_LABEL: Record<ItemStatus, string> = {
  suggested: "Suggested",
  under_review: "Under review",
  approved: "Approved",
  rejected: "Rejected",
  needs_review: "Needs review (CLO changed)",
};
const STATUS_CLASS: Record<ItemStatus, string> = {
  suggested: "extracted",
  under_review: "in_review",
  approved: "locked",
  rejected: "superseded",
  needs_review: "warning",
};

function errText(e: unknown) {
  if (e instanceof ApiError) return e.items?.length ? `${e.message} ${e.items.map((i) => i.message ?? `${i.loc}: ${i.msg}`).join("; ")}` : e.message;
  return String(e);
}

function summary(it: DraftItem): string {
  const b = it.body;
  return String(b.stem ?? b.question ?? b.statement ?? b.title ?? "").slice(0, 140);
}

function checkState(it: DraftItem): "ok" | "to_check" | "blocked" {
  if (it.scores.some((s) => s.hard && s.outcome === "fail")) return "blocked";
  if (it.scores.some((s) => s.outcome === "fail" || s.outcome === "warn")) return "to_check";
  return "ok";
}

function checkBadge(it: DraftItem) {
  const fail = it.scores.filter((s) => s.outcome === "fail");
  const warn = it.scores.filter((s) => s.outcome === "warn");
  if (fail.some((s) => s.hard)) return <span className="pill error">blocked</span>;
  if (fail.length || warn.length) return <span className="pill warning">{fail.length + warn.length} to check</span>;
  return <span className="pill locked">checks ok</span>;
}

// --------------------------------------------------------------------------
function RequestForm({ cv, ctx, types, onDone }: { cv: number; ctx: DraftContext; types: DraftType[]; onDone: (items: DraftItem[]) => void }) {
  const [type, setType] = useState("mcq");
  const [clos, setClos] = useState<number[]>([]);
  const [weeks, setWeeks] = useState<number[]>([]);
  const [count, setCount] = useState(3);
  const [difficulty, setDifficulty] = useState("medium");
  const [bloom, setBloom] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const isQuestion = types.find((t) => t.type === type)?.question;
  const chosenSkills = ctx.clos.filter((c) => clos.includes(c.number) && c.skills);

  const toggle = (arr: number[], n: number) => (arr.includes(n) ? arr.filter((x) => x !== n) : [...arr, n].sort((a, b) => a - b));

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const job = await api.generate(cv, { item_type: type, clo_numbers: clos, weeks, count, difficulty, bloom_level: bloom || null, notes: notes || null });
      const done = await waitJob(job.id, (j) => setStage(j.message ?? ""));
      onDone(await Promise.all((done.result!.item_ids as number[]).map((id) => api.item(id))));
      setNotes("");
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  return (
    <div className="card stack">
      <h2>Request drafts</h2>
      <div className="req-grid">
        <div>
          <label className="lbl" htmlFor="rq-type">Item type</label>
          <select id="rq-type" value={type} onChange={(e) => setType(e.target.value)}>
            {types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className="lbl" htmlFor="rq-count">How many</label>
          <input id="rq-count" type="number" min={1} max={10} value={count} onChange={(e) => setCount(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
        </div>
        <div>
          <label className="lbl" htmlFor="rq-diff">Difficulty</label>
          <select id="rq-diff" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
            <option>easy</option><option>medium</option><option>hard</option>
          </select>
        </div>
        <div>
          <label className="lbl" htmlFor="rq-bloom">Bloom level</label>
          <select id="rq-bloom" value={bloom} onChange={(e) => setBloom(e.target.value)}>
            <option value="">From the CLO</option>
            {ctx.bloom_levels.map((b) => <option key={b}>{b}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="lbl">Target CLO(s) — none selected means all</label>
        <div className="clo-picks">
          {ctx.clos.map((c) => (
            <label key={c.number} className={`clo-pick ${clos.includes(c.number) ? "on" : ""}`} title={c.text}>
              <input type="checkbox" checked={clos.includes(c.number)} onChange={() => setClos(toggle(clos, c.number))} />
              <span><strong>CLO {c.number}</strong> {c.text}</span>
              <span className="small muted">{c.bloom_level ?? ""}{c.skills ? " · skills" : ""}</span>
            </label>
          ))}
        </div>
        {isQuestion && chosenSkills.length > 0 && chosenSkills.length === clos.length && (
          <div className="small" style={{ color: "var(--warning)", marginTop: 4 }}>
            Skills outcomes are better evidenced by a rubric, case study or activity than by questions.
          </div>
        )}
      </div>
      <div>
        <label className="lbl">Week(s) — optional</label>
        <div className="week-picks">
          {ctx.weeks.map((w) => (
            <button key={w.week_no} type="button" title={w.topics.join("; ")} className={weeks.includes(w.week_no) ? "on" : ""}
              onClick={() => setWeeks(toggle(weeks, w.week_no))}>
              {w.week_no}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="lbl" htmlFor="rq-notes">Notes for the model — optional</label>
        <textarea id="rq-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. use UAE-based examples; avoid calculators" rows={2} />
      </div>
      {err && <div className="error-box">{err}</div>}
      <div className="row">
        <button className="primary" onClick={submit} disabled={busy}>{busy ? stage || "Queued…" : "Generate drafts"}</button>
        <span className="small muted">Drafts are grounded in your <Link to={`/v/${cv}/materials`}>course materials</Link> when they match; otherwise they are marked ungrounded.</span>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
function Detail({ item, onChange }: { item: DraftItem; onChange: (it: DraftItem, extra?: DraftItem[]) => void }) {
  const [showKey, setShowKey] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{ tags: any; body: any; answer_key: any; feedback: any }>({ tags: {}, body: {}, answer_key: null, feedback: null });
  const [mode, setMode] = useState<null | "reject" | "regenerate" | "approve">(null);
  const [solv, setSolv] = useState<{ verdict: string; detail: string } | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setEditing(false);
    setMode(null);
    setErr(null);
  }, [item.id]);

  const startEdit = () => {
    setDraft({
      tags: { clo_numbers: item.clo_numbers, week_no: item.week_no, bloom_level: item.bloom_level, difficulty: item.difficulty },
      body: structuredClone(item.body),
      answer_key: item.answer_key ? structuredClone(item.answer_key) : null,
      feedback: item.feedback ? structuredClone(item.feedback) : null,
    });
    setEditing(true);
    setErr(null);
  };

  async function run(fn: () => Promise<void>) {
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

  const save = () =>
    run(async () => {
      const it = await api.editItem(item.id, { ...draft, answer_key: draft.answer_key ?? undefined, feedback: draft.feedback ?? undefined, notes: note || undefined });
      setEditing(false);
      setNote("");
      onChange(it);
    });

  const act = (action: "approve" | "reject" | "reopen" | "regenerate") =>
    run(async () => {
      const r = await api.itemAction(item.id, action, note || undefined);
      let replacements = r.replacements;
      if (r.job) {
        const done = await waitJob(r.job.id);
        replacements = await Promise.all((done.result!.item_ids as number[]).map((id) => api.item(id)));
      }
      setMode(null);
      setNote("");
      onChange(r.job ? await api.item(item.id) : r.item, replacements);
    });

  const reviewable = item.status === "suggested" || item.status === "under_review" || item.status === "needs_review";

  return (
    <div className="card stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="row wrap">
            <span className={`pill ${STATUS_CLASS[item.status]}`}>{STATUS_LABEL[item.status]}</span>
            <strong>#{item.id} · {item.type_label}</strong>
            {item.grounded ? <span className="pill locked" title="Built from your course materials">grounded</span> : <span className="pill warning" title="No course material matched this request">ungrounded</span>}
          </div>
          <div className="small muted" style={{ marginTop: 4 }}>
            CLO {item.clo_numbers.join(", ")}{item.week_no ? ` · Week ${item.week_no}` : ""} · {item.bloom_level} · {item.difficulty}
            {" · "}{item.model} · {item.prompt_version}
            {item.parent_item_id && ` · replaces #${item.parent_item_id}`}
          </div>
          {item.approved_by && <div className="small" style={{ color: "var(--ok)" }}>Approved by {item.approved_by}, {fmtDate(item.approved_at)}</div>}
        </div>
        <label className="small row" style={{ gap: 4 }}>
          <input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} style={{ width: "auto" }} /> Show answer key
        </label>
      </div>

      {editing ? (
        <div className="stack">
          <div className="req-grid">
            <div><label className="lbl">CLO numbers</label>
              <input value={draft.tags.clo_numbers.join(", ")} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, clo_numbers: (e.target.value.match(/\d+/g) ?? []).map(Number) } })} /></div>
            <div><label className="lbl">Week</label>
              <input type="number" value={draft.tags.week_no ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, week_no: e.target.value ? Number(e.target.value) : null } })} /></div>
            <div><label className="lbl">Bloom</label>
              <select value={draft.tags.bloom_level ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, bloom_level: e.target.value } })}>
                {["remember", "understand", "apply", "analyze", "evaluate", "create"].map((b) => <option key={b}>{b}</option>)}
              </select></div>
            <div><label className="lbl">Difficulty</label>
              <select value={draft.tags.difficulty ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, difficulty: e.target.value } })}>
                <option>easy</option><option>medium</option><option>hard</option>
              </select></div>
          </div>
          <h3>Item</h3>
          <JsonEditor value={draft.body} onChange={(v) => setDraft({ ...draft, body: v })} />
          {draft.answer_key && (<><h3>Answer key</h3><JsonEditor value={draft.answer_key} onChange={(v) => setDraft({ ...draft, answer_key: v })} /></>)}
          {draft.feedback && (<><h3>Feedback prompts</h3><JsonEditor value={draft.feedback} onChange={(v) => setDraft({ ...draft, feedback: v })} /></>)}
          <input placeholder="What did you change? (optional, kept in the history)" value={note} onChange={(e) => setNote(e.target.value)} />
          {err && <div className="error-box">{err}</div>}
          <div className="row">
            <button className="primary" onClick={save} disabled={busy}>{busy ? "Saving and re-checking…" : "Save edit"}</button>
            <button onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
            <span className="small muted">Saving returns the item to review and re-runs the checks.</span>
          </div>
        </div>
      ) : (
        <ItemView item={item} showKey={showKey} />
      )}

      {!editing && (
        <>
          <div>
            <h3 style={{ marginBottom: 6 }}>Quality checks</h3>
            <table className="grid checks">
              <tbody>
                {item.scores.map((s) => (
                  <tr key={s.check} className={`chk ${s.outcome}`}>
                    <td style={{ width: 210 }}>{s.label}{s.hard && <span className="small muted"> · required</span>}</td>
                    <td style={{ width: 80 }}><span className={`pill ${s.outcome === "pass" ? "locked" : s.outcome === "fail" ? "error" : s.outcome === "warn" ? "warning" : ""}`}>{s.outcome}</span></td>
                    <td className="small">{s.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {mode ? (
            <div className="stack">
              <textarea autoFocus value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder={mode === "reject" ? "Why reject? (helps judge item types later)" : mode === "regenerate" ? "What should the replacement do differently? (required)" : "Approval note (optional)"} />
              {err && <div className="error-box">{err}</div>}
              <div className="row">
                <button className="primary" disabled={busy || (mode === "regenerate" && !note.trim())} onClick={() => act(mode)}>
                  {busy ? "Working…" : mode === "approve" ? "Approve" : mode === "reject" ? "Reject" : "Reject and regenerate"}
                </button>
                <button onClick={() => setMode(null)} disabled={busy}>Cancel</button>
              </div>
            </div>
          ) : (
            <div className="row wrap">
              {reviewable && (
                <button className="primary" disabled={!item.can_approve} title={item.can_approve ? "" : "Fix the failed required checks first"} onClick={() => { setMode("approve"); setNote(""); }}>
                  Approve
                </button>
              )}
              {item.status !== "rejected" && <button onClick={startEdit}>Edit</button>}
              {item.status !== "rejected" && <button onClick={() => { setMode("reject"); setNote(""); }}>Reject</button>}
              <button onClick={() => { setMode("regenerate"); setNote(""); }}>Regenerate with notes</button>
              {item.status === "approved" && (
                <label className="small row" style={{ gap: 4 }} title="Colleagues teaching this course can use it in their forms">
                  <input type="checkbox" style={{ width: "auto" }} checked={item.shared}
                    onChange={(e) => run(async () => { await api.share(item.id, e.target.checked); onChange({ ...item, shared: e.target.checked }); })} />
                  Share with colleagues
                </label>
              )}
              <button title="Can a strong model solve this unaided? A report only; never blocks approval."
                onClick={() => run(async () => {
                  const job = await api.solvability(item.id);
                  const done = await waitJob(job.id);
                  setSolv(done.result as any);
                })}>AI-solvability check</button>
              {(item.status === "approved" || item.status === "rejected") && <button onClick={() => act("reopen")}>Reopen</button>}
              {err && <div className="error-box">{err}</div>}
            </div>
          )}

          {solv && (
            <div className={`gate ${solv.verdict === "not" ? "ready" : ""}`}>
              <div className="grow small">
                <strong>AI-solvability: {solv.verdict === "trivial" ? "solved trivially" : solv.verdict === "partly" ? "partly solved" : solv.verdict === "not" ? "not solved" : "unknown"}</strong> — {solv.detail}
                {(solv.verdict === "trivial" || solv.verdict === "partly") && <div className="muted">Consider personalised data, an oral follow-up, or asking for process evidence.</div>}
              </div>
            </div>
          )}
          {item.events.length > 0 && (
            <div className="small muted">
              <strong>History:</strong>{" "}
              {item.events.map((e, i) => (
                <span key={i}>{i > 0 && " · "}{e.action} by {e.by} {fmtDate(e.at)}{e.notes ? ` (“${e.notes}”)` : ""}</span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
export default function Drafts() {
  const cv = Number(useParams().id);
  const [v, setV] = useState<VersionDetail | null>(null);
  const [ctx, setCtx] = useState<DraftContext | null>(null);
  const [types, setTypes] = useState<DraftType[]>([]);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [filter, setFilter] = useState<ItemStatus | "all">("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [cloFilter, setCloFilter] = useState("all");
  const [weekFilter, setWeekFilter] = useState("all");
  const [checkFilter, setCheckFilter] = useState("all");
  const [err, setErr] = useState<string | null>(null);
  const [includeKey, setIncludeKey] = useState(true);

  useEffect(() => {
    Promise.all([api.get(cv), api.draftContext(cv), api.draftTypes(), api.drafts(cv)])
      .then(([vv, c, t, it]) => {
        setV(vv); setCtx(c); setTypes(t); setItems(it);
        setSel(it[0]?.id ?? null);
      })
      .catch((e) => setErr(errText(e)));
  }, [cv]);

  const shown = useMemo(
    () => items.filter((i) =>
      (filter === "all" || i.status === filter) &&
      (typeFilter === "all" || i.type === typeFilter) &&
      (cloFilter === "all" || i.clo_numbers.includes(Number(cloFilter))) &&
      (weekFilter === "all" || String(i.week_no ?? "") === weekFilter) &&
      (checkFilter === "all" || checkState(i) === checkFilter)),
    [items, filter, typeFilter, cloFilter, weekFilter, checkFilter],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const i of items) c[i.status] = (c[i.status] ?? 0) + 1;
    return c;
  }, [items]);
  const current = items.find((i) => i.id === sel) ?? null;

  const upsert = (it: DraftItem, extra: DraftItem[] = []) => {
    setItems((prev) => {
      const rest = prev.filter((p) => p.id !== it.id && !extra.some((x) => x.id === p.id));
      return [...extra, it, ...rest].sort((a, b) => b.id - a.id);
    });
    if (extra.length) setSel(extra[0].id);
  };

  if (err && !v) return <div className="error-box">{err}</div>;
  if (!v || !ctx) return <p className="muted">Loading…</p>;
  const rec = v.record;

  return (
    <div className="stack">
      <div className="small"><Link to={`/v/${cv}`}>← {rec.course.code} {rec.offering.term} working version</Link> · <Link to={`/v/${cv}/materials`}>Course materials</Link></div>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <h1>Draft Studio · <span className="code" style={{ fontSize: 22 }}>{rec.course.code}</span> {rec.course.title}</h1>
          <div className="muted">Every draft stays a draft until you approve it. Only approved items export.</div>
        </div>
        <div className="card row" style={{ padding: "10px 14px" }}>
          <span className="small"><strong>{counts.approved ?? 0}</strong> approved</span>
          <label className="small row" style={{ gap: 4 }}>
            <input type="checkbox" checked={includeKey} onChange={(e) => setIncludeKey(e.target.checked)} style={{ width: "auto" }} /> with answer key
          </label>
          <button disabled={!counts.approved} onClick={() => api.exportItems(cv, "docx", includeKey).catch((e) => setErr(errText(e)))}>Export DOCX</button>
          <button disabled={!counts.approved} onClick={() => api.exportItems(cv, "pdf", includeKey).catch((e) => setErr(errText(e)))}>Export PDF</button>
          <button disabled={!counts.approved} onClick={() => api.postDownload(`/api/course-versions/${cv}/qti`, {}, "bank_qti.zip").catch((e) => setErr(errText(e)))}>Export QTI</button>
          <label className="row small" style={{ gap: 4, cursor: "pointer" }}>
            <input type="file" accept=".docx,.pdf,.txt,.zip" style={{ display: "none" }}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setErr(null);
                try {
                  const job = await api.bankImport(cv, f);
                  const done = await waitJob(job.id);
                  const news = await Promise.all((done.result!.item_ids as number[]).map((id) => api.item(id)));
                  setItems((p) => [...news.reverse(), ...p]);
                } catch (ex) {
                  setErr(errText(ex));
                }
                e.target.value = "";
              }} />
            <span className="button-like">Import question bank…</span>
          </label>
        </div>
      </div>
      {err && <div className="error-box">{err}</div>}

      {ctx.can_generate ? (
        <RequestForm cv={cv} ctx={ctx} types={types} onDone={(news) => { setItems((p) => [...news.slice().reverse(), ...p]); setSel(news[0]?.id ?? sel); setFilter("all"); }} />
      ) : (
        <div className="gate"><div className="grow small">This version is {v.status}. Drafts are generated only from the locked working version; you can still review existing drafts here.</div></div>
      )}

      <div className="drafts-layout">
        <div className="card" style={{ padding: 12 }}>
          <div className="filter" style={{ flexWrap: "wrap" }}>
            {(["all", "suggested", "under_review", "needs_review", "approved", "rejected"] as const).map((k) => (
              <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
                {k === "all" ? `All (${items.length})` : `${STATUS_LABEL[k]} (${counts[k] ?? 0})`}
              </button>
            ))}
          </div>
          <div className="filter-grid">
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter by type">
              <option value="all">All types</option>
              {types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
            </select>
            <select value={cloFilter} onChange={(e) => setCloFilter(e.target.value)} aria-label="Filter by CLO">
              <option value="all">All CLOs</option>
              {ctx.clos.map((c) => <option key={c.number} value={c.number}>CLO {c.number}</option>)}
            </select>
            <select value={weekFilter} onChange={(e) => setWeekFilter(e.target.value)} aria-label="Filter by week">
              <option value="all">All weeks</option>
              {ctx.weeks.map((w) => <option key={w.week_no} value={w.week_no}>Week {w.week_no}</option>)}
            </select>
            <select value={checkFilter} onChange={(e) => setCheckFilter(e.target.value)} aria-label="Filter by quality checks">
              <option value="all">Any checks</option>
              <option value="ok">Checks ok</option>
              <option value="to_check">Something to check</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
          {shown.length === 0 && <p className="muted small">No drafts here yet.</p>}
          {shown.map((it) => (
            <button key={it.id} className={`draft-row ${sel === it.id ? "sel" : ""}`} onClick={() => setSel(it.id)}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="small"><strong>#{it.id}</strong> {it.type_label} · CLO {it.clo_numbers.join(",")}</span>
                <span className={`pill ${STATUS_CLASS[it.status]}`}>{STATUS_LABEL[it.status]}</span>
              </div>
              <div className="small" style={{ margin: "4px 0", textAlign: "left" }}>{summary(it)}</div>
              {checkBadge(it)}
            </button>
          ))}
        </div>
        <div>{current ? <Detail item={current} onChange={upsert} /> : <div className="card muted">Select a draft.</div>}</div>
      </div>
    </div>
  );
}
