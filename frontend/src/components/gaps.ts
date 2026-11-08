/* What a paper is missing, said in plain words. Gaps come in two shapes:
   quizzes written by EduForge carry a ready sentence ({ warning }), papers put
   together from the question bank carry the numbers behind the shortfall
   ({ type, count, clo_numbers, weeks, reason }). Both read as one sentence. */

const NOUN: Record<string, [string, string]> = {
  mcq: ["multiple-choice question", "multiple-choice questions"],
  short_answer: ["short-answer question", "short-answer questions"],
  problem: ["worked problem", "worked problems"],
  code_exercise: ["code exercise", "code exercises"],
  case_study: ["case study", "case studies"],
  practice_set: ["practice set", "practice sets"],
};

export interface Gap {
  warning?: string;
  type?: string | null;
  count?: number;
  clo_numbers?: number[];
  weeks?: number[];
  reason?: string;
}

/** "1", "1 and 3", "1, 2 and 3" */
export function andList(xs: (number | string)[]): string {
  if (xs.length <= 1) return xs.join("");
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

function weeksText(weeks: number[] | undefined): string {
  if (!weeks?.length) return "";
  const w = [...weeks].sort((a, b) => a - b);
  if (w.length === 1) return `week ${w[0]}`;
  const run = w.every((n, i) => i === 0 || n === w[i - 1] + 1);
  return run ? `weeks ${w[0]} to ${w[w.length - 1]}` : `weeks ${andList(w)}`;
}

function outcomesText(clos: number[] | undefined): string {
  if (!clos?.length) return "";
  return `${clos.length === 1 ? "outcome" : "outcomes"} ${andList(clos)}`;
}

export function gapText(g: Gap): string {
  if (g.warning) return g.warning;
  const n = g.count ?? 0;
  const where = [outcomesText(g.clo_numbers), weeksText(g.weeks)].filter(Boolean).join(" in ");
  if (g.type) {
    const [one, many] = NOUN[g.type] ?? ["question", "questions"];
    return `${n} ${n === 1 ? one : many} could not be added. The question bank has no more approved ones` +
      `${where ? ` for ${where}` : ""} that are not already in this paper or too similar to one that is.`;
  }
  // An outcome with too few questions: "Outcome 3 is under-covered (0 of ~5 items)".
  const m = /\((\d+) of (?:~|about )(\d+)/.exec(g.reason ?? "");
  const clo = g.clo_numbers?.length ? andList(g.clo_numbers) : "";
  if (m) {
    const have = Number(m[1]), want = Number(m[2]);
    return `Outcome ${clo} has ${have === 0 ? "no" : have} question${have === 1 ? "" : "s"} in this paper; ` +
      `about ${want} would match how much of the course it covers.`;
  }
  return `Outcome ${clo} needs about ${n} more question${n === 1 ? "" : "s"}.`;
}
