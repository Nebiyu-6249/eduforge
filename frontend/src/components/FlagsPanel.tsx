import { useState } from "react";
import type { Flag } from "../types";
import { fmtDate, ptrLabel } from "./util";

interface Props {
  flags: Flag[];
  editable: boolean;
  onResolve: (flag: Flag, action: "accept" | "reopen", note?: string) => Promise<void>;
  onChoose: (flag: Flag, choice: number) => Promise<void>;
  onJump: (ptr: string) => void;
  /** True when the flag's evidence points at an assessment the dialog can settle. */
  fixable: (flag: Flag) => boolean;
  /** Opens the assessment dialog on that assessment. */
  onFix: (flag: Flag) => void;
}

type Filter = "open" | "settled" | "all";

export default function FlagsPanel({ flags, editable, onResolve, onChoose, onJump, fixable, onFix }: Props) {
  const [filter, setFilter] = useState<Filter>("open");
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const open = flags.filter((f) => f.status === "open");
  const shown = flags.filter((f) =>
    filter === "all" ? true : filter === "open" ? f.status === "open" : f.status !== "open",
  );
  const blocking = open.filter((f) => f.severity !== "info").length;

  async function accept(f: Flag) {
    setErr(null);
    try {
      await onResolve(f, "accept", note);
      setNoteFor(null);
      setNote("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <aside className="flags card">
      <div className="head">
        <h2>Validator flags</h2>
        <span className={`pill ${blocking ? "warning" : "locked"}`}>{blocking ? `${blocking} to settle` : "All settled"}</span>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        Flags are never fixed automatically. Correct the field (the flag clears itself) or accept it as is with a reason.
      </p>
      <div className="filter">
        {(["open", "settled", "all"] as Filter[]).map((k) => (
          <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
            {k === "open" ? `Open (${open.length})` : k === "settled" ? `Settled (${flags.length - open.length})` : "All"}
          </button>
        ))}
      </div>
      {shown.length === 0 && <p className="muted">{filter === "open" ? "Nothing open." : "None."}</p>}
      {shown.map((f) => (
        <div key={f.id} className={`flag ${f.severity} ${f.status !== "open" ? "done" : ""}`}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="rule">
              <strong>{f.rule_id}</strong> · {f.rule_title}
            </span>
            <span className={`pill ${f.status === "open" ? f.severity : "locked"}`}>
              {f.status === "open" ? f.severity : f.status === "cleared" ? "cleared" : "accepted"}
            </span>
          </div>
          <div className="msg">{f.message}</div>
          {editable && f.status === "open" && fixable(f) && (
            <div className="row" style={{ marginTop: 6 }}>
              <button className="primary" onClick={() => onFix(f)}>Fix this assessment</button>
            </div>
          )}
          {f.evidence_refs.length > 0 && (
            <div className="ev">
              {f.evidence_refs.slice(0, 4).map((p) => (
                <button key={p} onClick={() => onJump(p)}>Go to {ptrLabel(p)}</button>
              ))}
            </div>
          )}
          {f.status !== "open" && (
            <div className="res">
              {f.status === "cleared" ? "Cleared by an edit" : "Accepted as is"}
              {f.resolution_note && f.status !== "cleared" ? `: “${f.resolution_note}”` : ""}
              {f.resolved_by && ` — ${f.resolved_by}, ${fmtDate(f.resolved_at)}`}
            </div>
          )}
          {editable && f.status === "open" && f.choices.length > 0 && (
            <div className="choices">
              <span className="small muted">Choose a value:</span>
              {f.choices.map((c, i) => (
                <button key={i} className="icon" onClick={() => onChoose(f, i).catch((e) => setErr(e.message))}>
                  {c.label}
                </button>
              ))}
            </div>
          )}
          {editable && f.status === "open" && f.severity !== "info" && (
            noteFor === f.id ? (
              <div className="stack" style={{ marginTop: 8 }}>
                <textarea
                  placeholder="Why is this acceptable as is? (optional, kept on the flag)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  autoFocus
                />
                {err && <div className="error-box small">{err}</div>}
                <div className="row">
                  <button className="primary" onClick={() => accept(f)}>
                    Accept as is
                  </button>
                  <button onClick={() => setNoteFor(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <div className="row" style={{ marginTop: 6 }}>
                <button className="icon" onClick={() => { setNoteFor(f.id); setNote(""); setErr(null); }}>
                  Accept as is…
                </button>
              </div>
            )
          )}
          {editable && f.status === "resolved" && (
            <div className="row" style={{ marginTop: 6 }}>
              <button className="icon" onClick={() => onResolve(f, "reopen")}>Reopen</button>
            </div>
          )}
        </div>
      ))}
    </aside>
  );
}
