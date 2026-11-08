import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { JOB_FINISHED } from "../components/Activity";
import Icon from "../components/Icon";
import { againUrl, newQuizUrl, PRACTICE } from "../components/quizUrl";
import { fmtDate } from "../components/util";
import type { QuizForm, QuizOptions } from "../types";

/* Every quiz and exam of the course, under the syllabus row it is for, in
   syllabus order, so the page doubles as the term's checklist (Canvas lists
   assignments by group the same way). Rows that are still being written show
   their progress and keep updating. */

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

function statusOf(f: QuizForm): { text: string; tone: string; action: string } {
  if (f.status === "writing") return { text: `Writing… ${f.job?.time_left ?? ""}`.trim(), tone: "info", action: "Open" };
  if (f.status === "failed") return { text: "Couldn't finish", tone: "danger", action: "Try again" };
  if (f.status === "approved") return { text: "Ready to download", tone: "ok", action: "Open" };
  return {
    text: f.question_count === 0 ? "No questions" : `${f.approved_count} of ${f.question_count} approved`,
    tone: f.approved_count === f.question_count && f.question_count > 0 ? "ok" : "attention",
    action: "Review",
  };
}

export default function QuizList() {
  const cv = Number(useParams().id);
  const [o, setO] = useState<QuizOptions | null>(null);
  const [forms, setForms] = useState<QuizForm[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => api.forms(cv).then(setForms).catch((e) => setErr(errText(e))), [cv]);
  useEffect(() => {
    api.quizOptions(cv).then(setO).catch((e) => setErr(errText(e)));
    load();
  }, [cv, load]);

  // Rows being written refresh themselves; any finished job refreshes the list.
  const writing = forms?.some((f) => f.status === "writing");
  useEffect(() => {
    if (!writing) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [writing, load]);
  useEffect(() => {
    const on = () => load();
    window.addEventListener(JOB_FINISHED, on);
    return () => window.removeEventListener(JOB_FINISHED, on);
  }, [load]);

  if (err && !forms) return <div className="error-box">{err}</div>;
  if (!o || !forms) return <p className="muted">Loading…</p>;

  if (!o.can_create) {
    return (
      <div className="stack">
        <div className="page-head"><h1>Quizzes and exams</h1></div>
        <div className="empty">
          <h3>Confirm the syllabus first</h3>
          <p>Quizzes are written from the confirmed syllabus. Settle the things to check, then confirm it.</p>
          <Link className="btn primary" to={`/v/${cv}`}>Open the syllabus</Link>
        </div>
      </div>
    );
  }

  // Syllabus rows in syllabus order, then practice, then anything else (older builder papers).
  const names = o.choices.map((x) => x.name);
  const groups: { name: string; subtitle: string; forms: QuizForm[]; forNew: string }[] = o.choices.map((x) => ({
    name: x.name, subtitle: x.subtitle, forNew: x.name,
    forms: forms.filter((f) => f.assessment_name === x.name),
  }));
  groups.push({ name: "Practice questions", subtitle: "Not graded", forNew: PRACTICE,
    forms: forms.filter((f) => f.assessment_name === "Practice questions") });
  const other = forms.filter((f) => !names.includes(f.assessment_name) && f.assessment_name !== "Practice questions");
  if (other.length) groups.push({ name: "Other papers", subtitle: "", forNew: PRACTICE, forms: other });

  const made = forms.length;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Quizzes and exams</h1>
          <p className="lede">
            Every quiz and exam for {o.course}, under the syllabus row it is for.{" "}
            {made === 0 ? "Nothing made yet." : `${made} made so far.`}
          </p>
        </div>
        <div className="actions">
          <Link className="btn primary" to={newQuizUrl(cv)}><Icon name="plus" size={16} /> New quiz or exam</Link>
        </div>
      </div>

      <section className="card flush">
        <table className="grid quiz-list">
          <caption className="sr-only">Quizzes and exams by syllabus assessment</caption>
          <thead>
            <tr><th>Quiz or exam</th><th>Questions</th><th>Status</th><th>Last change</th><th><span className="sr-only">Action</span></th></tr>
          </thead>
          {groups.map((g) => (
            <tbody key={g.name}>
              <tr className="group-row">
                <th colSpan={4} scope="rowgroup">
                  {g.name}{g.subtitle && <span className="small muted"> · {g.subtitle}</span>}
                </th>
                <td className="num">
                  {g.forms.length === 0 && (
                    <Link className="link" to={newQuizUrl(cv, { step: g.forNew === PRACTICE ? 1 : 2, for: g.forNew })}>
                      Create
                    </Link>
                  )}
                </td>
              </tr>
              {g.forms.map((f) => {
                const s = statusOf(f);
                const to = f.status === "failed" ? againUrl(cv, f) : `/v/${cv}/quiz/${f.id}`;
                return (
                  <tr key={f.id}>
                    <td><Link to={`/v/${cv}/quiz/${f.id}`}><strong>{f.assessment_name} · Version {f.version_label}</strong></Link></td>
                    <td className="num">
                      {f.status === "writing" ? `${f.question_count} of ${f.asked_for}` : f.question_count}
                      {f.points > 0 && <span className="small muted"> · {f.points} points</span>}
                    </td>
                    <td>
                      <span className={`pill ${s.tone}`}>{s.text}</span>
                      {f.status === "writing" && f.job && (
                        <div className="progress slim" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                          aria-valuenow={f.job.progress} aria-label={`${f.assessment_name} progress`}>
                          <span style={{ width: `${Math.max(4, f.job.progress)}%` }} />
                        </div>
                      )}
                      {f.status === "failed" && f.error && <div className="small err-text">{f.error}</div>}
                    </td>
                    <td className="num small muted">{fmtDate(f.last_change ?? f.created_at)}</td>
                    <td className="num"><Link className="btn" to={to}>{s.action}</Link></td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      </section>
    </div>
  );
}
