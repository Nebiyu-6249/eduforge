import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type {
  AssessmentOverview,
  AssessmentRow,
  Coverage,
  EditEntry,
  EditOp,
  Strength,
  SyllabusRecord,
} from "../types";
import Field from "./Field";
import { fmtDate, fmtPct, isUnder } from "./util";

export interface TabProps {
  rec: SyllabusRecord;
  editable: boolean;
  focus: string | null;
  save: (path: string, value: unknown) => Promise<void>;
  apply: (ops: EditOp[]) => Promise<void>;
}

export interface AssessmentsTabProps extends TabProps {
  overview: AssessmentOverview | null;
  onEdit: (row: AssessmentRow) => void;
  onAdd: () => void;
}

/** Which reconciliation row an assessment in the weekly schedule belongs to. */
export function rowForSchedule(ov: AssessmentOverview | null, wi: number, ai: number): AssessmentRow | null {
  return ov?.rows.find((r) => r.schedule.some((c) => c.week_index === wi && c.item_index === ai)) ?? null;
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
const fmtDay = (iso: string | null) =>
  iso ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : null;

const cloList = (ns: number[]) => (ns.length ? `CLO ${ns.join(", ")}` : "none");

/** A few words per rule for the status column; the full message is in the
 *  flags panel, on the cell's tooltip and at the top of the edit dialog. */
const RULE_SHORT: Record<string, string> = {
  V1: "weight missing or the total is off",
  V2: "the two weights disagree",
  V3: "missing from one of the tables",
  V4: "another assessment shares this name",
  V5: "the CLO lists disagree",
  V6: "no CLO is mapped to it",
  V8: "assessed before the topic is taught",
  V9: "not on a class meeting day",
  V12: "a required value is missing",
};

/** One cell of the reconciliation table; `bad` marks a side that disagrees. */
function Cell({ bad, title, children }: { bad?: boolean; title?: string; children: React.ReactNode }) {
  return (
    <td className={bad ? "disagree" : undefined} title={bad ? title : undefined} tabIndex={bad ? 0 : undefined}>
      {children}
    </td>
  );
}

/**
 * The Assessments tab is one reconciliation table: a row per assessment with
 * what each of the three tables says about it, and an Edit button that opens
 * the dialog settling all three at once. The tables as read from the file stay
 * available below, collapsed.
 */
export function AssessmentsTab({ rec, editable, focus, save, apply, overview, onEdit, onAdd }: AssessmentsTabProps) {
  const total = rec.weights.reduce((s, w) => s + (w.weight_pct ?? 0), 0);
  const cloNums = rec.clos.map((c) => c.number);
  const toggle = (j: number, n: number) => {
    const cur = rec.clo_matrix[j].clo_numbers;
    const nextV = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n].sort((a, b) => a - b);
    return save(`/clo_matrix/${j}/clo_numbers`, nextV);
  };
  const rows = overview?.rows ?? [];

  return (
    <div className="stack">
      <div className="row wrap between">
        <p className="muted small" style={{ margin: 0, maxWidth: "60ch" }}>
          Each assessment is listed once, with what the weight table, the weekly schedule and the CLO matrix each say
          about it. Cells that disagree are marked; Edit settles all three in one dialog and one saved change.
        </p>
        {editable && <button className="primary" onClick={onAdd}>Add assessment</button>}
      </div>

      {!overview ? (
        <p className="muted">Loading the assessments…</p>
      ) : rows.length === 0 ? (
        <div className="empty">
          <p>No assessments were read from this syllabus.</p>
          {editable && <button className="primary" onClick={onAdd}>Add the first assessment</button>}
        </div>
      ) : (
        <div className="scroll-x">
          <table className="grid recon">
            <thead>
              <tr>
                <th style={{ minWidth: 118 }}>Assessment</th>
                <th style={{ width: 74 }}>Weight table</th>
                <th style={{ minWidth: 150 }}>Schedule</th>
                <th style={{ width: 78 }}>Matrix CLOs</th>
                <th style={{ width: 78 }}>Schedule CLOs</th>
                <th style={{ minWidth: 170 }}>Status</th>
                {editable && <th style={{ width: 58 }} />}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const msg = r.flags.map((f) => `${f.rule_id}: ${f.message}`).join("\n");
                const rules = new Set(r.flags.map((f) => f.rule_id));
                const weightBad = rules.has("V1") || rules.has("V2") || (rules.has("V3") && r.schedule.length === 0);
                const schedBad = rules.has("V2") || rules.has("V9") || (rules.has("V3") && !r.weight);
                const matrixBad = rules.has("V5") || (rules.has("V3") && !r.weight) || rules.has("V6");
                const hl = r.pointers.some((p) => isUnder(p, focus));
                return (
                  <tr key={r.key + (r.weight?.index ?? "m") + (r.matrix?.index ?? "s")} className={hl ? "hl" : undefined}>
                    <th scope="row">
                      {r.name}
                      {r.by_category && <div className="small muted">a category row: it covers the items below</div>}
                    </th>
                    <Cell bad={weightBad} title={msg}>
                      {r.weight ? <span className="num">{fmtPct(r.weight.weight_pct)}</span>
                        : <span className="muted">not listed</span>}
                    </Cell>
                    <Cell bad={schedBad} title={msg}>
                      {r.schedule.length === 0 ? <span className="muted">not scheduled</span> : r.schedule.map((c) => (
                        <div key={`${c.week_index}.${c.item_index}`} className="sched-cell">
                          <span className="wk">Week {c.week_no}</span>
                          <span className="num">{fmtPct(c.weight_pct)}</span>
                          <span className="muted">{fmtDay(c.due_date) ?? (c.due_week ? `week ${c.due_week}` : "no date")}</span>
                          {/* Only where V9 applies: take-home work may fall on any day. */}
                          {c.due_on_meeting_day === false && rules.has("V9") &&
                            <span className="pill warning">not a class day</span>}
                        </div>
                      ))}
                      {r.schedule.length > 1 && (
                        <div className="small muted">total {fmtPct(r.schedule_weight_total)}</div>
                      )}
                    </Cell>
                    <Cell bad={matrixBad} title={msg}>
                      {r.matrix ? cloList(r.matrix.clo_numbers) : <span className="muted">no column</span>}
                    </Cell>
                    <Cell bad={matrixBad} title={msg}>
                      {r.schedule.length ? cloList(r.schedule_clo_numbers) : <span className="muted">—</span>}
                    </Cell>
                    <td>
                      {r.flags.length === 0 ? <span className="pill locked">agrees</span> : (
                        <ul className="row-flags">
                          {r.flags.map((f) => (
                            <li key={f.id} title={f.message}>
                              <span className={`pill ${f.severity}`}>{f.rule_id}</span>{" "}
                              {RULE_SHORT[f.rule_id] ?? f.message}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    {editable && (
                      <td className="c">
                        <button onClick={() => onEdit(r)} aria-label={`Edit ${r.name}`}>Edit</button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Weight table total</th>
                <th className={Math.abs(total - 100) < 0.01 ? "ok-num" : "bad-num"}>{total}%</th>
                <th colSpan={editable ? 5 : 4} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {overview && overview.unrowed_flags.length > 0 && (
        <div className="note-box">
          <div>
            <strong>About the assessments as a whole</strong>
            <ul className="tight">
              {overview.unrowed_flags.map((f) => <li key={f.id}>{f.rule_id}: {f.message}</li>)}
            </ul>
          </div>
        </div>
      )}

      <details className="raw-tables">
        <summary>Tables as read from the file</summary>
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
              <tr><th>Total</th><th className={Math.abs(total - 100) < 0.01 ? "ok-num" : "bad-num"}>{total}%</th>{editable && <th />}</tr>
            </tbody>
          </table>
        </section>

        <section className="sect">
          <h3>CLO × assessment matrix</h3>
          {rec.clo_matrix.length === 0 ? <p className="muted">No matrix found in the file.</p> : (
            <div className="scroll-x">
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
            </div>
          )}
        </section>
      </details>
    </div>
  );
}

// --------------------------------------------------------------------------
export function WeeklyTab({ rec, editable, focus, save, overview, onEdit, onAdd }: AssessmentsTabProps) {
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
                {w.assessments.map((a, k) => {
                  const row = rowForSchedule(overview, i, k);
                  return (
                    <div key={k} className={`assess ${isUnder(`/weekly/${i}/assessments/${k}`, focus) ? "hl" : ""}`}>
                      <div className="row between">
                        <strong>{a.name}</strong>
                        {editable && row && (
                          <button className="link small" onClick={() => onEdit(row)} aria-label={`Edit ${a.name}`}>Edit</button>
                        )}
                      </div>
                      <div className="row small muted wrap">
                        <span>{fmtPct(a.weight_pct)}</span>
                        <span>{fmtDay(a.due_date) ?? (a.due_week ? `week ${a.due_week}` : "no date")}</span>
                      </div>
                      {a.due_text_raw && <div className="small muted">File says: “{a.due_text_raw}”</div>}
                    </div>
                  );
                })}
                {editable && (
                  <button className="icon" onClick={onAdd}>Add assessment…</button>
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
/** Edits saved together (one dialog, one save) read as one row that unfolds. */
function groupEdits(edits: EditEntry[]): { group: number; at: string; by: string; note: string | null; rows: EditEntry[] }[] {
  const out: { group: number; at: string; by: string; note: string | null; rows: EditEntry[] }[] = [];
  for (const e of edits) {
    const last = out[out.length - 1];
    if (last && last.group === e.group) last.rows.push(e);
    else out.push({ group: e.group, at: e.at, by: e.edited_by, note: e.note, rows: [e] });
  }
  return out.reverse();
}

function summarise(rows: EditEntry[]): string {
  if (rows.length === 1) return `${rows[0].op_label}: ${rows[0].label}`;
  const subjects = [...new Set(rows.map((r) => r.label.split(" - ")[0]))];
  const head = subjects.slice(0, 2).join(", ") + (subjects.length > 2 ? ` and ${subjects.length - 2} more` : "");
  return `${rows.length} changes to ${head}`;
}

export function EditLogTab({ edits, onExport }: { edits: EditEntry[] | null; onExport: () => void }) {
  const [open, setOpen] = useState<number[]>([]);
  const groups = useMemo(() => groupEdits(edits ?? []), [edits]);
  if (!edits) return <p className="muted">Loading…</p>;
  if (edits.length === 0)
    return (
      <div className="empty">
        <p>No edits yet.</p>
        <p className="muted">Every change you make to the extracted record is recorded here, against the file you
          uploaded. It is the audit trail, so nothing is deleted from it.</p>
      </div>
    );
  return (
    <div className="stack">
      <div className="row between wrap">
        <p className="muted small" style={{ margin: 0 }}>
          {edits.length} change{edits.length === 1 ? "" : "s"} in {groups.length} save{groups.length === 1 ? "" : "s"},
          newest first. Changes saved together are shown as one save.
        </p>
        <button onClick={onExport}>Download CSV</button>
      </div>
      <div className="scroll-x">
        <table className="grid log">
          <thead>
            <tr>
              <th style={{ width: 140 }}>When</th>
              <th style={{ width: 110 }}>Who</th>
              <th style={{ width: 86 }}>Change</th>
              <th style={{ minWidth: 200 }}>What changed</th>
              <th style={{ width: 170 }}>Was</th>
              <th style={{ width: 170 }}>Now</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const multi = g.rows.length > 1;
              const expanded = open.includes(g.group);
              const first = g.rows[0];
              return (
                <Fragment key={g.group}>
                  <tr className={multi ? "save-head" : undefined}>
                    <td className="small">{fmtDate(g.at)}</td>
                    <td>{g.by}</td>
                    <td>{multi ? <span className="chip">{g.rows.length} changes</span> : first.op_label}</td>
                    <td>
                      {multi ? (
                        <button className="link" aria-expanded={expanded}
                          onClick={() => setOpen((p) => (expanded ? p.filter((x) => x !== g.group) : [...p, g.group]))}>
                          {summarise(g.rows)}
                        </button>
                      ) : first.label}
                      {g.note && <div className="small muted">Note: {g.note}</div>}
                    </td>
                    <td className="small wrapcell">{multi ? "" : first.old_text}</td>
                    <td className="small wrapcell">{multi ? "" : first.new_text}</td>
                  </tr>
                  {multi && expanded && g.rows.map((e) => (
                    <tr key={e.id} className="save-row">
                      <td />
                      <td />
                      <td className="small">{e.op_label}</td>
                      <td className="small">{e.label}</td>
                      <td className="small wrapcell">{e.old_text}</td>
                      <td className="small wrapcell">{e.new_text}</td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
