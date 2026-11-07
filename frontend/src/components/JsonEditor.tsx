/**
 * Structured editor for any draft part (body / answer key / feedback).
 * Objects become labelled fields, arrays get add/remove, strings become
 * text boxes, numbers number inputs. The backend re-validates the result
 * against the item type's schema on save.
 */

const NUMERIC = new Set(["value", "minutes", "points", "session_minutes", "numeric_answer", "tolerance", "week_no"]);

const label = (k: string) => k.replace(/_/g, " ");

function blank(sample: unknown): unknown {
  if (Array.isArray(sample)) return [];
  if (sample && typeof sample === "object")
    return Object.fromEntries(Object.entries(sample).map(([k, v]) => [k, blank(v)]));
  if (typeof sample === "number") return 0;
  if (typeof sample === "boolean") return false;
  return "";
}

interface Props {
  value: unknown;
  onChange: (v: unknown) => void;
  name?: string;
}

export default function JsonEditor({ value, onChange, name }: Props) {
  if (Array.isArray(value)) {
    const sample = value[0];
    return (
      <div className="je-array">
        {value.map((v, i) => (
          <div key={i} className="je-row">
            <div className="je-index">{i + 1}</div>
            <div className="je-grow">
              <JsonEditor value={v} name={name} onChange={(nv) => onChange(value.map((x, j) => (j === i ? nv : x)))} />
            </div>
            <button className="icon danger" type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Remove">
              ✕
            </button>
          </div>
        ))}
        <button className="icon" type="button" onClick={() => onChange([...value, sample !== undefined ? blank(sample) : ""])}>
          + add
        </button>
      </div>
    );
  }
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    // why_others_wrong-style maps: string -> string
    return (
      <div className="je-object">
        {Object.entries(obj).map(([k, v]) => (
          <div key={k} className="je-field">
            <label className="lbl">{label(k)}</label>
            <JsonEditor value={v} name={k} onChange={(nv) => onChange({ ...obj, [k]: nv })} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "number" || (value === null && name && NUMERIC.has(name))) {
    return (
      <input
        type="number"
        step="any"
        value={value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    );
  }
  if (typeof value === "boolean") {
    return <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} style={{ width: "auto" }} />;
  }
  const s = value === null || value === undefined ? "" : String(value);
  const long = s.length > 70 || s.includes("\n") || ["content", "scenario", "statement", "stem", "description", "model_answer", "teaching_notes"].includes(name ?? "");
  return long ? (
    <textarea value={s} rows={Math.min(12, Math.max(2, Math.ceil(s.length / 90) + s.split("\n").length - 1))} onChange={(e) => onChange(e.target.value)} />
  ) : (
    <input value={s} onChange={(e) => onChange(e.target.value === "" && value === null ? null : e.target.value)} />
  );
}
