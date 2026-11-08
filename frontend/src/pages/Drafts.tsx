import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import Icon from "../components/Icon";
import ItemView from "../components/ItemView";
import JsonEditor from "../components/JsonEditor";
import { fmtDate } from "../components/util";
import type { DraftContext, DraftItem, DraftType, Grounding, ItemStatus, Material, VersionDetail } from "../types";

const STATUS_LABEL: Record<ItemStatus, string> = {
  suggested: "New",
  under_review: "Needs your review",
  approved: "Approved",
  rejected: "Not used",
  needs_review: "Needs another look",
};
const STATUS_CLASS: Record<ItemStatus, string> = {
  suggested: "info",
  under_review: "attention",
  approved: "ok",
  rejected: "neutral",
  needs_review: "attention",
};

function errText(e: unknown) {
  if (e instanceof ApiError) return e.items?.length ? `${e.message} ${e.items.map((i) => i.message ?? `${i.loc}: ${i.msg}`).join("; ")}` : e.message;
  return String(e);
}

/* The one-line preview in the list has no maths typesetting, so raw TeX
   ("$\text{mean}=75.0$") would be what a teacher skims. Strip the markers and
   leave the numbers and words. */
function plainMath(s: string): string {
  return s
    .replace(/\$\$?([^$]*)\$\$?/g, "$1")
    .replace(/\\(?:text|mathrm|mathbf|operatorname)\{([^}]*)\}/g, "$1")
    .replace(/\\[a-zA-Z]+/g, "")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function summary(it: DraftItem): string {
  const b = it.body;
  return plainMath(String(b.stem ?? b.question ?? b.statement ?? b.title ?? "")).slice(0, 140);
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

const DIFFICULTIES = ["easy", "medium", "hard"];
const capital = (s: string | null | undefined) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const usedLabel = (u: DraftItem["used_in"][number]) => `${u.assessment_name} · ${u.version_label}`;
const NOT_IN_QUIZ = "Not in a quiz yet";

// --------------------------------------------------------------------------
const KIND_WORD: Record<string, string> = {
  slides: "slides", notes: "notes", past_exam: "past exam", textbook: "textbook", other: "other",
};

/** What the next request will be grounded in, before it is made. */
function MaterialsBanner({ cv, materials }: { cv: number; materials: Material[] | null }) {
  if (materials === null) return null;
  const indexed = materials.filter((m) => m.status === "indexed");
  if (indexed.length === 0) {
    const pending = materials.filter((m) => m.status === "pending").length;
    return (
      <div className="note-box">
        <Icon name="materials" size={18} />
        <div className="grow">
          <strong>No slides added yet</strong>
          <div className="small">
            {pending > 0
              ? `${pending} file(s) are still being read. Wait a moment, or write questions now from the syllabus alone.`
              : "Questions will be written from the syllabus only. Add your slides and they will follow your own wording instead."}
          </div>
        </div>
        <Link className="btn" to={`/v/${cv}/materials`}>Add materials</Link>
      </div>
    );
  }
  return (
    <div className="note-box">
      <Icon name="materials" size={18} />
      <div className="grow">
        <strong>Based on your slides ({indexed.length})</strong>
        <ul className="tight small">
          {indexed.slice(0, 4).map((m) => (
            <li key={m.id}>
              {m.title} ({KIND_WORD[m.kind] ?? m.kind}, {m.week_no ? `week ${m.week_no}` : "whole course"})
            </li>
          ))}
          {indexed.length > 4 && <li className="muted">and {indexed.length - 4} more</li>}
        </ul>
      </div>
      <Link className="btn" to={`/v/${cv}/materials`}>Course Materials</Link>
    </div>
  );
}

/** Where a draft came from: the material and passage, or why there was none. */
function GroundingPanel({ item }: { item: DraftItem }) {
  const [g, setG] = useState<Grounding | null>(null);
  const [open, setOpen] = useState<number[]>([]);
  useEffect(() => {
    setG(null);
    setOpen([]);
    api.grounding(item.id).then(setG).catch(() => setG(null));
  }, [item.id]);
  if (!g) return null;
  if (!g.grounded)
    return (
      <div className="grounding ungrounded">
        <strong>Written from the syllabus only (no slides added).</strong>{" "}
        <span className="small">{g.note}</span>
      </div>
    );
  return (
    <div className="grounding">
      <strong>Based on your slides:</strong>{" "}
      {g.sources.map((s, i) => (
        <span key={s.chunk_id}>
          {i > 0 && "; "}
          {s.material_title}
          {s.week_no ? `, week ${s.week_no}` : ""} ({s.location})
        </span>
      ))}
      <div className="small muted">{g.note}</div>
      {g.sources.map((s) => (
        <details key={s.chunk_id} open={open.includes(s.chunk_id)}
          onToggle={(e) => setOpen((p) => (e.currentTarget.open ? [...p, s.chunk_id] : p.filter((x) => x !== s.chunk_id)))}>
          <summary>{s.material_title} — {s.location}</summary>
          <blockquote className="excerpt">{s.excerpt}</blockquote>
        </details>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
function RequestForm({ cv, ctx, types, materials, onDone }: {
  cv: number; ctx: DraftContext; types: DraftType[]; materials: Material[] | null;
  onDone: (items: DraftItem[]) => void;
}) {
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
  const chosenType = types.find((t) => t.type === type);
  const isQuestion = chosenType?.question;
  const chosenSkills = ctx.clos.filter((c) => clos.includes(c.number) && c.skills);
  const LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"];
  const cap = chosenType?.max_bloom ?? null;
  const tooHigh = cap
    ? ctx.clos.filter((c) => clos.includes(c.number) && c.bloom_level &&
        LEVELS.indexOf(c.bloom_level) > LEVELS.indexOf(cap))
    : [];

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
      <h2>Write some more questions or materials</h2>
      <MaterialsBanner cv={cv} materials={materials} />
      <div className="req-grid">
        <div>
          <label className="lbl" htmlFor="rq-type">What kind</label>
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
            {DIFFICULTIES.map((d) => <option key={d} value={d}>{capital(d)}</option>)}
          </select>
        </div>
      </div>
      <details>
        <summary className="small muted">More options</summary>
        <div style={{ marginTop: 12, maxWidth: 320 }}>
          <label className="lbl" htmlFor="rq-bloom">Type of thinking</label>
          <select id="rq-bloom" value={bloom} onChange={(e) => setBloom(e.target.value)}>
            <option value="">From the learning outcome</option>
            {ctx.bloom_levels
              .filter((b) => !cap || LEVELS.indexOf(b) <= LEVELS.indexOf(cap))
              .map((b) => <option key={b} value={b}>{capital(b)}</option>)}
          </select>
        </div>
      </details>
      {tooHigh.length > 0 && (
        <p className="small" style={{ color: "var(--warning)", margin: 0 }}>
          Outcome {tooHigh.map((c) => c.number).join(", ")} asks for more than a{" "}
          {chosenType?.label.toLowerCase()} can show, because choosing from a list only goes so far. These
          will aim one level lower. A case study, a worked problem or a marking rubric fits the rest.
        </p>
      )}
      <div>
        <label className="lbl">Which learning outcomes (none ticked means all of them)</label>
        <div className="clo-picks">
          {ctx.clos.map((c) => (
            <label key={c.number} className={`clo-pick ${clos.includes(c.number) ? "on" : ""}`} title={c.text}>
              <input type="checkbox" checked={clos.includes(c.number)} onChange={() => setClos(toggle(clos, c.number))} />
              <span><strong>Outcome {c.number}</strong> {c.text}</span>
              <span className="small muted">{c.skills ? "communication or teamwork" : ""}</span>
            </label>
          ))}
        </div>
        {isQuestion && chosenSkills.length > 0 && chosenSkills.length === clos.length && (
          <div className="small" style={{ color: "var(--warning)", marginTop: 4 }}>
            Outcomes about communication or teamwork are better shown by a case study, an activity or a marking rubric than by a question.
          </div>
        )}
      </div>
      <div>
        <label className="lbl">Which weeks (optional)</label>
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
        <label className="lbl" htmlFor="rq-notes">Anything they should do differently (optional)</label>
        <textarea id="rq-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. use UAE-based examples; avoid calculators" rows={2} />
      </div>
      {err && <div className="error-box">{err}</div>}
      <div className="row">
        <button className="primary" onClick={submit} disabled={busy}>{busy ? stage || "Starting…" : "Write them"}</button>
        <span className="small muted">Everything written here is a draft until you approve it.</span>
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
            {item.grounded
              ? <span className="pill ok">from your slides</span>
              : <span className="pill neutral">from the syllabus</span>}
          </div>
          <div className="small muted" style={{ marginTop: 4 }}>
            Outcome {item.clo_numbers.join(", ")}{item.week_no ? ` · week ${item.week_no}` : ""}
            {item.difficulty ? ` · ${capital(item.difficulty)}` : ""}
            {item.parent_item_id && " · replaces an earlier one"}
          </div>
          <div className="small" style={{ marginTop: 4 }}>
            {item.used_in.length === 0 ? <span className="muted">{NOT_IN_QUIZ}</span> : (
              <>In{" "}{item.used_in.map((u, i) => (
                <span key={u.form_id}>{i > 0 && ", "}<Link to={`/v/${item.course_version_id}/quiz/${u.form_id}`}>{usedLabel(u)}</Link></span>
              ))}</>
            )}
          </div>
          {item.approved_by && (
            <div className="small" style={{ color: "var(--ok)" }}>
              Approved by {item.approved_by}{item.approved_at ? `, ${fmtDate(item.approved_at)}` : ""}
            </div>
          )}
        </div>
        <label className="small row" style={{ gap: 4 }}>
          <input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} style={{ width: "auto" }} /> Show answer key
        </label>
      </div>

      {editing ? (
        <div className="stack">
          <div className="req-grid">
            <div><label className="lbl">Learning outcomes</label>
              <input value={draft.tags.clo_numbers.join(", ")} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, clo_numbers: (e.target.value.match(/\d+/g) ?? []).map(Number) } })} /></div>
            <div><label className="lbl">Week</label>
              <input type="number" value={draft.tags.week_no ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, week_no: e.target.value ? Number(e.target.value) : null } })} /></div>
            <div><label className="lbl" htmlFor="ed-bloom">Type of thinking</label>
              <select id="ed-bloom" value={draft.tags.bloom_level ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, bloom_level: e.target.value } })}>
                {["remember", "understand", "apply", "analyze", "evaluate", "create"].map((b) => <option key={b} value={b}>{capital(b)}</option>)}
              </select></div>
            <div><label className="lbl" htmlFor="ed-diff">Difficulty</label>
              <select id="ed-diff" value={draft.tags.difficulty ?? ""} onChange={(e) => setDraft({ ...draft, tags: { ...draft.tags, difficulty: e.target.value } })}>
                {DIFFICULTIES.map((d) => <option key={d} value={d}>{capital(d)}</option>)}
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
            <span className="small muted">Saving puts the question back on your review list and runs the checks again.</span>
          </div>
        </div>
      ) : (
        <>
          <GroundingPanel item={item} />
          <ItemView item={item} showKey={showKey} />
        </>
      )}

      {!editing && (
        <>
          {item.scores.length > 0 && <div>
            <h3 style={{ marginBottom: 6 }}>Checks EduForge ran</h3>
            <table className="grid checks">
              <tbody>
                {item.scores.map((s) => (
                  <tr key={s.check} className={`chk ${s.outcome}`}>
                    <td style={{ width: 210 }}>{s.label}{s.hard && <span className="small muted"> · must pass</span>}</td>
                    <td style={{ width: 80 }}><span className={`pill ${s.outcome === "pass" ? "locked" : s.outcome === "fail" ? "error" : s.outcome === "warn" ? "warning" : ""}`}>{s.outcome}</span></td>
                    <td className="small">{s.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>}

          {mode ? (
            <div className="stack">
              <textarea autoFocus value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder={mode === "reject" ? "Why are you not using it? (optional, kept with the question)" : mode === "regenerate" ? "What should be different? (needed)" : "Approval note (optional)"} />
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
                <button className="primary" disabled={!item.can_approve} title={item.can_approve ? "" : "Change the question first: a check that must pass did not"} onClick={() => { setMode("approve"); setNote(""); }}>
                  Approve
                </button>
              )}
              {item.status !== "rejected" && <button onClick={startEdit}>Edit</button>}
              {item.status !== "rejected" && <button onClick={() => { setMode("reject"); setNote(""); }}>Reject</button>}
              <button onClick={() => { setMode("regenerate"); setNote(""); }}>Replace with a different one</button>
              {item.status === "approved" && (
                <label className="small row" style={{ gap: 4 }} title="Colleagues teaching this course can use it in their own papers">
                  <input type="checkbox" style={{ width: "auto" }} checked={item.shared}
                    onChange={(e) => run(async () => { await api.share(item.id, e.target.checked); onChange({ ...item, shared: e.target.checked }); })} />
                  Share with colleagues
                </label>
              )}
              <button title="Could a strong AI answer this without the course? A report only; it never blocks you."
                onClick={() => run(async () => {
                  const job = await api.solvability(item.id);
                  const done = await waitJob(job.id);
                  setSolv(done.result as any);
                })}>Could AI answer this?</button>
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
type GroupBy = "quiz" | "week" | "outcome" | "none";
const STATUS_TABS = ["all", "suggested", "under_review", "needs_review", "approved", "rejected"] as const;

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
  const [usedFilter, setUsedFilter] = useState("all");
  const [groupBy, setGroupBy] = useState<GroupBy>("quiz");
  const [picked, setPicked] = useState<number[]>([]);
  const [why, setWhy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [materials, setMaterials] = useState<Material[] | null>(null);
  const [assessments, setAssessments] = useState<string[]>([]);

  useEffect(() => {
    Promise.all([api.get(cv), api.draftContext(cv), api.draftTypes(), api.drafts(cv)])
      .then(([vv, c, t, it]) => {
        setV(vv); setCtx(c); setTypes(t); setItems(it);
        setSel(it[0]?.id ?? null);
      })
      .catch((e) => setErr(errText(e)));
    api.materials(cv).then(setMaterials).catch(() => setMaterials([]));
    api.quizOptions(cv).then((o) => setAssessments(o.choices.map((c) => c.name))).catch(() => setAssessments([]));
  }, [cv]);

  const usedNames = useMemo(() => {
    const seen = new Set<string>(assessments);
    for (const i of items) for (const u of i.used_in) seen.add(u.assessment_name);
    return [...seen];
  }, [items, assessments]);

  const shown = useMemo(
    () => items.filter((i) =>
      (filter === "all" || i.status === filter) &&
      (typeFilter === "all" || i.type === typeFilter) &&
      (cloFilter === "all" || i.clo_numbers.includes(Number(cloFilter))) &&
      (weekFilter === "all" || String(i.week_no ?? "") === weekFilter) &&
      (checkFilter === "all" || checkState(i) === checkFilter) &&
      (usedFilter === "all" || (usedFilter === NOT_IN_QUIZ ? i.used_in.length === 0
        : i.used_in.some((u) => u.assessment_name === usedFilter)))),
    [items, filter, typeFilter, cloFilter, weekFilter, checkFilter, usedFilter],
  );

  /* Group headings in a teacher's order: syllabus assessments in syllabus order, then the rest. */
  const groups = useMemo(() => {
    const out = new Map<string, DraftItem[]>();
    const key = (i: DraftItem): string => {
      if (groupBy === "quiz") return i.used_in[0] ? usedLabel(i.used_in[0]) : NOT_IN_QUIZ;
      if (groupBy === "week") return i.week_no ? `Week ${i.week_no}` : "No week";
      if (groupBy === "outcome") return i.clo_numbers.length ? `Learning outcome ${i.clo_numbers[0]}` : "No outcome";
      return "";
    };
    for (const i of shown) {
      const k = key(i);
      out.set(k, [...(out.get(k) ?? []), i]);
    }
    const order = (k: string) => {
      if (groupBy === "quiz") {
        if (k === NOT_IN_QUIZ) return 1e6;
        const idx = usedNames.findIndex((n) => k.startsWith(`${n} · `));
        return idx < 0 ? 1e5 : idx * 100 + k.charCodeAt(k.length - 1);
      }
      const n = Number(k.replace(/\D+/g, ""));
      return Number.isNaN(n) || n === 0 ? 1e6 : n;
    };
    return [...out.entries()].sort((a, b) => order(a[0]) - order(b[0]));
  }, [shown, groupBy, usedNames]);

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

  const togglePick = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const allShownPicked = shown.length > 0 && shown.every((i) => picked.includes(i.id));
  const pickedApproved = items.filter((i) => picked.includes(i.id) && i.status === "approved").map((i) => i.id);

  /* Downloads act on the ticked questions only, never silently on everything. */
  const download = (fn: (ids: number[]) => Promise<unknown>) => {
    setErr(null);
    if (picked.length === 0) {
      setWhy("Tick the questions you want to download first.");
      return;
    }
    if (pickedApproved.length === 0) {
      setWhy("Only approved questions can be downloaded, and none of the ticked ones is approved yet.");
      return;
    }
    setWhy(pickedApproved.length < picked.length
      ? `${picked.length - pickedApproved.length} ticked question(s) are not approved yet and are left out.` : null);
    fn(pickedApproved).catch((e) => setErr(errText(e)));
  };

  if (err && !v) return <div className="error-box">{err}</div>;
  if (!v || !ctx) return <p className="muted">Loading…</p>;
  const rec = v.record;
  const none = picked.length === 0;

  return (
    <div className="stack">
      <div>
        <h1 className="page-title"><Icon name="bank" size={26} /> Question bank</h1>
        <div className="muted" style={{ marginTop: 4 }}>
          {rec.course.code} {rec.course.title} · every question for this course, by the quiz or exam it is in.
          To make a whole paper at once, use <Link to={`/v/${cv}/quiz`}>Quizzes and exams</Link>.
        </div>
      </div>

      <div className="card selection-bar">
        <span className="small"><strong>{picked.length}</strong> selected{" "}
          <span className="muted">· {counts.approved ?? 0} approved in the bank</span></span>
        <div className="export-group">
          <span className="small">Question paper</span>
          {(["docx", "pdf"] as const).map((f) => (
            <button key={f} className={none ? "soft-disabled" : ""} aria-disabled={none ? "true" : undefined}
              onClick={() => download((ids) => api.exportItems(cv, f, "paper", ids))}>{f === "docx" ? "Word" : "PDF"}</button>
          ))}
        </div>
        <div className="export-group">
          <span className="small">Answer key</span>
          {(["docx", "pdf"] as const).map((f) => (
            <button key={f} className={none ? "soft-disabled" : ""} aria-disabled={none ? "true" : undefined}
              onClick={() => download((ids) => api.exportItems(cv, f, "key", ids))}>{f === "docx" ? "Word" : "PDF"}</button>
          ))}
        </div>
        <details className="more-menu">
          <summary className="btn"><Icon name="more" size={16} /> More</summary>
          <div className="more-pop">
            <button onClick={() => download((ids) => api.postDownload(`/api/course-versions/${cv}/qti`, { item_ids: ids }, "questions_qti.zip"))}>
              Download selected for Blackboard
            </button>
            <label className="button-like" style={{ cursor: "pointer" }}>
              <input type="file" accept=".docx,.pdf,.txt,.zip" className="sr-only"
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
              Add questions from a file…
            </label>
          </div>
        </details>
      </div>
      {why && <p className="why" role="alert"><Icon name="info" size={16} /> {why}</p>}
      {err && <div className="error-box">{err}</div>}

      {ctx.can_generate ? (
        <RequestForm cv={cv} ctx={ctx} types={types} materials={materials} onDone={(news) => { setItems((p) => [...news.slice().reverse(), ...p]); setSel(news[0]?.id ?? sel); setFilter("all"); }} />
      ) : (
        <div className="gate"><div className="grow small">Questions are written from a confirmed syllabus. You can still read and reuse the ones already here.</div></div>
      )}

      <div className="drafts-layout">
        <div className="card" style={{ padding: 12 }}>
          <div className="tabbar" role="group" aria-label="Show questions that are">
            {STATUS_TABS.map((k) => (
              <button key={k} aria-pressed={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
                {k === "all" ? "All" : STATUS_LABEL[k]} <span className="count">{k === "all" ? items.length : counts[k] ?? 0}</span>
              </button>
            ))}
          </div>
          <select className="tab-select" value={filter} aria-label="Show questions that are"
            onChange={(e) => setFilter(e.target.value as ItemStatus | "all")}>
            {STATUS_TABS.map((k) => (
              <option key={k} value={k}>{k === "all" ? "All" : STATUS_LABEL[k]} ({k === "all" ? items.length : counts[k] ?? 0})</option>
            ))}
          </select>
          <div className="filter-grid">
            <select value={usedFilter} onChange={(e) => setUsedFilter(e.target.value)} aria-label="Used in">
              <option value="all">Used in: any</option>
              {usedNames.map((n) => <option key={n} value={n}>{n}</option>)}
              <option value={NOT_IN_QUIZ}>{NOT_IN_QUIZ}</option>
            </select>
            <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)} aria-label="Group by">
              <option value="quiz">Group by: Quiz or exam</option>
              <option value="week">Group by: Week</option>
              <option value="outcome">Group by: Learning outcome</option>
              <option value="none">Group by: None</option>
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter by type">
              <option value="all">Every kind</option>
              {types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
            </select>
            <select value={cloFilter} onChange={(e) => setCloFilter(e.target.value)} aria-label="Filter by learning outcome">
              <option value="all">Every outcome</option>
              {ctx.clos.map((c) => <option key={c.number} value={c.number}>Outcome {c.number}</option>)}
            </select>
            <select value={weekFilter} onChange={(e) => setWeekFilter(e.target.value)} aria-label="Filter by week">
              <option value="all">All weeks</option>
              {ctx.weeks.map((w) => <option key={w.week_no} value={w.week_no}>Week {w.week_no}</option>)}
            </select>
            <select value={checkFilter} onChange={(e) => setCheckFilter(e.target.value)} aria-label="Filter by check result">
              <option value="all">Any check result</option>
              <option value="ok">Checks passed</option>
              <option value="to_check">Something to look at</option>
              <option value="blocked">Needs a change</option>
            </select>
          </div>
          {shown.length > 0 && (
            <label className="small row pick-all">
              <input type="checkbox" checked={allShownPicked}
                onChange={() => setPicked(allShownPicked ? picked.filter((id) => !shown.some((s) => s.id === id))
                  : [...new Set([...picked, ...shown.map((s) => s.id)])])} />
              Select all {shown.length} shown
            </label>
          )}
          {shown.length === 0 && <p className="muted small">No questions here yet.</p>}
          {groups.map(([name, list]) => {
            const rows = list.map((it) => (
              <div key={it.id} className={`draft-item ${sel === it.id ? "sel" : ""}`}>
                <input type="checkbox" checked={picked.includes(it.id)} onChange={() => togglePick(it.id)}
                  aria-label={`Select question #${it.id}`} />
                <button className="draft-row" onClick={() => setSel(it.id)}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <span className="small"><strong>#{it.id}</strong> {it.type_label} · Outcome {it.clo_numbers.join(", ")}</span>
                    <span className={`pill ${STATUS_CLASS[it.status]}`}>{STATUS_LABEL[it.status]}</span>
                  </div>
                  <div className="small" style={{ margin: "4px 0", textAlign: "left" }}>{summary(it)}</div>
                  <div className="row wrap" style={{ gap: 6 }}>
                    {it.used_in.length
                      ? it.used_in.map((u) => <span key={u.form_id} className="pill brand">{usedLabel(u)}</span>)
                      : <span className="pill neutral">{NOT_IN_QUIZ}</span>}
                    {checkBadge(it)}
                  </div>
                </button>
              </div>
            ));
            return groupBy === "none" ? <div key="all">{rows}</div> : (
              <details key={name} open className="bank-group">
                <summary><span>{name}</span><span className="count">{list.length}</span></summary>
                {rows}
              </details>
            );
          })}
        </div>
        <div>{current ? <Detail item={current} onChange={upsert} /> : <div className="card muted">Select a question.</div>}</div>
      </div>
    </div>
  );
}
