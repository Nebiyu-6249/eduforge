import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import Icon from "../components/Icon";
import ItemView from "./ItemView";
import Modal from "./Modal";
import type { DraftItem } from "../types";

/* The paper, as a student would see it, with the teacher's actions on each
   card: Approve, Edit, Replace. Microsoft Forms shows the correct answer
   marked on the option itself, so we do too. */

function errText(e: unknown) {
  return e instanceof ApiError
    ? (e.items?.length ? `${e.message} ${e.items.map((i) => i.message ?? i.msg).join("; ")}` : e.message)
    : String(e);
}

interface Props {
  cv: number;
  formId: number;
  onStartAnother: () => void;
}

export default function QuizReview({ cv, formId, onStartAnother }: Props) {
  const [form, setForm] = useState<any | null>(null);
  const [items, setItems] = useState<Record<number, DraftItem>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [replacing, setReplacing] = useState<DraftItem | null>(null);

  const say = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async () => {
    const forms = await api.forms(cv);
    const f = forms.find((x: any) => x.id === formId);
    if (!f) throw new ApiError(404, "That paper is no longer here.");
    setForm(f);
    const got = await Promise.all(f.items.map((fi: any) => api.item(fi.item_id)));
    setItems(Object.fromEntries(got.map((it) => [it.id, it])));
  }, [cv, formId]);

  useEffect(() => {
    load().catch((e) => setErr(errText(e)));
  }, [load]);

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

  if (err && !form) return <div className="error-box">{err}</div>;
  if (!form) return <p className="muted">Loading the paper…</p>;

  const ordered = [...form.items].sort((a: any, b: any) => a.position - b.position);
  const approved = ordered.filter((fi: any) => items[fi.item_id]?.status === "approved").length;
  const allApproved = approved === ordered.length && ordered.length > 0;
  const canBulk = ordered.some((fi: any) => {
    const it = items[fi.item_id];
    return it && it.status !== "approved" && it.can_approve && !hasWarning(it);
  });

  const approveAllClean = () =>
    run(async () => {
      let n = 0;
      for (const fi of ordered) {
        const it = items[fi.item_id];
        if (it && it.status !== "approved" && it.can_approve && !hasWarning(it)) {
          await api.itemAction(it.id, "approve");
          n += 1;
        }
      }
      await load();
      say(`${n} question${n === 1 ? "" : "s"} approved.`);
    });

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{form.assessment_name}</h1>
          <p className="lede">
            Read each question and approve it, change it, or ask for a different one. Nothing leaves EduForge
            until you approve it.
          </p>
        </div>
        <div className="actions">
          <button onClick={onStartAnother}><Icon name="plus" size={16} /> Make another quiz</button>
        </div>
      </div>

      {err && <div className="error-box">{err}</div>}

      <div className="review-bar">
        <div>
          <strong>{approved} of {ordered.length} approved</strong>
          <div className="small muted">
            {form.status === "approved"
              ? "This paper is approved. You can download it."
              : allApproved
                ? "Every question is approved. Approve the paper to download it."
                : "Approve every question, then approve the paper."}
          </div>
        </div>
        <div className="row wrap">
          {canBulk && (
            <button disabled={busy} onClick={approveAllClean}>Approve all that passed the checks</button>
          )}
          {allApproved && form.status !== "approved" && (
            <button className="primary" disabled={busy}
              onClick={() => run(async () => { await api.editForm(form.id, { action: "approve" }); await load(); say("Paper approved."); })}>
              Approve this paper
            </button>
          )}
        </div>
      </div>

      {form.status === "approved" && (
        <section className="card">
          <div className="card-head"><h2>Download</h2></div>
          <div className="row wrap">
            <div className="export-group">
              <span>Question paper</span>
              {(["docx", "pdf"] as const).map((f) => (
                <button key={f} disabled={busy}
                  onClick={() => run(() => api.postDownload(`/api/forms/${form.id}/export`,
                    { format: f, part: "paper" }, `question_paper.${f}`))}>
                  {f === "docx" ? "Word" : "PDF"}
                </button>
              ))}
            </div>
            <div className="export-group">
              <span>Answer key</span>
              {(["docx", "pdf"] as const).map((f) => (
                <button key={f} disabled={busy}
                  onClick={() => run(() => api.postDownload(`/api/forms/${form.id}/export`,
                    { format: f, part: "key" }, `answer_key.${f}`))}>
                  {f === "docx" ? "Word" : "PDF"}
                </button>
              ))}
            </div>
            <Link className="btn" to={`/v/${cv}/quiz`}>Make another version</Link>
          </div>
          <p className="hint">
            Two files: the paper has no answers on it, the key has the correct answer and why, for you.
          </p>
          <details style={{ marginTop: 16 }}>
            <summary className="small muted">Advanced</summary>
            <div className="row wrap" style={{ marginTop: 12 }}>
              <button disabled={busy}
                onClick={() => run(() => api.postDownload(`/api/forms/${form.id}/export`, { format: "qti" },
                  "quiz_qti.zip"))}>
                Download for Blackboard (QTI)
              </button>
              <Link className="btn" to={`/v/${cv}/questions`}>Open the question bank</Link>
              <Link className="btn" to={`/v/${cv}/builder`}>Blueprint and parallel versions</Link>
            </div>
            <p className="hint">
              Build a second version for another section, change the blueprint the paper is matched
              against, or see how often each question has been used.
            </p>
          </details>
        </section>
      )}

      {form.gaps?.length > 0 && (
        <div className="msg warn">
          <Icon name="warning" size={18} />
          <div className="grow">
            <strong>Not everything could be written</strong>
            <ul className="tight small">
              {form.gaps.map((g: any, i: number) => <li key={i}>{g.warning ?? JSON.stringify(g)}</li>)}
            </ul>
          </div>
        </div>
      )}

      {ordered.map((fi: any, n: number) => {
        const it = items[fi.item_id];
        if (!it) return null;
        return (
          <QuestionCard
            key={fi.item_id}
            n={n + 1}
            points={fi.points}
            item={it}
            busy={busy}
            onApprove={() => run(async () => {
              await api.itemAction(it.id, "approve");
              await load();
              say("Approved.");
            })}
            onReplace={() => setReplacing(it)}
            onSaved={async () => { await load(); say("Saved."); }}
          />
        );
      })}

      {replacing && (
        <ReplaceDialog
          item={replacing}
          onClose={() => setReplacing(null)}
          onReplace={async (why) => {
            const r = await api.itemAction(replacing.id, "regenerate", why);
            if (r.job) await waitJob(r.job.id);
            await load();
            say("A different question has been written.");
          }}
        />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

const hasWarning = (it: DraftItem) => it.scores.some((s) => s.outcome === "fail" || s.outcome === "warn");

// --------------------------------------------------------------------------
function QuestionCard({ n, points, item, busy, onApprove, onReplace, onSaved }: {
  n: number; points: number; item: DraftItem; busy: boolean;
  onApprove: () => void; onReplace: () => void; onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const failed = item.scores.filter((s) => s.outcome === "fail");
  const warned = item.scores.filter((s) => s.outcome === "warn");
  const blocked = failed.some((s) => s.hard);
  const approvedNow = item.status === "approved";

  return (
    <article className={`qcard ${approvedNow ? "approved" : ""}`}>
      <header>
        <span className="n">Question {n}</span>
        <span className="row">
          <span className="small muted">{points} point{points === 1 ? "" : "s"}</span>
          {approvedNow && <span className="pill ok">Approved</span>}
        </span>
      </header>
      <div className="body">
        <ItemView item={item} showKey />
        <p className={`answer-note ${blocked ? "check" : failed.length + warned.length ? "check" : "ok"}`}>
          {blocked
            ? "This one needs a change before it can be approved: " + failed.map((s) => s.detail).join(" ")
            : failed.length + warned.length
              ? "Please check this answer: " + [...failed, ...warned].map((s) => s.detail).join(" ")
              : "Answer checked independently and it agrees."}
        </p>
      </div>
      <div className="foot">
        <div className="row wrap">
          {!approvedNow && (
            <button className="primary" disabled={busy || !item.can_approve}
              title={item.can_approve ? "" : "Change the question first"}
              onClick={onApprove}>Approve</button>
          )}
          <button disabled={busy} onClick={() => setEditing(true)}>Edit</button>
          <button disabled={busy} onClick={onReplace}>Replace</button>
        </div>
        <details>
          <summary className="small muted">Details for the team</summary>
          <div className="small muted" style={{ marginTop: 8 }}>
            Outcome {item.clo_numbers.join(", ")}
            {item.week_no ? ` · week ${item.week_no}` : ""} · {item.bloom_level} · {item.difficulty}
            <br />
            {item.model} · {item.prompt_version}
          </div>
        </details>
      </div>
      {editing && (
        <EditDialog item={item} onClose={() => setEditing(false)}
          onSaved={async () => { setEditing(false); await onSaved(); }} />
      )}
    </article>
  );
}

// --------------------------------------------------------------------------
/** A plain form for the parts of a question a teacher actually edits. */
function EditDialog({ item, onClose, onSaved }: { item: DraftItem; onClose: () => void; onSaved: () => Promise<void> }) {
  const [body, setBody] = useState<any>(() => structuredClone(item.body));
  const [key, setKey] = useState<any>(() => (item.answer_key ? structuredClone(item.answer_key) : null));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const stemField = item.type === "mcq" ? "stem" : item.type === "short_answer" ? "question"
    : item.type === "problem" ? "statement" : "prompt";

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await api.editItem(item.id, { body, answer_key: key ?? undefined });
      await onSaved();
    } catch (e) {
      setErr(errText(e));
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Edit this question"
      description="Your change is saved against the question and the checks run again."
      onClose={onClose}
      footer={
        <>
          {err && <div className="error-box small grow">{err}</div>}
          <span className="grow" />
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="primary" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <label className="lbl" htmlFor="q-stem">The question</label>
      <textarea id="q-stem" rows={3} value={body[stemField] ?? ""}
        onChange={(e) => setBody({ ...body, [stemField]: e.target.value })} />

      {item.type === "mcq" && (
        <section className="dlg-sect">
          <h3>Options</h3>
          <p className="hint" style={{ marginTop: 0 }}>Choose the correct one.</p>
          {(body.options ?? []).map((o: any, i: number) => (
            <label key={o.label} className={`choice ${key?.correct === o.label ? "on" : ""}`}>
              <input type="radio" name="correct" checked={key?.correct === o.label}
                onChange={() => setKey({ ...(key ?? {}), correct: o.label })} />
              <span className="text grow">
                <b>{o.label}</b>
                <input value={o.text} aria-label={`Option ${o.label}`}
                  onChange={(e) => {
                    const next = [...body.options];
                    next[i] = { ...o, text: e.target.value };
                    setBody({ ...body, options: next });
                  }} />
              </span>
            </label>
          ))}
          <label className="lbl" htmlFor="q-why" style={{ marginTop: 12 }}>Why that one is correct</label>
          <textarea id="q-why" rows={2} value={key?.why_correct ?? ""}
            onChange={(e) => setKey({ ...(key ?? {}), why_correct: e.target.value })} />
        </section>
      )}

      {item.type === "short_answer" && key && (
        <section className="dlg-sect">
          <h3>What a good answer says</h3>
          <textarea rows={4} aria-label="Model answer" value={key.model_answer ?? ""}
            onChange={(e) => setKey({ ...key, model_answer: e.target.value })} />
        </section>
      )}

      {item.type === "problem" && key && (
        <section className="dlg-sect">
          <h3>The answer</h3>
          <label className="lbl" htmlFor="q-ans">Final answer</label>
          <input id="q-ans" value={key.final_answer_text ?? ""}
            onChange={(e) => setKey({ ...key, final_answer_text: e.target.value })} />
        </section>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------
function ReplaceDialog({ item, onClose, onReplace }: {
  item: DraftItem; onClose: () => void; onReplace: (why: string) => Promise<void>;
}) {
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Ask for a different question"
      description="The one you have is set aside and a new one is written in its place."
      onClose={onClose}
      width={560}
      footer={
        <>
          {err && <div className="error-box small grow">{err}</div>}
          <span className="grow" />
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="primary" disabled={busy || !why.trim()}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await onReplace(why);
                onClose();
              } catch (e) {
                setErr(errText(e));
                setBusy(false);
              }
            }}>
            {busy ? "Writing…" : "Write a different one"}
          </button>
        </>
      }
    >
      <label className="lbl" htmlFor="replace-why">What should be different?</label>
      <textarea id="replace-why" rows={3} value={why} autoFocus
        onChange={(e) => setWhy(e.target.value)}
        placeholder="For example: this is too easy; ask them to compare two methods instead." />
      <p className="hint">Question {item.id} stays in the question bank, marked as not used.</p>
    </Modal>
  );
}
