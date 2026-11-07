import { useState } from "react";
import Modal from "./Modal";
import { fmtDate } from "./util";
import type { Flag } from "../types";

/* "Things to check" — what the validator found, written for a teacher.
   One card per problem: a plain title, the plain sentence, how serious it is
   in words, one filled "Fix" button and one quiet "Keep as it is" link. The
   rule id, the technical message and the JSON pointers live under "Details"
   for the team. */

interface Props {
  flags: Flag[];
  editable: boolean;
  /** Settle a thing to check as acceptable, or reopen it. */
  onKeep: (flag: Flag, note?: string) => Promise<void>;
  /** Apply one of the prepared fixes (index into flag.choices). */
  onChoose: (flag: Flag, choice: number) => Promise<void>;
  /** True when the assessment dialog can settle this one instead. */
  fixable: (flag: Flag) => boolean;
  /** Open the assessment dialog for this flag. */
  onFix: (flag: Flag) => void;
  /** Highlight the place in the syllabus the flag points at. */
  onShowInSyllabus: (ptr: string) => void;
}

export default function ThingsToCheck({ flags, editable, onKeep, onChoose, fixable, onFix, onShowInSyllabus }: Props) {
  const [dialogFor, setDialogFor] = useState<Flag | null>(null);
  const [keepFor, setKeepFor] = useState<Flag | null>(null);

  const open = flags.filter((f) => f.status === "open");
  const mustFix = open.filter((f) => f.severity === "error");
  const worthLook = open.filter((f) => f.severity === "warning");
  const notes = open.filter((f) => f.severity === "info");
  const settled = flags.filter((f) => f.status !== "open");
  const blocking = mustFix.length + worthLook.length;
  const total = flags.filter((f) => f.severity !== "info").length;
  const done = total - blocking;
  const pct = total ? Math.round((done / total) * 100) : 100;

  return (
    <section className="card" aria-labelledby="ttc-title">
      <div className="checks-head">
        <div className="row between wrap">
          <h2 id="ttc-title">Things to check</h2>
          <span className="small muted">{done} of {total} done</span>
        </div>
        <div className="progress" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
        <p className="small muted" style={{ margin: 0 }}>
          {blocking === 0
            ? "Nothing left. You can confirm this syllabus for the term."
            : "EduForge never changes your syllabus on its own. Fix each one, or keep it as it is and say why."}
        </p>
      </div>

      {blocking === 0 && settled.length === 0 && (
        <p className="muted">Nothing to check in this syllabus.</p>
      )}

      <Group title="Must fix before confirming" flags={mustFix} kind="must" {...{ editable, fixable, onFix, setDialogFor, setKeepFor, onShowInSyllabus }} />
      <Group title="Worth a look" flags={worthLook} kind="worth" {...{ editable, fixable, onFix, setDialogFor, setKeepFor, onShowInSyllabus }} />

      {notes.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary className="small muted">Notes from reading the file ({notes.length})</summary>
          <div style={{ marginTop: 12 }}>
            <Group title="" flags={notes} kind="worth" {...{ editable, fixable, onFix, setDialogFor, setKeepFor, onShowInSyllabus }} />
          </div>
        </details>
      )}

      {settled.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary className="small muted">Already settled ({settled.length})</summary>
          <div style={{ marginTop: 12 }}>
            {settled.map((f) => (
              <div key={f.id} className="check settled">
                <h3>{f.plain_title}</h3>
                <p className="what small">{f.plain_message}</p>
                <p className="settled-note">
                  {f.status === "cleared" ? "Fixed by an edit you made." : "Kept as it is."}
                  {f.resolution_note && f.status !== "cleared" ? ` “${f.resolution_note}”` : ""}
                  {f.resolved_by ? ` — ${f.resolved_by}, ${fmtDate(f.resolved_at)}` : ""}
                </p>
                {editable && f.status === "resolved" && (
                  <button className="link" onClick={() => onKeep(f, undefined)}>Look at it again</button>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {dialogFor && (
        <FixDialog
          flag={dialogFor}
          onClose={() => setDialogFor(null)}
          onChoose={(i) => onChoose(dialogFor, i)}
          onShowInSyllabus={onShowInSyllabus}
        />
      )}
      {keepFor && (
        <KeepDialog flag={keepFor} onClose={() => setKeepFor(null)} onKeep={(note) => onKeep(keepFor, note)} />
      )}
    </section>
  );
}

// --------------------------------------------------------------------------
function Group({ title, flags, kind, editable, fixable, onFix, setDialogFor, setKeepFor, onShowInSyllabus }: {
  title: string; flags: Flag[]; kind: "must" | "worth"; editable: boolean;
  fixable: (f: Flag) => boolean; onFix: (f: Flag) => void;
  setDialogFor: (f: Flag) => void; setKeepFor: (f: Flag) => void;
  onShowInSyllabus: (ptr: string) => void;
}) {
  if (flags.length === 0) return null;
  return (
    <div style={{ marginTop: title ? 20 : 0 }}>
      {title && <h3 style={{ marginBottom: 8 }}>{title} ({flags.length})</h3>}
      {flags.map((f) => (
        <article key={f.id} className={`check ${kind}`}>
          <h3>{f.plain_title}</h3>
          <p className="what">{f.plain_message}</p>
          <p className="sev">{f.plain_severity}</p>
          {editable && (
            <div className="actions">
              {fixable(f) ? (
                <button className="primary" onClick={() => onFix(f)}>Fix</button>
              ) : f.choices.length > 0 ? (
                <button className="primary" onClick={() => setDialogFor(f)}>Fix</button>
              ) : (
                <button className="primary" onClick={() => onShowInSyllabus(f.evidence_refs[0] ?? "")}>
                  Fix in the syllabus
                </button>
              )}
              <button className="link" onClick={() => setKeepFor(f)}>Keep as it is</button>
            </div>
          )}
          <details>
            <summary>Details for the team</summary>
            <div className="tech">
              Rule {f.rule_id} · {f.rule_title}
              <br />
              {f.message}
              {f.evidence_refs.length > 0 && <><br />{f.evidence_refs.join("  ")}</>}
            </div>
          </details>
        </article>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
/** Prepared fixes as large radio cards, nothing preselected, plus "Set it myself". */
function FixDialog({ flag, onClose, onChoose, onShowInSyllabus }: {
  flag: Flag; onClose: () => void; onChoose: (i: number) => Promise<void>;
  onShowInSyllabus: (ptr: string) => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const manual = flag.choices.length; // the index after the last prepared fix

  async function save() {
    if (picked === null) {
      setErr("Choose one of the options above.");
      return;
    }
    if (picked === manual) {
      onClose();
      onShowInSyllabus(flag.evidence_refs[0] ?? "");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onChoose(picked);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={flag.plain_title}
      description={flag.plain_message}
      onClose={onClose}
      width={620}
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
      <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
        <legend className="lbl">How would you like to fix it?</legend>
        {flag.choices.map((c, i) => (
          <label key={i} className={`choice ${picked === i ? "on" : ""}`}>
            <input type="radio" name="fix" checked={picked === i} onChange={() => { setPicked(i); setErr(null); }} />
            <span className="text"><b>{c.label}</b></span>
          </label>
        ))}
        <label className={`choice ${picked === manual ? "on" : ""}`}>
          <input type="radio" name="fix" checked={picked === manual} onChange={() => { setPicked(manual); setErr(null); }} />
          <span className="text">
            <b>Set it myself</b>
            <span>Opens the place in the syllabus so you can type the value you want.</span>
          </span>
        </label>
      </fieldset>
      {flag.evidence_refs.length > 0 && (
        <p style={{ marginTop: 16 }}>
          <button type="button" className="link" onClick={() => { onClose(); onShowInSyllabus(flag.evidence_refs[0]); }}>
            Show in syllabus
          </button>
        </p>
      )}
    </Modal>
  );
}

// --------------------------------------------------------------------------
function KeepDialog({ flag, onClose, onKeep }: {
  flag: Flag; onClose: () => void; onKeep: (note?: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Modal
      title="Keep it as it is"
      description={flag.plain_message}
      onClose={onClose}
      width={560}
      footer={
        <>
          {err && <div className="error-box small grow">{err}</div>}
          <span className="grow" />
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="primary" disabled={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await onKeep(note || undefined);
                onClose();
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
                setBusy(false);
              }
            }}>
            {busy ? "Saving…" : "Keep as it is"}
          </button>
        </>
      }
    >
      <label className="lbl" htmlFor="keep-note">Why is this fine? (optional)</label>
      <textarea id="keep-note" value={note} rows={3} onChange={(e) => setNote(e.target.value)}
        placeholder="For example: the department agreed this weighting with the dean." />
      <p className="hint">
        The syllabus is not changed. The note is kept with the record so anyone reviewing it later can see
        why you left it.
      </p>
    </Modal>
  );
}
