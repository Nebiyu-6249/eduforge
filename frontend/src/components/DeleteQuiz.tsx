import { api } from "../api";
import BinButton from "./BinButton";

/* Deletes one quiz or exam, approved ones too; the questions stay in the
   question bank. The server refuses (and says why) while the quiz is being
   written or once students' answers or marks belong to it. */
export default function DeleteQuiz({ form, onDeleted, onError }: {
  form: { id: number; assessment_name: string; version_label: string; status: string };
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const name = `${form.assessment_name} · Version ${form.version_label}`;
  const warn = form.status === "approved" ? " It is approved, so make sure you no longer need the paper." : "";
  return (
    <BinButton label={`Delete ${name}`} question={`Delete ${name}?${warn} Its questions stay in your question bank.`}
      remove={() => api.deleteForm(form.id)} onDone={onDeleted} onError={onError} />
  );
}
