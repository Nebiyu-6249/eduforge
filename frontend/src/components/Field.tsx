import { useEffect, useRef, useState } from "react";
import { useShowSource } from "./SourcePanel";
import { isUnder, parseNums } from "./util";

export type Kind = "text" | "textarea" | "number" | "lines" | "nums" | "date";

interface Props {
  path: string;
  value: unknown;
  kind?: Kind;
  label?: string;
  editable: boolean;
  focus: string | null;
  onSave: (path: string, value: unknown) => Promise<void>;
  placeholder?: string;
  className?: string;
  display?: (v: unknown) => React.ReactNode;
}

function toText(v: unknown, kind: Kind): string {
  if (v === null || v === undefined) return "";
  if (kind === "lines") return (v as string[]).join("\n");
  if (kind === "nums") return (v as number[]).join(", ");
  return String(v);
}

function fromText(s: string, kind: Kind): unknown {
  const t = s.trim();
  switch (kind) {
    case "number":
      return t === "" ? null : Number(t);
    case "lines":
      return t.split("\n").map((x) => x.trim()).filter(Boolean);
    case "nums":
      return parseNums(t);
    case "date":
      return t === "" ? null : t;
    default:
      return t === "" ? null : t;
  }
}

/** A record value with an inline editor. Saving sends one logged 'replace' op. */
export default function Field({ path, value, kind = "text", label, editable, focus, onSave, placeholder, className, display }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const showSource = useShowSource();
  const hl = isUnder(path, focus);

  useEffect(() => {
    if (hl) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [hl]);

  const start = () => {
    setDraft(toText(value, kind));
    setErr(null);
    setEditing(true);
  };

  async function save() {
    const v = fromText(draft, kind);
    if (kind === "number" && v !== null && Number.isNaN(v)) {
      setErr("Enter a number.");
      return;
    }
    setSaving(true);
    try {
      await onSave(path, v);
      setEditing(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const empty = value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
  const multi = kind === "textarea" || kind === "lines";

  return (
    <div ref={ref} className={`field ${editing ? "editing" : ""} ${hl ? "hl" : ""} ${className ?? ""}`} data-path={path}>
      {label && <label className="lbl">{label}</label>}
      {editing ? (
        <div className="stack" style={{ marginTop: 2 }}>
          {multi ? (
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={kind === "lines" ? Math.max(3, draft.split("\n").length + 1) : 5}
              autoFocus
            />
          ) : (
            <input
              type={kind === "number" ? "number" : kind === "date" ? "date" : "text"}
              step="any"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
              autoFocus
            />
          )}
          {kind === "lines" && <div className="small muted">One item per line.</div>}
          {kind === "nums" && <div className="small muted">Numbers separated by commas, e.g. 1, 3.</div>}
          {err && <div className="error-box small">{err}</div>}
          <div className="row">
            <button className="primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            <button onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <div className={`val ${empty ? "empty" : ""}`}>
            {empty ? placeholder ?? "Not found in the file" : display ? display(value) : toText(value, kind === "lines" ? "lines" : kind)}
          </div>
          <button className="icon src-btn" onClick={() => showSource(path)} aria-label={`Source of ${label ?? path}: show the line it was read from`}>
            Source
          </button>
          {editable && (
            <button className="icon edit-btn" onClick={start} aria-label={`Edit ${label ?? path}`}>
              Edit
            </button>
          )}
        </>
      )}
    </div>
  );
}
