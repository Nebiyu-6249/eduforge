import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, waitJob } from "../api";
import Icon from "../components/Icon";
import QuizReview from "../components/QuizReview";
import type { QuizChoice, QuizMixPart, QuizOptions } from "../types";

/* "Create a quiz or exam" — four short steps, one question each, then the
   paper to review. One thing per step, Back and Continue, in the shape of a
   GOV.UK question page; the mix table is Canvas' "how many, worth how much"
   and Microsoft Forms' per-type add. */

const STEP_TITLES = ["What are you making?", "What should it cover?", "How many of each type?", "Write the questions"];
const PRACTICE = "__practice__";

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

export default function QuizFlow() {
  const cv = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const [o, setO] = useState<QuizOptions | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [step, setStep] = useState(0);
  const [choice, setChoice] = useState<string | null>(null);
  const [weeks, setWeeks] = useState<number[]>([]);
  const [outcomes, setOutcomes] = useState<number[]>([]);
  const [mix, setMix] = useState<Record<string, number>>({});
  const [points, setPoints] = useState<Record<string, number>>({});
  const [difficulty, setDifficulty] = useState("medium");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [formId, setFormId] = useState<number | null>(
    params.get("form") ? Number(params.get("form")) : null);

  useEffect(() => {
    api.quizOptions(cv).then((opts) => {
      setO(opts);
      const want = params.get("assessment");
      const found = want ? opts.choices.find((c) => c.name === want) : null;
      if (found) {
        setChoice(found.name);
        setWeeks(found.weeks);
        setOutcomes(found.clo_numbers);
        setStep(1);
      }
      setPoints(Object.fromEntries(opts.types.map((t) => [t.type, t.points])));
    }).catch((e) => setErr(errText(e)));
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

  const picked: QuizChoice | null = useMemo(
    () => (o && choice && choice !== PRACTICE ? o.choices.find((c) => c.name === choice) ?? null : null),
    [o, choice]);

  const parts: QuizMixPart[] = useMemo(
    () => Object.entries(mix).filter(([, n]) => n > 0)
      .map(([type, count]) => ({ type, count, points: points[type] ?? 1 })),
    [mix, points]);
  const totalQuestions = parts.reduce((s, p) => s + p.count, 0);
  const totalPoints = parts.reduce((s, p) => s + p.count * p.points, 0);
  const totalMinutes = o ? parts.reduce(
    (s, p) => s + p.count * (o.types.find((t) => t.type === p.type)?.minutes ?? 3), 0) : 0;

  if (err && !o) return <div className="error-box">{err}</div>;
  if (!o) return <p className="muted">Loading…</p>;

  if (formId !== null) {
    return <QuizReview cv={cv} formId={formId} onStartAnother={() => { setFormId(null); setStep(0); setParams({}); }} />;
  }

  if (!o.can_create) {
    return (
      <div className="stack">
        <div className="page-head"><h1>Create a quiz or exam</h1></div>
        <div className="empty">
          <h3>Confirm the syllabus first</h3>
          <p>
            Questions are written from the confirmed syllabus, so that every question is tied to a learning
            outcome and a week that you have signed off. Settle the things to check, then confirm it.
          </p>
          <Link className="btn primary" to={`/v/${cv}`}>Open the syllabus</Link>
        </div>
      </div>
    );
  }

  const skillsOnly = outcomes.length > 0 &&
    outcomes.every((n) => o.outcomes.find((x) => x.number === n)?.skills);

  async function create() {
    setBusy(true);
    setErr(null);
    try {
      const job = await api.createQuiz(cv, {
        assessment_name: choice === PRACTICE ? null : choice,
        weeks, clo_numbers: outcomes, difficulty,
        mix: parts, notes: notes || null,
      });
      const done = await waitJob(job.id, (j) => setStage(j.message ?? ""));
      setFormId(done.result!.form_id as number);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  const canContinue = [
    choice !== null,
    weeks.length > 0 && outcomes.length > 0,
    totalQuestions > 0 && totalQuestions <= o.max_questions,
    true,
  ][step];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Create a quiz or exam</h1>
          <p className="lede">
            Say what you need and EduForge writes all of it in one go. Every question is a draft until you
            approve it.
          </p>
        </div>
      </div>

      <ol className="steps" aria-label="Steps">
        {STEP_TITLES.map((t, i) => (
          <li key={t} className={i < step ? "done" : i === step ? "now" : ""} aria-current={i === step ? "step" : undefined}>
            <span className="dot">{i < step ? <Icon name="check" size={13} /> : i + 1}</span>
            <span>{t}</span>
          </li>
        ))}
      </ol>

      {err && <div className="error-box">{err}</div>}

      <section className="card">
        <h2>{STEP_TITLES[step]}</h2>

        {step === 0 && (
          <div style={{ marginTop: 16 }}>
            <p className="muted small">
              Pick a row from your syllabus and the weeks and outcomes it covers are filled in for you.
            </p>
            <div className="pick-grid" style={{ marginTop: 12 }}>
              {o.choices.map((c) => (
                <button key={`${c.name}-${c.week}`} type="button" aria-pressed={choice === c.name}
                  className={`pick ${choice === c.name ? "on" : ""}`}
                  onClick={() => { setChoice(c.name); setWeeks(c.weeks); setOutcomes(c.clo_numbers); }}>
                  <b>{c.name}</b>
                  <span>{c.subtitle || "No weight or week in the syllabus"}</span>
                </button>
              ))}
              <button type="button" aria-pressed={choice === PRACTICE}
                className={`pick ${choice === PRACTICE ? "on" : ""}`}
                onClick={() => {
                  setChoice(PRACTICE);
                  setWeeks(o.weeks.map((w) => w.week_no));
                  setOutcomes(o.outcomes.map((x) => x.number));
                }}>
                <b>Practice questions</b>
                <span>Not graded. For revision or a worksheet.</span>
              </button>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="stack-tight" style={{ marginTop: 16 }}>
            <div className={`msg ${o.slides.length ? "ok" : "warn"}`}>
              <Icon name="materials" size={18} />
              <div className="grow">
                {o.slides.length ? (
                  <>
                    <strong>Based on your slides</strong>
                    {o.slides.slice(0, 3).map((s) => s.title).join(", ")}
                    {o.slides.length > 3 ? ` and ${o.slides.length - 3} more` : ""}.
                  </>
                ) : (
                  <>
                    <strong>No slides added</strong>
                    Questions will be written from the syllabus only. Adding your slides makes them follow your
                    own wording.
                  </>
                )}
              </div>
              {o.slides.length === 0 && <Link className="btn" to={`/v/${cv}/materials`}>Add slides</Link>}
            </div>

            <div>
              <h3>Weeks</h3>
              <p className="muted small">The questions will stay inside the weeks you tick.</p>
              <div className="week-grid" style={{ marginTop: 8 }}>
                {o.weeks.map((w) => (
                  <button key={w.week_no} type="button" aria-pressed={weeks.includes(w.week_no)}
                    title={w.topics.join("; ")}
                    className={`week-chip ${weeks.includes(w.week_no) ? "on" : ""}`}
                    onClick={() => setWeeks(toggle(weeks, w.week_no))}>
                    {w.week_no}
                  </button>
                ))}
              </div>
              <p className="hint">
                {weeks.length === 0 ? "Tick at least one week." :
                  `Weeks ${weeks.slice(0, 6).join(", ")}${weeks.length > 6 ? "…" : ""}: ` +
                  o.weeks.filter((w) => weeks.includes(w.week_no)).slice(0, 3)
                    .map((w) => w.topics[0]).filter(Boolean).join("; ")}
              </p>
            </div>

            <div>
              <h3>Learning outcomes</h3>
              <div className="check-list" style={{ marginTop: 8 }}>
                {o.outcomes.map((x) => (
                  <label key={x.number} className={`check-row ${outcomes.includes(x.number) ? "on" : ""}`}>
                    <input type="checkbox" checked={outcomes.includes(x.number)}
                      onChange={() => setOutcomes(toggle(outcomes, x.number))} />
                    <span>
                      <b>Outcome {x.number}</b>
                      <span className="sub">{x.text}</span>
                    </span>
                  </label>
                ))}
              </div>
              {outcomes.length === 0 && <p className="hint">Tick at least one outcome.</p>}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="stack-tight" style={{ marginTop: 16 }}>
            {skillsOnly && (
              <div className="msg warn">
                <Icon name="warning" size={18} />
                <div className="grow">
                  <strong>These outcomes are about communication or teamwork</strong>
                  A written question cannot show whether a student can do them. A case study or a marking
                  rubric fits better; you can make those in the question bank.
                </div>
              </div>
            )}
            <div className="bordered">
              <table className="grid">
                <caption className="sr-only">How many questions of each type, and what each is worth</caption>
                <thead>
                  <tr>
                    <th>Question type</th>
                    <th style={{ width: 170 }}>How many</th>
                    <th style={{ width: 150 }}>Points each</th>
                  </tr>
                </thead>
                <tbody>
                  {o.types.map((t) => {
                    const n = mix[t.type] ?? 0;
                    return (
                      <tr key={t.type}>
                        <th scope="row">
                          {t.label}
                          <span className="small muted" style={{ display: "block", fontWeight: 400 }}>
                            about {t.minutes} minute{t.minutes === 1 ? "" : "s"} each
                          </span>
                        </th>
                        <td>
                          <div className="stepper">
                            <button type="button" aria-label={`One fewer ${t.label}`} disabled={n === 0}
                              onClick={() => setMix((m) => ({ ...m, [t.type]: Math.max(0, (m[t.type] ?? 0) - 1) }))}>−</button>
                            <span className="count" aria-live="polite">
                              <span className="sr-only">{t.label}: </span>{n}
                            </span>
                            <button type="button" aria-label={`One more ${t.label}`}
                              disabled={totalQuestions >= o.max_questions}
                              onClick={() => setMix((m) => ({ ...m, [t.type]: (m[t.type] ?? 0) + 1 }))}>+</button>
                          </div>
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`pts-${t.type}`}>Points per {t.label}</label>
                          <input id={`pts-${t.type}`} type="number" min={0} step={0.5} style={{ width: 90 }}
                            value={points[t.type] ?? t.points}
                            onChange={(e) => setPoints((pts) => ({ ...pts, [t.type]: Number(e.target.value) }))} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="running-total" role="status">
              <div><span className="n">{totalQuestions}</span><span className="t">questions</span></div>
              <div><span className="n">{totalPoints}</span><span className="t">points</span></div>
              <div><span className="n">about {totalMinutes}</span><span className="t">minutes to sit</span></div>
            </div>
            {totalQuestions > o.max_questions && (
              <p className="error-box small">
                That is {totalQuestions} questions. EduForge writes up to {o.max_questions} at a time; make a
                second quiz for the rest.
              </p>
            )}

            <div>
              <span className="lbl">Difficulty</span>
              <div className="segmented" role="group" aria-label="Difficulty">
                {[["easy", "Easier"], ["medium", "Mixed"], ["hard", "Harder"]].map(([v, label]) => (
                  <button key={v} type="button" aria-pressed={difficulty === v}
                    className={difficulty === v ? "on" : ""} onClick={() => setDifficulty(v)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <details>
              <summary className="small muted">Advanced options</summary>
              <div style={{ marginTop: 12 }}>
                <label className="lbl" htmlFor="quiz-notes">Anything the questions should do differently?</label>
                <textarea id="quiz-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="For example: use examples from the UAE; no calculators." />
                <p className="hint">
                  The cognitive level comes from the outcomes you picked. Multiple-choice questions never aim
                  above “analyse”, because choosing from a list cannot show more than that.
                </p>
              </div>
            </details>
          </div>
        )}

        {step === 3 && (
          <div className="stack-tight" style={{ marginTop: 16 }}>
            <p>
              EduForge will write <strong>{totalQuestions} question{totalQuestions === 1 ? "" : "s"}</strong>
              {" "}for <strong>{choice === PRACTICE ? "practice" : choice}</strong>, covering{" "}
              {outcomes.length === 1 ? "outcome" : "outcomes"} {outcomes.join(", ")} from week{weeks.length === 1 ? "" : "s"}{" "}
              {weeks[0]}{weeks.length > 1 ? ` to ${weeks[weeks.length - 1]}` : ""}.
            </p>
            <ul className="tight">
              {parts.map((p) => (
                <li key={p.type}>
                  {p.count} × {o.types.find((t) => t.type === p.type)?.label} · {p.points} point
                  {p.points === 1 ? "" : "s"} each
                </li>
              ))}
            </ul>
            <p className="muted small">
              This takes a minute or two. Nothing is final: you review every question before anyone sees it.
            </p>
            {busy && (
              <div className="msg info" role="status">
                <div className="spinner" aria-hidden="true" style={{ margin: 0, width: 20, height: 20 }} />
                <div className="grow"><strong>{stage || "Starting…"}</strong></div>
              </div>
            )}
            <div>
              <button className="primary" disabled={busy || totalQuestions === 0} onClick={create}>
                {busy ? "Working…" : `Create ${totalQuestions} question${totalQuestions === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        )}

        <div className="wizard-nav">
          <button type="button" disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>
            <Icon name="back" size={16} /> Back
          </button>
          {step < 3 && (
            <button type="button" className="primary" disabled={!canContinue} onClick={() => setStep(step + 1)}>
              Continue <Icon name="forward" size={16} />
            </button>
          )}
        </div>
      </section>

      {picked && step > 0 && (
        <p className="small muted">
          Making: {picked.name}{picked.subtitle ? ` · ${picked.subtitle}` : ""}.{" "}
          <button className="link" onClick={() => setStep(0)}>Change</button>
        </p>
      )}
    </div>
  );
}

const toggle = (xs: number[], n: number) =>
  xs.includes(n) ? xs.filter((x) => x !== n) : [...xs, n].sort((a, b) => a - b);
