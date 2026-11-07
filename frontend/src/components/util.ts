export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const fmtPct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v}%`);

export const parseNums = (s: string): number[] =>
  [...new Set((s.match(/\d+/g) ?? []).map(Number).filter((n) => n > 0 && n < 100))].sort((a, b) => a - b);

/** Which tab shows the record field a JSON Pointer refers to. */
export function tabFor(ptr: string): string {
  if (ptr.startsWith("/course") || ptr.startsWith("/offering") || ptr.startsWith("/resources")) return "course";
  if (ptr.startsWith("/clos")) return "clos";
  if (ptr.startsWith("/weights") || ptr.startsWith("/clo_matrix")) return "assessments";
  if (ptr.startsWith("/weekly")) return "weekly";
  if (ptr.startsWith("/programs")) return "programs";
  if (ptr.startsWith("/raw_sections") || ptr.startsWith("/notes")) return "source";
  return "course";
}

export function ptrLabel(ptr: string): string {
  return ptr
    .replace(/^\/weekly\/(\d+)/, (_, i) => `week row ${Number(i) + 1}`)
    .replace(/^\/weights\/(\d+)/, (_, i) => `weight row ${Number(i) + 1}`)
    .replace(/^\/clo_matrix\/(\d+)/, (_, i) => `matrix column ${Number(i) + 1}`)
    .replace(/^\/programs\/(\d+)/, (_, i) => `program ${Number(i) + 1}`)
    .replace(/^\/clos\/(\d+)/, (_, i) => `CLO row ${Number(i) + 1}`)
    .replace(/^\/raw_sections\//, "section: ")
    .replace(/~1/g, "/")
    .replace(/~0/g, "~")
    .replace(/^\//, "")
    .replace(/\//g, " › ")
    .replace(/_/g, " ");
}

export const isUnder = (path: string, focus: string | null) =>
  !!focus && (path === focus || path.startsWith(focus + "/") || focus.startsWith(path + "/"));
