import { useState } from "react";
import { api, ApiError } from "../api";
import Icon from "./Icon";

/* A bin button that deletes one quiz or exam after asking once. Approved
   papers can go too; the questions stay in the question bank either way. The
   server refuses (and says why) while the quiz is being written or once
   students' answers or marks belong to it. */
export default function DeleteQuiz({ form, onDeleted, onError }: {
  form: { id: number; assessment_name: string; version_label: string; status: string };
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const name = `${form.assessment_name} · Version ${form.version_label}`;

  async function go() {
    const warn = form.status === "approved" ? " It is approved, so make sure you no longer need the paper." : "";
    if (!confirm(`Delete ${name}?${warn} Its questions stay in your question bank.`)) return;
    setBusy(true);
    try {
      await api.deleteForm(form.id);
      onDeleted();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <button type="button" className="icon-only ghost danger" disabled={busy} onClick={go}
      aria-label={`Delete ${name}`} title="Delete">
      <Icon name="trash" size={18} />
    </button>
  );
}
