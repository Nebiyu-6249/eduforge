import type { DraftItem } from "../types";
import MathText, { FigureView } from "./MathText";

/** Read-only rendering of a draft, laid out like the export. */
export default function ItemView({ item, showKey }: { item: DraftItem; showKey: boolean }) {
  const b = item.body;
  const k = item.answer_key ?? {};
  const f = item.feedback;
  return (
    <div className="item-view">
      {item.type === "mcq" && (
        <>
          <p className="stem"><MathText text={b.stem} /></p>
          <ul className="opts">
            {b.options.map((o: any) => (
              <li key={o.label} className={showKey && o.label === k.correct ? "correct" : ""}>
                <strong>{o.label}.</strong> <MathText text={o.text} />
                {showKey && k.why_others_wrong?.[o.label] && <div className="small muted">{k.why_others_wrong[o.label]}</div>}
                {showKey && o.label === k.correct && <div className="small">✓ <MathText text={k.why_correct} /></div>}
              </li>
            ))}
          </ul>
        </>
      )}
      {item.type === "short_answer" && (
        <>
          <p className="stem"><MathText text={b.question} /></p>
          <p className="small muted">Expected length: {b.expected_length}</p>
          {showKey && (
            <div className="key">
              <p><MathText text={k.model_answer} /></p>
              <ul>{k.key_points?.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
        </>
      )}
      {item.type === "problem" && (
        <>
          <p className="stem"><MathText text={b.statement} /></p>
          {b.given?.length > 0 && (
            <ul>{b.given.map((g: any) => <li key={g.name}><code>{g.name}</code> = {g.value} {g.unit} {g.description && <span className="muted">— {g.description}</span>}</li>)}</ul>
          )}
          <p><strong>Find:</strong> <MathText text={b.asks_for} /></p>
          {showKey && (
            <div className="key">
              <ol>{k.solution_steps?.map((s: string, i: number) => <li key={i}><MathText text={s} /></li>)}</ol>
              <p><strong>Answer:</strong> <MathText text={k.final_answer_text} /></p>
              {k.answer_expression && <p className="small muted">Check expression: <code>{k.answer_expression}</code> = {k.numeric_answer}</p>}
            </div>
          )}
        </>
      )}
      {item.type === "practice_set" && (
        <>
          <h3>{b.title}</h3>
          <p>{b.instructions}</p>
          <ol>
            {b.exercises.map((e: any, i: number) => (
              <li key={i}>
                <MathText text={e.prompt} />
                {showKey && <div className="key small">Answer: {e.answer}{e.hint && ` · Hint: ${e.hint}`}</div>}
              </li>
            ))}
          </ol>
        </>
      )}
      {item.type === "lesson_plan" && (
        <>
          <h3>{b.title} <span className="muted small">({b.session_minutes} min)</span></h3>
          <p><strong>Objectives</strong></p>
          <ul>{b.objectives.map((o: string, i: number) => <li key={i}>{o}</li>)}</ul>
          {b.prior_knowledge && <p><strong>Prior knowledge:</strong> {b.prior_knowledge}</p>}
          <table className="grid">
            <thead><tr><th>Activity</th><th style={{ width: 50 }}>Min</th><th>Description</th><th style={{ width: 70 }}>CLO</th></tr></thead>
            <tbody>{b.activities.map((a: any, i: number) => (
              <tr key={i}><td>{a.name}</td><td>{a.minutes}</td><td>{a.description}</td><td>{a.clo_numbers?.join(", ")}</td></tr>
            ))}</tbody>
          </table>
          {b.materials?.length > 0 && <p><strong>Materials:</strong> {b.materials.join("; ")}</p>}
          <p><strong>Check for understanding:</strong> {b.check_for_understanding}</p>
          {b.after_class && <p><strong>After class:</strong> {b.after_class}</p>}
        </>
      )}
      {item.type === "case_study" && (
        <>
          <h3>{b.title}</h3>
          <p style={{ whiteSpace: "pre-wrap" }}><MathText text={b.scenario} /></p>
          <ol>{b.questions.map((q: any, i: number) => (
            <li key={i}>{q.question}{showKey && <div className="key small">{q.model_answer}</div>}</li>
          ))}</ol>
          {showKey && k.teaching_notes && <div className="key"><strong>Teaching notes:</strong> {k.teaching_notes}</div>}
        </>
      )}
      {item.type === "learning_resource" && (
        <>
          <h3>{b.title} <span className="chip">{b.kind}</span></h3>
          <div style={{ whiteSpace: "pre-wrap" }}><MathText text={b.content} /></div>
          {b.further_reading?.length > 0 && <><p><strong>Further reading</strong></p><ul>{b.further_reading.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></>}
        </>
      )}
      {item.type === "rubric" && (
        <>
          <h3>{b.title}</h3>
          <p><strong>Task:</strong> {b.task}</p>
          {b.criteria.map((c: any, i: number) => (
            <table className="grid" key={i} style={{ marginBottom: 8 }}>
              <thead><tr><th>{c.criterion} {c.clo_numbers?.length > 0 && <span className="muted">· CLO {c.clo_numbers.join(", ")}</span>}</th>
                {[...c.levels].sort((x: any, y: any) => y.points - x.points).map((lv: any) => <th key={lv.label}>{lv.label} ({lv.points})</th>)}</tr></thead>
              <tbody><tr><td />{[...c.levels].sort((x: any, y: any) => y.points - x.points).map((lv: any) => <td key={lv.label}>{lv.descriptor}</td>)}</tr></tbody>
            </table>
          ))}
        </>
      )}
      {item.type === "code_exercise" && (
        <>
          <p className="stem"><MathText text={b.prompt} /></p>
          <div className="small muted">Starter code</div>
          <pre className="code-block">{b.starter_code}</pre>
          {showKey && (
            <div className="key">
              <div className="small muted">Reference solution</div>
              <pre className="code-block">{k.solution_code}</pre>
              <div className="small muted">Hidden tests</div>
              <pre className="code-block">{k.tests_code}</pre>
              {k.explanation && <p><MathText text={k.explanation} /></p>}
            </div>
          )}
        </>
      )}
      {b.figure && <FigureView itemId={item.id} figure={b.figure} />}
      {showKey && f && (
        <div className="small muted" style={{ marginTop: 8 }}>
          <strong>Feedback prompts</strong> — Hint: {f.hint} · Explanation: {f.explanation}
        </div>
      )}
    </div>
  );
}
