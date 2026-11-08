import { useState } from "react";
import { ApiError } from "../api";
import Icon from "./Icon";

/* A bin icon that deletes something after asking once. Used for quizzes and
   for courses. It sits inside clickable rows, so its clicks stop here. */
export default function BinButton({ label, question, remove, onDone, onError }: {
  label: string;          // read out by screen readers: "Delete STAT 100 Fall 2026"
  question: string;       // the confirm question
  remove: () => Promise<unknown>;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function go(e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(question)) return;
    setBusy(true);
    try {
      await remove();
      onDone();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <button type="button" className="icon-only ghost danger" disabled={busy} onClick={go}
      onKeyDown={(e) => e.stopPropagation()} aria-label={label} title="Delete">
      <Icon name="trash" size={18} />
    </button>
  );
}
