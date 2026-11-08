import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { announceJob } from "../components/Activity";
import Icon from "../components/Icon";
import {
  clearSession, loadSession, PRACTICE, readChoices, saveSession, writeChoices, type QuizChoices,
} from "../components/quizUrl";
import type { QuizMixPart, QuizOptions } from "../types";

/* "Create a quiz or exam": four short steps, one question each. The step and
   every choice live in the address (GOV.UK question pages, Microsoft Forms),
   so browser Back and Forward move between steps, a refresh keeps the place,
   and the teacher can leave and come back. Pressing Create makes the quiz at
   once; it is written in the background and has its own page. */

const STEP_TITLES = ["What are you making?", "What should it cover?", "How many of each type?", "Write the questions"];
const LEAVE_MSG = "Leave without creating the quiz? Your choices will be kept for this session.";

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

export default function QuizFlow() {
  const cv = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const [o, setO] = useState<QuizOptions | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [why, setWhy] = useState<string | null>(null);  // why Continue can't go on yet
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [resume, setResume] = useState<string | null>(null);
  const sending = useRef(false);
  const askedOnce = useRef(false);

  const c = readChoices(params);
  const set = (next: Partial<QuizChoices>, push = false) => {
    setWhy(null);
    setParams(writeChoices({ ...c, ...next }), { replace: !push });
  };

  useEffect(() => {
    api.quizOptions(cv).then(setO).catch((e) => setErr(errText(e)));
    // Coming back with an empty address: offer the choices kept for this session.
    const saved = loadSession(cv);
    if (!params.toString() && saved && saved !== "step=1") setResume(saved);
  }, [cv]); // eslint-disable-line react-hooks/exhaustive-deps

  // Picked from a link ("Prepare this quiz", "Create" on the list): fill in its weeks and outcomes once.
  useEffect(() => {
    if (!o || !c.for || c.for === PRACTICE || (c.weeks.length && c.outcomes.length)) return;
    const found = o.choices.find((x) => x.name === c.for);
    if (found) set({ weeks: found.weeks, outcomes: found.clo_numbers });
  }, [o, c.for]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (params.toString()) saveSession(cv, params.toString());
  }, [cv, params]);

  const started = c.for !== null;
  const blocker = useBlocker(({ nextLocation }) =>
    started && !sending.current && !askedOnce.current && !nextLocation.pathname.startsWith(`/v/${cv}/quiz/new`));
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    askedOnce.current = true;
    if (window.confirm(LEAVE_MSG)) blocker.proceed();
    else blocker.reset();
  }, [blocker]);

  const parts: QuizMixPart[] = useMemo(
    () => Object.entries(c.mix).filter(([, n]) => n > 0)
      .map(([type, count]) => ({ type, count, points: c.points[type] ?? o?.types.find((t) => t.type === type)?.points ?? 1 })),
    [c.mix, c.points, o]);
  const totalQuestions = parts.reduce((s, p) => s + p.count, 0);
  const totalPoints = parts.reduce((s, p) => s + p.count * p.points, 0);
  const totalMinutes = o ? parts.reduce((s, p) => s + p.count * (o.types.find((t) => t.type === p.type)?.minutes ?? 3), 0) : 0;

  if (err && !o) return <div className="error-box">{err}</div>;
  if (!o) return <p className="muted">Loading…</p>;

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

  const step = c.step;
  const picked = c.for && c.for !== PRACTICE ? o.choices.find((x) => x.name === c.for) ?? null : null;
  const skillsOnly = c.outcomes.length > 0 && c.outcomes.every((n) => o.outcomes.find((x) => x.number === n)?.skills);

  const blockReason = [
    c.for === null ? "Pick what you are making first." : null,
    c.weeks.length === 0 ? "Tick at least one week." : c.outcomes.length === 0 ? "Tick at least one learning outcome." : null,
    totalQuestions === 0 ? "Add at least one question with the + buttons."
      : totalQuestions > o.max_questions ? `EduForge writes up to ${o.max_questions} questions at a time.` : null,
    null,
  ][step - 1];

  const goTo = (n: number) => set({ step: n }, true);
  const next = () => (blockReason ? setWhy(blockReason) : goTo(step + 1));
  const back = () => (step === 1 ? nav(`/v/${cv}/quiz`) : goTo(step - 1));

  async function create() {
    if (blockReason || totalQuestions === 0) {
      setWhy(blockReason ?? "Add at least one question first.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const job = await api.createQuiz(cv, {
        assessment_name: c.for === PRACTICE ? null : c.for,
        weeks: c.weeks, clo_numbers: c.outcomes, difficulty: c.difficulty,
        mix: parts, notes: notes || null,
      });
      sending.current = true;
      clearSession(cv);
      announceJob();
      // The quiz exists from this moment; its page shows the writing and survives leaving.
      nav(job.link ?? `/v/${cv}/quiz`, { replace: true });
    } catch (e) {
      setErr(errText(e));
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Create a quiz or exam</h1>
          <p className="lede">
            Say what you need and EduForge writes all of it in one go. Every question is a draft until you approve it.
          </p>
        </div>
      </div>

      {resume && (
        <div className="msg info">
          <Icon name="info" size={18} />
          <div className="grow"><strong>You started a quiz earlier</strong> Pick up where you left off, or start again.</div>
          <div className="row">
            <button className="primary" onClick={() => { setParams(new URLSearchParams(resume), { replace: true }); setResume(null); }}>
              Continue
            </button>
            <button onClick={() => { clearSession(cv); setResume(null); }}>Start again</button>
          </div>
        </div>
      )}

      <div className="steps-wrap">
        <ol className="steps" aria-label="The four steps">
          {STEP_TITLES.map((t, i) => (
            <li key={t} className={i + 1 < step ? "done" : i + 1 === step ? "now" : ""} aria-current={i + 1 === step ? "step" : undefined}>
              <span className="dot">{i + 1 < step ? <Icon name="check" size={13} /> : i + 1}</span>
              <span>{t}</span>
            </li>
          ))}
        </ol>
      </div>

      {err && <div className="error-box" role="alert">{err}</div>}

      <section className="card">
        <h2>{STEP_TITLES[step - 1]}</h2>

        {step === 1 && (
          <div style={{ marginTop: 16 }}>
            <p className="muted small">Pick a row from your syllabus and the weeks and outcomes it covers are filled in for you.</p>
            <div className="pick-grid" style={{ marginTop: 12 }}>
              {o.choices.map((x) => (
                <button key={`${x.name}-${x.week}`} type="button" aria-pressed={c.for === x.name}
                  className={`pick ${c.for === x.name ? "on" : ""}`}
                  onClick={() => set({ for: x.name, weeks: x.weeks, outcomes: x.clo_numbers })}>
                  <b>{x.name}</b>
                  <span>{x.subtitle || "No weight or week in the syllabus"}</span>
                </button>
              ))}
              <button type="button" aria-pressed={c.for === PRACTICE} className={`pick ${c.for === PRACTICE ? "on" : ""}`}
                onClick={() => set({ for: PRACTICE, weeks: o.weeks.map((w) => w.week_no), outcomes: o.outcomes.map((x) => x.number) })}>
                <b>Practice questions</b>
                <span>Not graded. For revision or a worksheet.</span>
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
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
                    Questions will be written from the syllabus only. Adding your slides makes them follow your own wording.
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
                  <button key={w.week_no} type="button" aria-pressed={c.weeks.includes(w.week_no)} title={w.topics.join("; ")}
                    className={`week-chip ${c.weeks.includes(w.week_no) ? "on" : ""}`}
                    onClick={() => set({ weeks: toggle(c.weeks, w.week_no) })}>
                    {w.week_no}
                  </button>
                ))}
              </div>
              <p className="hint">
                {c.weeks.length === 0 ? "Tick at least one week." :
                  `Weeks ${c.weeks.slice(0, 6).join(", ")}${c.weeks.length > 6 ? "…" : ""}: ` +
                  o.weeks.filter((w) => c.weeks.includes(w.week_no)).slice(0, 3).map((w) => w.topics[0]).filter(Boolean).join("; ")}
              </p>
            </div>

            <div>
              <h3>Learning outcomes</h3>
              <div className="check-list" style={{ marginTop: 8 }}>
                {o.outcomes.map((x) => (
                  <label key={x.number} className={`check-row ${c.outcomes.includes(x.number) ? "on" : ""}`}>
                    <input type="checkbox" checked={c.outcomes.includes(x.number)}
                      onChange={() => set({ outcomes: toggle(c.outcomes, x.number) })} />
                    <span><b>Outcome {x.number}</b><span className="sub">{x.text}</span></span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="stack-tight" style={{ marginTop: 16 }}>
            {skillsOnly && (
              <div className="msg warn">
                <Icon name="warning" size={18} />
                <div className="grow">
                  <strong>These outcomes are about communication or teamwork</strong>
                  A written question cannot show whether a student can do them. A case study or a marking rubric fits
                  better; you can make those in the question bank.
                </div>
              </div>
            )}
            <div className="bordered">
              <table className="grid">
                <caption className="sr-only">How many questions of each type, and what each is worth</caption>
                <thead>
                  <tr><th>Question type</th><th style={{ width: 170 }}>How many</th><th style={{ width: 150 }}>Points each</th></tr>
                </thead>
                <tbody>
                  {o.types.map((t) => {
                    const n = c.mix[t.type] ?? 0;
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
                              onClick={() => set({ mix: { ...c.mix, [t.type]: Math.max(0, n - 1) } })}>−</button>
                            <span className="count" aria-live="polite"><span className="sr-only">{t.label}: </span>{n}</span>
                            <button type="button" aria-label={`One more ${t.label}`}
                              aria-disabled={totalQuestions >= o.max_questions ? "true" : undefined}
                              className={totalQuestions >= o.max_questions ? "soft-disabled" : ""}
                              onClick={() => (totalQuestions >= o.max_questions
                                ? setWhy(`EduForge writes up to ${o.max_questions} questions at a time. Make a second quiz for the rest.`)
                                : set({ mix: { ...c.mix, [t.type]: n + 1 } }))}>+</button>
                          </div>
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`pts-${t.type}`}>Points per {t.label}</label>
                          <input id={`pts-${t.type}`} type="number" min={0} step={0.5} style={{ width: 90 }}
                            value={c.points[t.type] ?? t.points}
                            onChange={(e) => set({ points: { ...c.points, [t.type]: Number(e.target.value) } })} />
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

            <div>
              <span className="lbl">Difficulty</span>
              <div className="segmented" role="group" aria-label="Difficulty">
                {[["easy", "Easier"], ["medium", "Mixed"], ["hard", "Harder"]].map(([v, label]) => (
                  <button key={v} type="button" aria-pressed={c.difficulty === v} className={c.difficulty === v ? "on" : ""}
                    onClick={() => set({ difficulty: v })}>{label}</button>
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
                  The type of thinking comes from the outcomes you picked. Multiple-choice questions never aim above
                  “analyse”, because choosing from a list cannot show more than that.
                </p>
              </div>
            </details>
          </div>
        )}

        {step === 4 && (
          <div className="stack-tight" style={{ marginTop: 16 }}>
            <p>
              EduForge will write <strong>{totalQuestions} question{totalQuestions === 1 ? "" : "s"}</strong> for{" "}
              <strong>{c.for === PRACTICE ? "practice" : c.for}</strong>, covering{" "}
              {c.outcomes.length === 1 ? "outcome" : "outcomes"} {c.outcomes.join(", ")} from week{c.weeks.length === 1 ? "" : "s"}{" "}
              {c.weeks[0]}{c.weeks.length > 1 ? ` to ${c.weeks[c.weeks.length - 1]}` : ""}.
            </p>
            <ul className="tight">
              {parts.map((p) => (
                <li key={p.type}>
                  {p.count} × {o.types.find((t) => t.type === p.type)?.label} · {p.points} point{p.points === 1 ? "" : "s"} each
                </li>
              ))}
            </ul>
            <div className="msg info">
              <Icon name="activity" size={18} />
              <div className="grow">
                <strong>You can leave this page</strong>
                This takes a minute or two. We'll keep writing and let you know when it's ready. Nothing is final:
                you review every question before anyone sees it.
              </div>
            </div>
            <div>
              <button className="primary" disabled={busy} onClick={create}>
                {busy ? "Starting…" : `Create ${totalQuestions} question${totalQuestions === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        )}

        {why && <p className="why" role="alert"><Icon name="info" size={16} /> {why}</p>}

        <div className="wizard-nav">
          <button type="button" onClick={back}>
            <Icon name="back" size={16} /> {step === 1 ? "Back to quizzes and exams" : "Back"}
          </button>
          {step < 4 && (
            <button type="button" className={`primary ${blockReason ? "soft-disabled" : ""}`}
              aria-disabled={blockReason ? "true" : undefined} onClick={next}>
              Continue <Icon name="forward" size={16} />
            </button>
          )}
        </div>
      </section>

      {picked && step > 1 && (
        <p className="small muted">
          Making: {picked.name}{picked.subtitle ? ` · ${picked.subtitle}` : ""}.{" "}
          <button className="link" onClick={() => goTo(1)}>Change</button>
        </p>
      )}
    </div>
  );
}

const toggle = (xs: number[], n: number) => (xs.includes(n) ? xs.filter((x) => x !== n) : [...xs, n].sort((a, b) => a - b));
