import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import Icon from "../components/Icon";
import type { Dashboard as DashboardData, DayCount } from "../types";

/** The first screen. Four numbers, a week of activity, the teacher's courses,
 *  how ready the term is, and the next assessment due. */
export default function Dashboard() {
  const [d, setD] = useState<DashboardData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.dashboard().then(setD).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (err) return <div className="error-box">{err}</div>;
  if (!d) return <p className="muted">Loading your courses…</p>;

  const empty = d.courses.length === 0 && d.kpis.every((k) => k.value === 0);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Welcome back, {d.teacher.replace(/^Dr\.?\s+/i, "")}</h1>
          <p className="lede">
            {d.term
              ? `Here is where ${d.term} stands.`
              : "Upload a syllabus to get started: EduForge reads the course from it and writes questions once you confirm it."}
          </p>
        </div>
        <div className="actions">
          <Link className="btn primary" to="/courses"><Icon name="plus" size={16} /> Upload a syllabus</Link>
        </div>
      </div>

      {empty ? (
        <div className="empty">
          <h3>Nothing here yet</h3>
          <p>
            Start by uploading a syllabus that your department has already approved. EduForge reads the course,
            the learning outcomes and the weekly plan from it, and lists anything in the file that does not add up.
          </p>
          <Link className="btn primary" to="/courses">Upload a syllabus</Link>
        </div>
      ) : (
        <>
          <div className="grid-4">
            {d.kpis.map((k, i) => (
              <Link key={k.key} to={k.href} className={`kpi ${i === 0 ? "highlight" : ""}`}>
                <div className="label">{k.label}</div>
                <div className="value">{k.value}</div>
                <div className="note">{k.note}</div>
              </Link>
            ))}
          </div>

          <div className="grid-2">
            <WeekChart week={d.week} />
            <div className="stack-tight">
              <Readiness r={d.readiness} />
              {d.next_assessment ? (
                <div className="highlight-block">
                  <h3>Next assessment</h3>
                  <div className="when">
                    {d.next_assessment.days_away === 0 ? "Today"
                      : d.next_assessment.days_away === 1 ? "Tomorrow"
                      : `In ${d.next_assessment.days_away} days`}
                  </div>
                  <div className="sub">
                    {d.next_assessment.course} · {d.next_assessment.name} · {d.next_assessment.due}
                  </div>
                  <Link className="btn" to={d.next_assessment.href}>Prepare this quiz</Link>
                </div>
              ) : (
                <div className="card">
                  <h3>Next assessment</h3>
                  <p className="muted small" style={{ marginTop: 8 }}>
                    No dated assessment is coming up in a confirmed syllabus. Dates come from the weekly plan.
                  </p>
                </div>
              )}
            </div>
          </div>

          <section className="card">
            <div className="card-head">
              <div>
                <h2>Your courses</h2>
                <p className="muted small" style={{ margin: 0 }}>{d.term ?? "All terms"}</p>
              </div>
              <Link className="btn" to="/courses">See all</Link>
            </div>
            {d.courses.length === 0 ? (
              <p className="muted">No courses in this term yet.</p>
            ) : (
              <div className="scroll-x">
                <table className="grid">
                  <caption className="sr-only">Your courses this term and what each one needs</caption>
                  <thead>
                    <tr>
                      <th>Course</th>
                      <th style={{ width: 120 }}>Term</th>
                      <th style={{ width: 220 }}>What it needs</th>
                      <th style={{ width: 100 }} />
                    </tr>
                  </thead>
                  <tbody>
                    {d.courses.map((c) => (
                      <tr key={c.id}>
                        <th scope="row">
                          <span className="row">
                            <span className="avatar sm" aria-hidden="true">{c.initials}</span>
                            <span>
                              {c.code}
                              <span className="small muted" style={{ display: "block", fontWeight: 400 }}>{c.title}</span>
                            </span>
                          </span>
                        </th>
                        <td>{c.term}</td>
                        <td><span className={`pill ${c.tone}`}>{c.status}</span></td>
                        <td><Link className="btn" to={c.href}>Open</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
function WeekChart({ week }: { week: DayCount[] }) {
  const max = Math.max(1, ...week.map((w) => Math.max(w.created, w.approved)));
  const total = week.reduce((s, w) => s + w.created, 0);
  return (
    <section className="card chart-card">
      <div className="card-head">
        <div>
          <h2>Questions this week</h2>
          <p className="muted small" style={{ margin: 0 }}>
            {total === 0 ? "Nothing written in the last seven days." : `${total} written in the last seven days.`}
          </p>
        </div>
      </div>
      <div className="bars" aria-hidden="true">
        {week.map((w) => (
          <div className="day" key={w.date}>
            <div className="pair">
              <div className="bar created" style={{ height: `${(w.created / max) * 100}%` }} />
              <div className="bar approved" style={{ height: `${(w.approved / max) * 100}%` }} />
            </div>
            <div className="daylabel">{w.day}</div>
          </div>
        ))}
      </div>
      <div className="legend" style={{ marginTop: 12 }}>
        <span className="key"><span className="swatch created" /> Written</span>
        <span className="key"><span className="swatch approved" /> Approved by you</span>
      </div>
      {/* The same numbers as a table, for anyone who cannot see the bars. */}
      <details style={{ marginTop: 12 }}>
        <summary className="small muted">Show these numbers as a table</summary>
        <table className="grid" style={{ marginTop: 8 }}>
          <caption className="sr-only">Questions written and approved on each of the last seven days</caption>
          <thead><tr><th>Day</th><th className="c">Written</th><th className="c">Approved</th></tr></thead>
          <tbody>
            {week.map((w) => (
              <tr key={w.date}>
                <th scope="row">{w.day} {w.date}</th>
                <td className="c num">{w.created}</td>
                <td className="c num">{w.approved}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

// --------------------------------------------------------------------------
function Readiness({ r }: { r: { confirmed: number; ready: number; needs_checking: number; total: number } }) {
  const pct = r.total ? Math.round((r.confirmed / r.total) * 100) : 0;
  // A half circle of radius 90, so the arc is pi x 90 long. Two arcs on a grey
  // track: crimson up to "confirmed", gold on to "ready to confirm".
  const len = Math.PI * 90;
  const share = (n: number) => (r.total ? (n / r.total) * len : 0);
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>Term readiness</h2>
          <p className="muted small" style={{ margin: 0 }}>Syllabuses you have confirmed for this term</p>
        </div>
      </div>
      <div className="gauge">
        <svg width="220" height="118" viewBox="0 0 220 118" role="img"
          aria-label={`${pct}% of your ${r.total} course${r.total === 1 ? "" : "s"} are confirmed`}>
          <path d="M 20 108 A 90 90 0 0 1 200 108" fill="none" stroke="var(--surface-2)" strokeWidth="18" />
          <path d="M 20 108 A 90 90 0 0 1 200 108" fill="none" stroke="var(--gold)" strokeWidth="18"
            strokeDasharray={`${share(r.confirmed + r.ready)} ${len}`} />
          <path d="M 20 108 A 90 90 0 0 1 200 108" fill="none" stroke="var(--brand)" strokeWidth="18"
            strokeDasharray={`${share(r.confirmed)} ${len}`} />
        </svg>
        <div className="readout">
          <div className="big">{pct}%</div>
          <div className="sub">{r.confirmed} of {r.total} confirmed</div>
        </div>
      </div>
      <div className="legend" style={{ marginTop: 8, justifyContent: "center" }}>
        <span className="key"><span className="swatch confirmed" /> Confirmed {r.confirmed}</span>
        <span className="key"><span className="swatch ready" /> Ready to confirm {r.ready}</span>
        <span className="key"><span className="swatch todo" /> Needs checking {r.needs_checking}</span>
      </div>
    </section>
  );
}
