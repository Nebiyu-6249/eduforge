import { useEffect, useRef } from "react";
import type { Coverage, EditEntry, EditOp, Strength, SyllabusRecord } from "../types";
import Field from "./Field";
import { fmtDate, fmtPct, isUnder } from "./util";

export interface TabProps {
  rec: SyllabusRecord;
  editable: boolean;
  focus: string | null;
  save: (path: string, value: unknown) => Promise<void>;
  apply: (ops: EditOp[]) => Promise<void>;
}

function Hl({ path, focus, children, as = "div" }: { path: string; focus: string | null; children: React.ReactNode; as?: "div" | "tr" }) {
  const ref = useRef<HTMLDivElement & HTMLTableRowElement>(null);
  const hl = isUnder(path, focus);
  useEffect(() => {
    if (hl) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [hl]);
  const Tag = as;
  return (
    <Tag ref={ref} className={hl ? "hl" : undefined} data-path={path}>
      {children}
    </Tag>
  );
}

// --------------------------------------------------------------------------
export function CourseTab({ rec, editable, focus, save }: TabProps) {
  const f = (path: string, label: string, value: unknown, kind: "text" | "textarea" | "number" | "lines" = "text", full = false) => (
    <Field key={path} path={path} label={label} value={value} kind={kind} editable={editable} focus={focus} onSave={save}
      className={full ? "full" : undefined} />
  );
  const c = rec.course, o = rec.offering;
  return (
    <div className="stack">
      <div className="fields">
        {f("/course/code", "Course code", c.code)}
        {f("/course/title", "Course title", c.title)}
        {f("/course/credit_hours", "Credit hours", c.credit_hours, "number")}
        {f("/course/prerequisites", "Prerequisite course(s)", c.prerequisites)}
        {f("/offering/term_raw", "Semester and academic year (as in file)", o.term_raw)}
        <Field path="/offering/term" label="Term (normalised)" value={o.term} editable={false} focus={focus} onSave={save}
          placeholder="Couldn't read a term — edit the field to the left" />
        {f("/offering/class_timing_raw", "Class timing(s)", o.class_timing_raw)}
        <Field path="/offering/meetings" label="Meeting days (derived)" value={o.meetings} editable={false} focus={focus} onSave={save}
          display={(v) => (v as typeof o.meetings).map((m, i) => (
            <span key={i} className="chip">{m.days.map((d) => d[0].toUpperCase() + d.slice(1)).join("/") || "?"} {m.time_text}</span>
          ))} />
        {f("/offering/instructor_name", "Faculty name", o.instructor_name)}
        {f("/offering/instructor_contact", "Contact and office hours", o.instructor_contact)}
        {f("/course/methods_of_instruction", "Method(s) of instruction", c.methods_of_instruction, "text", true)}
        {f("/course/description", "Course description", c.description, "textarea", true)}
        {f("/course/additional_info", "Additional information", c.additional_info, "textarea", true)}
        {f("/resources/textbooks", "Textbooks and materials", rec.resources.textbooks, "lines", true)}
        {f("/resources/other", "Other resources", rec.resources.other, "lines", true)}
        {f("/resources/web", "Web resources", rec.resources.web, "lines", true)}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
export function ClosTab({ rec, editable, focus, save, apply }: TabProps) {
  const next = Math.max(0, ...rec.clos.map((c) => c.number)) + 1;
  return (
    <div className="stack">
      <table className="grid">
        <thead><tr><th style={{ width: 70 }}>CLO</th><th>Outcome</th>{editable && <th style={{ width: 70 }} />}</tr></thead>
        <tbody>
          {rec.clos.map((c, i) => (
            <Hl as="tr" key={i} path={`/clos/${i}`} focus={focus}>
              <td><Field path={`/clos/${i}/number`} value={c.number} kind="number" editable={editable} focus={null} onSave={save} /></td>
              <td><Field path={`/clos/${i}/text`} value={c.text} kind="textarea" editable={editable} focus={null} onSave={save} /></td>
              {editable && <td className="c"><button className="icon danger" onClick={() => apply([{ op: "remove", path: `/clos/${i}` }])}>Remove</button></td>}
            </Hl>
          ))}
        </tbody>
      </table>
      {editable && (
        <button onClick={() => apply([{ op: "add", path: "/clos/-", value: { number: next, text: "New outcome — edit me" } }])}>
          Add CLO {next}
        </button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
export function AssessmentsTab({ rec, editable, focus, save, apply }: TabProps) {
  const total = rec.weights.reduce((s, w) => s + (w.weight_pct ?? 0), 0);
  const cloNums = rec.clos.map((c) => c.number);
  const toggle = (j: number, n: number) => {
    const cur = rec.clo_matrix[j].clo_numbers;
    const nextV = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n].sort((a, b) => a - b);
    return save(`/clo_matrix/${j}/clo_numbers`, nextV);
  };
  return (
    <div>
      <section className="sect">
        <h3>Weight table</h3>
        <table className="grid">
          <thead><tr><th>Assessment</th><th style={{ width: 120 }}>Weight</th>{editable && <th style={{ width: 70 }} />}</tr></thead>
          <tbody>
            {rec.weights.map((w, i) => (
              <Hl as="tr" key={i} path={`/weights/${i}`} focus={focus}>
                <td><Field path={`/weights/${i}/name`} value={w.name} editable={editable} focus={null} onSave={save} /></td>
                <td><Field path={`/weights/${i}/weight_pct`} value={w.weight_pct} kind="number" editable={editable} focus={null} onSave={save}
                  display={(v) => fmtPct(v as number)} /></td>
                {editable && <td className="c"><button className="icon danger" onClick={() => apply([{ op: "remove", path: `/weights/${i}` }])}>Remove</button></td>}
              </Hl>
            ))}
            <tr><th>Total</th><th style={{ color: Math.abs(total - 100) < 0.01 ? "var(--ok)" : "var(--error)" }}>{total}%</th>{editable && <th />}</tr>
          </tbody>
        </table>
        {editable && (
          <button style={{ marginTop: 8 }} onClick={() => apply([{ op: "add", path: "/weights/-", value: { name: "New assessment", weight_pct: 0 } }])}>
            Add weight row
          </button>
        )}
      </section>

      <section className="sect">
        <h3>CLO × assessment matrix</h3>
        {rec.clo_matrix.length === 0 ? <p className="muted">No matrix found in the file.</p> : (
          <table className="grid">
            <thead>
              <tr><th>CLO</th>{rec.clo_matrix.map((m, j) => (
                <th key={j} className={`c ${isUnder(`/clo_matrix/${j}`, focus) ? "hl" : ""}`}>{m.assessment}</th>
              ))}</tr>
            </thead>
            <tbody>
              {cloNums.map((n) => (
                <tr key={n}>
                  <th>CLO {n}</th>
                  {rec.clo_matrix.map((m, j) => (
                    <td key={j} className={`c ${isUnder(`/clo_matrix/${j}`, focus) ? "hl" : ""}`}>
                      <input type="checkbox" checked={m.clo_numbers.includes(n)} disabled={!editable} onChange={() => toggle(j, n)}
                        aria-label={`CLO ${n} assessed by ${m.assessment}`} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------
export function WeeklyTab({ rec, editable, focus, save, apply }: TabProps) {
  return (
    <div className="stack">
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 52 }}>Week</th><th>Topics</th><th style={{ width: 130 }}>Readings</th>
            <th style={{ width: "34%" }}>Assessments (weight · due)</th><th style={{ width: 100 }}>CLOs</th>
          </tr>
        </thead>
        <tbody>
          {rec.weekly.map((w, i) => (
            <Hl as="tr" key={i} path={`/weekly/${i}`} focus={focus}>
              <td><Field path={`/weekly/${i}/week_no`} value={w.week_no} kind="number" editable={editable} focus={null} onSave={save} /></td>
              <td><Field path={`/weekly/${i}/topics`} value={w.topics} kind="lines" editable={editable} focus={null} onSave={save} placeholder="—" /></td>
              <td><Field path={`/weekly/${i}/readings`} value={w.readings} kind="lines" editable={editable} focus={null} onSave={save} placeholder="—" /></td>
              <td>
                {w.assessments.map((a, k) => (
                  <div key={k} className={`assess ${isUnder(`/weekly/${i}/assessments/${k}`, focus) ? "hl" : ""}`}>
                    <Field path={`/weekly/${i}/assessments/${k}/name`} value={a.name} editable={editable} focus={null} onSave={save} />
                    <div className="row small">
                      <Field path={`/weekly/${i}/assessments/${k}/weight_pct`} value={a.weight_pct} kind="number" editable={editable}
                        focus={null} onSave={save} display={(v) => fmtPct(v as number)} placeholder="no weight" />
                      <Field path={`/weekly/${i}/assessments/${k}/due_date`} value={a.due_date} kind="date" editable={editable}
                        focus={null} onSave={save} placeholder={a.due_week ? `week ${a.due_week}` : "no date"} />
                    </div>
                    {a.due_text_raw && <div className="small muted">File says: “{a.due_text_raw}”</div>}
                    {editable && (
                      <button className="icon danger" onClick={() => apply([{ op: "remove", path: `/weekly/${i}/assessments/${k}` }])}>Remove</button>
                    )}
                  </div>
                ))}
                {editable && (
                  <button className="icon" onClick={() => apply([{ op: "add", path: `/weekly/${i}/assessments/-`,
                    value: { name: "New assessment", weight_pct: null, due_text_raw: null, due_date: null, due_week: null } }])}>
                    + assessment
                  </button>
                )}
              </td>
              <td>
                <Field path={`/weekly/${i}/clo_numbers`} value={w.clo_numbers} kind="nums" editable={editable} focus={null} onSave={save}
                  placeholder="none" display={(v) => (v as number[]).map((n) => <span key={n} className="chip">CLO {n}</span>)} />
              </td>
            </Hl>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------
const STRENGTHS: (Strength | "")[] = ["", "high", "medium", "low"];

export function ProgramsTab({ rec, editable, focus, save }: TabProps) {
  if (rec.programs.length === 0) return <p className="muted">No appendix programs were found in the file.</p>;
  return (
    <div>
      {rec.programs.map((p, pi) => {
        const base = `/programs/${pi}`;
        const strengthOf = (clo: number, plo: number) => p.clo_plo.find((l) => l.clo === clo && l.plo === plo)?.strength ?? "";
        const setStrength = (clo: number, plo: number, s: Strength | "") => {
          const rest = p.clo_plo.filter((l) => !(l.clo === clo && l.plo === plo));
          const next = s ? [...rest, { clo, plo, strength: s }] : rest;
          next.sort((a, b) => a.clo - b.clo || a.plo - b.plo);
          return save(`${base}/clo_plo`, next);
        };
        const toggleAddressed = (n: number) => {
          const cur = p.abet_addressed;
          return save(`${base}/abet_addressed`, cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n].sort((a, b) => a - b));
        };
        return (
          <Hl key={pi} path={base} focus={focus}>
            <section className="sect">
              <h3><Field path={`${base}/name`} value={p.name} editable={editable} focus={null} onSave={save} /></h3>
              <table className="grid">
                <thead><tr><th style={{ width: 60 }}>PLO</th><th>Outcome</th></tr></thead>
                <tbody>
                  {p.plos.map((x, k) => (
                    <tr key={k}>
                      <td>{x.number}</td>
                      <td><Field path={`${base}/plos/${k}/text`} value={x.text} kind="textarea" editable={editable} focus={null} onSave={save} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3 style={{ margin: "14px 0 6px" }}>CLO → PLO mapping</h3>
              <table className={`grid ${isUnder(`${base}/clo_plo`, focus) ? "hl" : ""}`}>
                <thead>
                  <tr><th>CLO</th>{p.plos.map((x) => <th key={x.number} className="c">PLO {x.number}</th>)}</tr>
                </thead>
                <tbody>
                  {rec.clos.map((c) => (
                    <tr key={c.number}>
                      <th>CLO {c.number}</th>
                      {p.plos.map((x) => (
                        <td key={x.number} className="c">
                          {editable ? (
                            <select value={strengthOf(c.number, x.number)} onChange={(e) => setStrength(c.number, x.number, e.target.value as Strength | "")}
                              aria-label={`CLO ${c.number} to PLO ${x.number}`}>
                              {STRENGTHS.map((s) => <option key={s} value={s}>{s ? s[0].toUpperCase() : "—"}</option>)}
                            </select>
                          ) : (strengthOf(c.number, x.number)[0]?.toUpperCase() ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr className={isUnder(`${base}/abet_addressed`, focus) ? "hl" : undefined}>
                    <th>Addressed</th>
                    {p.plos.map((x) => (
                      <td key={x.number} className="c">
                        <input type="checkbox" checked={p.abet_addressed.includes(x.number)} disabled={!editable}
                          onChange={() => toggleAddressed(x.number)} aria-label={`Outcome ${x.number} addressed`} />
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </section>
          </Hl>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------
export function CoverageTab({ cov }: { cov: Coverage | null }) {
  if (!cov) return <p className="muted">Loading…</p>;
  return (
    <div>
      <section className="sect">
        <h3>Grade weight per CLO</h3>
        <table className="grid">
          <thead><tr><th style={{ width: 60 }}>CLO</th><th>Outcome</th><th style={{ width: 90 }}>Weight</th><th>Assessed by</th></tr></thead>
          <tbody>
            {cov.clos.map((c) => (
              <tr key={c.number}>
                <td>{c.number}</td><td>{c.text}</td>
                <td style={{ color: c.weight_pct ? undefined : "var(--error)" }}>{c.weight_pct}%</td>
                <td>{c.assessments.map((a) => <span key={a} className="chip">{a}</span>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">{cov.weight_note}</p>
      </section>
      {cov.programs.map((p) => (
        <section className="sect" key={p.name}>
          <h3>{p.name}</h3>
          <table className="grid">
            <thead><tr><th style={{ width: 60 }}>PLO</th><th>Outcome</th><th className="c" style={{ width: 110 }}>Mapped CLOs</th><th className="c" style={{ width: 90 }}>Addressed</th></tr></thead>
            <tbody>
              {p.plos.map((x) => {
                const clos = Object.entries(p.grid).filter(([, row]) => row[String(x.number)]).map(([c, row]) => `${c}${row[String(x.number)][0].toUpperCase()}`);
                return (
                  <tr key={x.number}>
                    <td>{x.number}</td><td>{x.text}</td>
                    <td className="c">{clos.length ? clos.join(", ") : <span className="muted">none</span>}</td>
                    <td className="c">{x.addressed ? "✓" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {p.uncovered_plos.length > 0 && <p className="small muted">Not covered by this course: PLO {p.uncovered_plos.join(", ")}.</p>}
        </section>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
export function SourceTab({ rec, focus }: { rec: SyllabusRecord; focus: string | null }) {
  const esc = (s: string) => s.replace(/~/g, "~0").replace(/\//g, "~1");
  return (
    <div>
      {rec.notes.length > 0 && (
        <section className="sect">
          <h3>Extraction notes</h3>
          {rec.notes.map((n, i) => (
            <Hl key={i} path={`/notes/${i}`} focus={focus}>
              <p><strong>{n.where}:</strong> {n.message}</p>
            </Hl>
          ))}
        </section>
      )}
      <section className="sect">
        <h3>Section text as read from the file</h3>
        <p className="small muted">Read-only. Used to check for leftover template text (V10).</p>
        {Object.entries(rec.raw_sections).map(([h, t]) => (
          <Hl key={h} path={`/raw_sections/${esc(h)}`} focus={focus}>
            <details open={isUnder(`/raw_sections/${esc(h)}`, focus)} style={{ marginBottom: 8 }}>
              <summary><strong>{h}</strong></summary>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--mono)", fontSize: 12, background: "#fbfaf7", padding: 10, borderRadius: 6 }}>{t}</pre>
            </details>
          </Hl>
        ))}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------
const show = (v: unknown) => (v === null || v === undefined ? "∅" : typeof v === "string" ? v : JSON.stringify(v));

export function EditLogTab({ edits, onExport }: { edits: EditEntry[] | null; onExport: () => void }) {
  if (!edits) return <p className="muted">Loading…</p>;
  if (edits.length === 0) return <p className="muted">No edits yet. Every change you make is logged here against the uploaded file.</p>;
  return (
    <>
    <div className="row" style={{ justifyContent: "flex-end", marginBottom: 8 }}>
      <button onClick={onExport}>Download CSV</button>
    </div>
    <table className="grid">
      <thead><tr><th style={{ width: 150 }}>When</th><th style={{ width: 110 }}>Who</th><th>Field</th><th>Was</th><th>Now</th><th>Note</th></tr></thead>
      <tbody>
        {[...edits].reverse().map((e) => (
          <tr key={e.id}>
            <td className="small">{fmtDate(e.at)}</td>
            <td>{e.edited_by}</td>
            <td className="code small">{e.op !== "replace" && <span className="chip">{e.op}</span>}{e.field_path}</td>
            <td className="small" style={{ maxWidth: 220, overflowWrap: "anywhere" }}>{show(e.old_value)}</td>
            <td className="small" style={{ maxWidth: 220, overflowWrap: "anywhere" }}>{show(e.new_value)}</td>
            <td className="small">{e.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </>
  );
}
