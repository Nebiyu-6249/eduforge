import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import Icon from "../components/Icon";
import QuizReview from "../components/QuizReview";
import { againUrl } from "../components/quizUrl";
import type { QuizForm } from "../types";

/* One quiz or exam. While it is being written it shows the progress and the
   questions written so far (they arrive one kind at a time); the teacher can
   leave and come back to this address. When it is written, it is the paper
   to review. */

function errText(e: unknown) {
  return e instanceof ApiError ? e.message : String(e);
}

export default function QuizPage() {
  const { id, formId } = useParams();
  const cv = Number(id);
  const fid = Number(formId);
  const nav = useNavigate();
  const [form, setForm] = useState<QuizForm | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => api.form(fid).then(setForm).catch((e) => setErr(errText(e))), [fid]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (form?.status !== "writing") return;
    const t = window.setInterval(load, 2500);
    return () => window.clearInterval(t);
  }, [form?.status, load]);

  if (err && !form) {
    return (
      <div className="stack">
        <div className="error-box">{err}</div>
        <Link className="btn" to={`/v/${cv}/quiz`}>Back to quizzes and exams</Link>
      </div>
    );
  }
  if (!form) return <p className="muted">Loading…</p>;

  const backLink = (
    <Link className="back-link" to={`/v/${cv}/quiz`}><Icon name="back" size={16} /> Quizzes and exams</Link>
  );

  if (form.status === "writing") {
    const pct = form.job?.progress ?? 0;
    const ordered = [...form.items].sort((a, b) => a.position - b.position);
    return (
      <div className="stack">
        {backLink}
        <div className="page-head">
          <div>
            <h1>{form.assessment_name} · Version {form.version_label}</h1>
            <p className="lede">EduForge is writing {form.asked_for} question{form.asked_for === 1 ? "" : "s"}.</p>
          </div>
        </div>
        <section className="card">
          <div className="msg info">
            <Icon name="activity" size={18} />
            <div className="grow">
              <strong>You can leave this page</strong>
              We'll keep writing and let you know when it's ready. It also shows under the clock icon at the top.
            </div>
          </div>
          <div className="writing-progress">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{form.question_count} of {form.asked_for} written</strong>
              <span className="muted">{form.job?.time_left ?? "Starting"}</span>
            </div>
            <div className="progress big" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
              aria-label="Writing the questions">
              <span style={{ width: `${Math.max(4, pct)}%` }} />
            </div>
          </div>
          {ordered.length > 0 && (
            <>
              <h3 style={{ marginTop: 24 }}>Written so far</h3>
              <ol className="written-so-far">
                {ordered.map((fi) => <li key={fi.item_id}>{fi.summary}</li>)}
              </ol>
            </>
          )}
        </section>
      </div>
    );
  }

  if (form.status === "failed") {
    return (
      <div className="stack">
        {backLink}
        <div className="page-head"><h1>{form.assessment_name} · Version {form.version_label}</h1></div>
        <section className="card">
          <div className="msg danger">
            <Icon name="warning" size={18} />
            <div className="grow">
              <strong>This quiz could not be finished</strong>
              {form.error ?? "Something went wrong while writing this quiz. Try again."}
            </div>
          </div>
          <div className="row wrap" style={{ marginTop: 16 }}>
            <Link className="btn primary" to={againUrl(cv, form)}>Try again</Link>
            <button onClick={async () => { await api.deleteForm(form.id).catch(() => undefined); nav(`/v/${cv}/quiz`); }}>
              Remove it
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="stack">
      {backLink}
      {form.error && (
        <div className="msg warn">
          <Icon name="warning" size={18} />
          <div className="grow"><strong>Not every question could be written</strong>{form.error}</div>
        </div>
      )}
      <QuizReview cv={cv} formId={fid} onStartAnother={() => nav(`/v/${cv}/quiz/new`)} />
    </div>
  );
}
