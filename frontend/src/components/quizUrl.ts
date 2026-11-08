/* The quiz flow keeps its step and every choice in the address, so browser
   Back and Forward move between steps, a refresh keeps the place, and a link
   can be shared (GOV.UK question pages work the same way). This module reads
   and writes that address. */

export const PRACTICE = "practice";

export interface QuizChoices {
  step: number;                 // 1-4
  for: string | null;           // a syllabus assessment name, PRACTICE, or null (not picked yet)
  weeks: number[];
  outcomes: number[];
  mix: Record<string, number>;  // type -> how many
  points: Record<string, number>;
  difficulty: string;           // easy | medium | hard
}

/** "1,2,3,5,9,10,11" -> "1-3,5,9-11" */
export function packNumbers(xs: number[]): string {
  const s = [...new Set(xs)].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < s.length; i++) {
    let j = i;
    while (j + 1 < s.length && s[j + 1] === s[j] + 1) j++;
    out.push(j > i ? `${s[i]}-${s[j]}` : `${s[i]}`);
    i = j;
  }
  return out.join(",");
}

export function unpackNumbers(v: string | null): number[] {
  if (!v) return [];
  const out: number[] = [];
  for (const part of v.split(",")) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part.trim());
    if (!m) continue;
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    for (let n = Math.min(a, b); n <= Math.max(a, b) && n - a < 200; n++) out.push(n);
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

const packMap = (m: Record<string, number>) =>
  Object.entries(m).filter(([, n]) => n > 0).map(([k, n]) => `${k}:${n}`).join(",");

function unpackMap(v: string | null): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of (v ?? "").split(",")) {
    const [k, n] = part.split(":");
    if (k && n !== undefined && !Number.isNaN(Number(n))) out[k] = Number(n);
  }
  return out;
}

export function readChoices(p: URLSearchParams): QuizChoices {
  const step = Math.min(4, Math.max(1, Number(p.get("step")) || 1));
  return {
    step,
    for: p.get("for"),
    weeks: unpackNumbers(p.get("weeks")),
    outcomes: unpackNumbers(p.get("outcomes")),
    mix: unpackMap(p.get("mix")),
    points: unpackMap(p.get("points")),
    difficulty: ["easy", "medium", "hard"].includes(p.get("difficulty") ?? "") ? p.get("difficulty")! : "medium",
  };
}

export function writeChoices(c: Partial<QuizChoices>): URLSearchParams {
  const p = new URLSearchParams();
  if (c.step) p.set("step", String(c.step));
  if (c.for) p.set("for", c.for);
  if (c.weeks?.length) p.set("weeks", packNumbers(c.weeks));
  if (c.outcomes?.length) p.set("outcomes", packNumbers(c.outcomes));
  if (c.mix && packMap(c.mix)) p.set("mix", packMap(c.mix));
  if (c.points && packMap(c.points)) p.set("points", packMap(c.points));
  if (c.difficulty && c.difficulty !== "medium") p.set("difficulty", c.difficulty);
  return p;
}

/** Link into the flow, prefilled. */
export function newQuizUrl(cv: number, c: Partial<QuizChoices> = {}): string {
  const q = writeChoices(c).toString();
  return `/v/${cv}/quiz/new${q ? `?${q}` : ""}`;
}

/** The same choices again, from a paper's blueprint: "Make another version" and "Try again". */
export function againUrl(cv: number, form: { assessment_name: string; blueprint: Record<string, any> }, step = 3): string {
  const bp = form.blueprint ?? {};
  return newQuizUrl(cv, {
    step,
    for: form.assessment_name === "Practice questions" ? PRACTICE : form.assessment_name,
    weeks: bp.weeks ?? [],
    outcomes: bp.clo_numbers ?? [],
    mix: bp.types ?? {},
    points: bp.points_per_type ?? {},
    difficulty: bp.difficulty ?? "medium",
  });
}

const STORE = "eduforge.quiz-choices";

/** Choices are also kept for the session, so leaving the flow loses nothing. */
export function saveSession(cv: number, search: string): void {
  try {
    sessionStorage.setItem(`${STORE}.${cv}`, search);
  } catch {
    /* private mode or full storage: the address still holds everything */
  }
}

export function loadSession(cv: number): string | null {
  try {
    return sessionStorage.getItem(`${STORE}.${cv}`);
  } catch {
    return null;
  }
}

export function clearSession(cv: number): void {
  try {
    sessionStorage.removeItem(`${STORE}.${cv}`);
  } catch {
    /* nothing to do */
  }
}
