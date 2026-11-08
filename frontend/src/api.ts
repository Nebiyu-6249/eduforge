import type {
  AppNotification,
  AssessmentOverview,
  Coverage,
  DraftContext,
  DraftItem,
  DraftType,
  Dashboard,
  Grounding,
  QuizMixPart,
  QuizOptions,
  SearchHit,
  EditEntry,
  EditOp,
  GenerateRequest,
  Job,
  Material,
  QuizForm,
  VersionDetail,
  VersionSummary,
} from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
const USER_KEY = "eduforge.devUser";

export interface DevUser {
  email: string;
  name: string;
}

export function getUser(): DevUser | null {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as DevUser) : null;
}

export function setUser(u: DevUser | null) {
  if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
  else localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public items?: { id?: number; rule_id?: string; message?: string; loc?: string; msg?: string }[],
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const u = getUser();
  const headers: Record<string, string> = {};
  if (u) {
    headers["X-Dev-User"] = u.email;
    headers["X-Dev-Name"] = u.name;
  }
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(BASE + path, {
    credentials: "include",
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    if (typeof d === "string") throw new ApiError(res.status, d);
    if (d && typeof d === "object" && "message" in d) throw new ApiError(res.status, d.message, d.items);
    if (Array.isArray(d)) throw new ApiError(res.status, d.map((x) => x.msg).join("; "));
    throw new ApiError(res.status, `Request failed (${res.status})`);
  }
  return data as T;
}

export const api = {
  me: () => call<{ id: number; email: string; name: string; is_team: boolean }>("GET", "/api/me"),
  // ---- home screen ----
  dashboard: () => call<Dashboard>("GET", "/api/dashboard"),
  search: (q: string) => call<SearchHit[]>("GET", `/api/search?q=${encodeURIComponent(q)}`),
  notifications: () => call<AppNotification[]>("GET", "/api/notifications"),
  markNotificationsRead: (keys?: string[]) =>
    call<void>("POST", "/api/notifications/read", { keys: keys ?? [] }),
  // ---- create a quiz or exam ----
  quizOptions: (cv: number) => call<QuizOptions>("GET", `/api/course-versions/${cv}/quiz-options`),
  createQuiz: (cv: number, body: {
    assessment_name: string | null; weeks: number[]; clo_numbers: number[];
    difficulty: string | null; mix: QuizMixPart[]; notes?: string | null;
  }) => call<Job>("POST", `/api/course-versions/${cv}/quizzes`, body),
  sampleClass: (formId: number, sectionId: number) =>
    call<{ students: number; submissions: number; job: Job }>(
      "POST", `/api/grading/forms/${formId}/sections/${sectionId}/sample-class`),
  teamMetrics: () => call<unknown>("GET", "/api/team/metrics"),
  list: () => call<VersionSummary[]>("GET", "/api/course-versions?include_superseded=true"),
  get: (id: number) => call<VersionDetail>("GET", `/api/course-versions/${id}`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<Job>("POST", "/api/syllabi", fd, true);
  },
  job: (id: number) => call<Job>("GET", `/api/jobs/${id}`),
  edit: (id: number, ops: EditOp[], note?: string) =>
    call<VersionDetail>("PATCH", `/api/course-versions/${id}/record`, { ops, note }),
  resolve: (id: number, flagId: number, action: "accept" | "reopen", note?: string) =>
    call<VersionDetail>("POST", `/api/course-versions/${id}/flags/${flagId}/resolve`, { action, note }),
  choose: (id: number, flagId: number, choice: number) =>
    call<VersionDetail>("POST", `/api/course-versions/${id}/flags/${flagId}/choose`, { choice }),
  carryOver: (id: number, fromId: number) =>
    call<VersionDetail>("POST", `/api/course-versions/${id}/carry-over`, { from_version_id: fromId }),
  async download(path: string, fallbackName: string) {
    const u = getUser();
    const res = await fetch(BASE + path, { credentials: "include", headers: u ? { "X-Dev-User": u.email } : {} });
    if (!res.ok) throw new ApiError(res.status, "Download failed.");
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  revalidate: (id: number) => call<VersionDetail>("POST", `/api/course-versions/${id}/revalidate`),
  lock: (id: number) => call<VersionDetail>("POST", `/api/course-versions/${id}/lock`),
  revise: (id: number) => call<VersionDetail>("POST", `/api/course-versions/${id}/revise`),
  rollover: (id: number, term: string) => call<VersionDetail>("POST", `/api/course-versions/${id}/rollover`, { term }),
  discard: (id: number) => call<void>("DELETE", `/api/course-versions/${id}`),
  edits: (id: number) => call<EditEntry[]>("GET", `/api/course-versions/${id}/edits`),
  coverage: (id: number) => call<Coverage>("GET", `/api/course-versions/${id}/coverage`),
  assessmentOverview: (id: number) =>
    call<AssessmentOverview>("GET", `/api/course-versions/${id}/assessment-overview`),
  // ---- Draft Studio ----
  draftTypes: () => call<DraftType[]>("GET", "/api/draft-types"),
  draftContext: (cv: number) => call<DraftContext>("GET", `/api/course-versions/${cv}/draft-context`),
  drafts: (cv: number) => call<DraftItem[]>("GET", `/api/course-versions/${cv}/drafts`),
  generate: (cv: number, req: GenerateRequest) => call<Job>("POST", `/api/course-versions/${cv}/drafts`, req),
  materials: (cv: number) => call<Material[]>("GET", `/api/course-versions/${cv}/materials`),
  uploadMaterial: (cv: number, file: File, meta: { kind: string; week_no?: number | null; title?: string; licensed: boolean }) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", meta.kind);
    if (meta.week_no) fd.append("week_no", String(meta.week_no));
    if (meta.title) fd.append("title", meta.title);
    fd.append("licensed", String(meta.licensed));
    return call<Job>("POST", `/api/course-versions/${cv}/materials`, fd, true);
  },
  updateMaterial: (id: number, patch: Partial<Pick<Material, "week_no" | "kind" | "licensed" | "title">>) =>
    call<Job>("PATCH", `/api/materials/${id}`, patch),
  reindexMaterial: (id: number) => call<Job>("POST", `/api/materials/${id}/reindex`),
  deleteMaterial: (id: number) => call<void>("DELETE", `/api/materials/${id}`),
  async figure(id: number): Promise<string> {
    const u = getUser();
    const res = await fetch(`${BASE}/api/drafts/${id}/figure.png`, { credentials: "include", headers: u ? { "X-Dev-User": u.email } : {} });
    if (!res.ok) throw new ApiError(res.status, "No figure image.");
    return URL.createObjectURL(await res.blob());
  },
  // ---- Phase 3: Assessment Builder ----
  assessments: (cv: number) => call<any[]>("GET", `/api/course-versions/${cv}/assessments`),
  blueprint: (cv: number, name: string, week?: number | null) =>
    call<any>("GET", `/api/course-versions/${cv}/blueprint?name=${encodeURIComponent(name)}${week ? `&week=${week}` : ""}`),
  buildForms: (cv: number, body: { blueprint: any; versions: number; sections?: string[]; allow_reuse?: boolean }) =>
    call<any[]>("POST", `/api/course-versions/${cv}/forms`, body),
  forms: (cv: number) => call<QuizForm[]>("GET", `/api/course-versions/${cv}/forms`),
  /** Work this teacher has running, and what finished in the last day. */
  activeJobs: () => call<Job[]>("GET", "/api/jobs?active=1"),
  recentJobs: () => call<Job[]>("GET", "/api/jobs?recent=1"),
  form: (id: number) => call<QuizForm>("GET", `/api/forms/${id}`),
  editForm: (id: number, body: any) => call<any>("POST", `/api/forms/${id}/edit`, body),
  deleteForm: (id: number) => call<void>("DELETE", `/api/forms/${id}`),
  pool: (cv: number) => call<any[]>("GET", `/api/course-versions/${cv}/pool`),
  // ---- Phase 4: Grading & Feedback Assist ----
  gradingStatus: () =>
    call<{ enabled: boolean; llm_approved: boolean; sandbox: string | null; suggest_off: string[] }>("GET", "/api/grading/status"),
  gradingScale: (cv: number) => call<any>("GET", `/api/grading/course-versions/${cv}/scale`),
  confirmScale: (cv: number, bands: any[], acknowledge_difference: boolean, note?: string) =>
    call<any>("POST", `/api/grading/course-versions/${cv}/scale`, { bands, acknowledge_difference, note }),
  gradingSections: (cv: number) => call<any[]>("GET", `/api/grading/course-versions/${cv}/sections`),
  addSection: (cv: number, label: string) => call<any>("POST", `/api/grading/course-versions/${cv}/sections`, { label }),
  uploadRoster: (sid: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<{ students: number; added: number; updated: number }>("POST", `/api/grading/sections/${sid}/roster`, fd, true);
  },
  roster: (sid: number, reveal: boolean) => call<any[]>("GET", `/api/grading/sections/${sid}/roster?reveal=${reveal}`),
  gradingForms: (cv: number) => call<any[]>("GET", `/api/grading/course-versions/${cv}/forms`),
  uploadSubmissions: (fid: number, sid: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<any>("POST", `/api/grading/forms/${fid}/sections/${sid}/submissions`, fd, true);
  },
  rescore: (fid: number, sid: number, rescore: boolean) =>
    call<Job>("POST", `/api/grading/forms/${fid}/sections/${sid}/score`, { rescore }),
  grid: (fid: number, sid: number) => call<any>("GET", `/api/grading/forms/${fid}/sections/${sid}/grid`),
  submission: (id: number) => call<any>("GET", `/api/grading/submissions/${id}`),
  confirmScore: (id: number, points: number, reason?: string) =>
    call<any>("POST", `/api/grading/scores/${id}/confirm`, { points, reason }),
  confirmKey: (fid: number, sid: number, item_id?: number) =>
    call<{ confirmed: number }>("POST", `/api/grading/forms/${fid}/sections/${sid}/confirm-key`, { item_id }),
  feedbackAction: (id: number, action: "approve" | "reject" | "edit", text?: string) =>
    call<any>("POST", `/api/grading/feedback/${id}`, { action, text }),
  addFeedback: (sub: number, item_id: number | null, text: string) =>
    call<any>("POST", `/api/grading/submissions/${sub}/feedback`, { item_id, text }),
  releaseGrades: (fid: number, sid: number) =>
    api.postDownload(`/api/grading/forms/${fid}/sections/${sid}/release`, {}, "grades.zip"),
  releases: (fid: number, sid: number) => call<any[]>("GET", `/api/grading/forms/${fid}/sections/${sid}/releases`),
  appeal: (sub: number, item_id: number | null, reason: string) =>
    call<any>("POST", `/api/grading/submissions/${sub}/appeals`, { item_id, reason }),
  decideAppeal: (id: number, outcome: string, points: Record<number, number>) =>
    call<any>("POST", `/api/grading/appeals/${id}/decide`, { outcome, points }),
  calibrate: (fid: number, file: File, description: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("description", description);
    return call<any>("POST", `/api/grading/forms/${fid}/calibration`, fd, true);
  },
  calibrations: (fid: number) => call<any[]>("GET", `/api/grading/forms/${fid}/calibration`),
  // ---- Phase 5: Blackboard ----
  lmsStatus: () => call<{ mode: "off" | "mock" | "blackboard"; connected: boolean }>("GET", "/api/lms/status"),
  lmsConnect: () => call<{ connected: boolean; authorize_url: string | null }>("POST", "/api/lms/connect"),
  lmsDisconnect: () => call<void>("POST", "/api/lms/disconnect"),
  lmsCourses: () => call<{ id: string; course_id: string; name: string; term: string | null }[]>("GET", "/api/lms/courses"),
  lmsLinks: (cv: number) => call<any[]>("GET", `/api/lms/course-versions/${cv}/links`),
  lmsLink: (cv: number, lms_course_id: string, section_id: number | null) =>
    call<any>("POST", "/api/lms/links", { course_version_id: cv, lms_course_id, section_id }),
  lmsUnlink: (id: number) => call<void>("DELETE", `/api/lms/links/${id}`),
  lmsPush: (link: number, form_id: number) => call<any>("POST", `/api/lms/links/${link}/push`, { form_id }),
  lmsColumns: (link: number) => call<any[]>("GET", `/api/lms/links/${link}/columns`),
  lmsAttach: (link: number, form_id: number, column_id: string) =>
    call<any>("POST", `/api/lms/links/${link}/attach`, { form_id, column_id }),
  lmsPull: (link: number, form_id: number, section_id: number | null) =>
    call<any>("POST", `/api/lms/links/${link}/pull`, { form_id, section_id }),
  lmsPassback: (link: number, form_id: number, section_id: number | null, dry_run: boolean, overwrite: string[] = []) =>
    call<any>("POST", `/api/lms/links/${link}/passback`, { form_id, section_id, dry_run, overwrite }),
  lmsSyncs: (link: number) => call<any[]>("GET", `/api/lms/links/${link}/syncs`),
  async postDownload(path: string, body: unknown, fallback: string) {
    const u = getUser();
    const res = await fetch(BASE + path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(u ? { "X-Dev-User": u.email } : {}) },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      throw new ApiError(res.status, typeof d?.detail === "string" ? d.detail : d?.detail?.message ?? "Download failed.");
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? fallback;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
  bankImport: (cv: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<Job>("POST", `/api/course-versions/${cv}/bank-import`, fd, true);
  },
  termDiff: (cv: number) => call<any>("GET", `/api/course-versions/${cv}/diff`),
  share: (item: number, shared: boolean) => call<void>("POST", `/api/drafts/${item}/share`, { shared }),
  solvability: (item: number) => call<Job>("POST", `/api/drafts/${item}/solvability`),
  solvabilityResults: (item: number) => call<any[]>("GET", `/api/drafts/${item}/solvability`),
  programs: () => call<{ id: number; name: string }[]>("GET", "/api/programs"),
  programCoverage: (id: number, term?: string, qa = false) =>
    call<any>("GET", `/api/${qa ? "qa/" : ""}programs/${id}/coverage${term ? `?term=${encodeURIComponent(term)}` : ""}`),
  qaPrograms: () => call<{ id: number; name: string }[]>("GET", "/api/qa/programs"),
  qaSyllabi: (term?: string) => call<any[]>("GET", `/api/qa/syllabi${term ? `?term=${encodeURIComponent(term)}` : ""}`),
  whoami: () => call<{ email: string; name: string; role: "faculty" | "viewer" }>("GET", "/api/auth/whoami"),
  item: (id: number) => call<DraftItem>("GET", `/api/drafts/${id}`),
  grounding: (id: number) => call<Grounding>("GET", `/api/drafts/${id}/grounding`),
  editItem: (id: number, patch: { tags?: object; body?: object; answer_key?: object | null; feedback?: object | null; notes?: string }) =>
    call<DraftItem>("PATCH", `/api/drafts/${id}`, patch),
  itemAction: (id: number, action: "approve" | "reject" | "reopen" | "regenerate", notes?: string) =>
    call<{ item: DraftItem; replacements: DraftItem[]; job: Job | null }>("POST", `/api/drafts/${id}/action`, { action, notes }),
  recheck: (id: number) => call<DraftItem>("POST", `/api/drafts/${id}/recheck`),
  /** The question paper and the answer key are separate files (part). */
  exportItems: (cv: number, format: "docx" | "pdf", part: "paper" | "key", itemIds?: number[]) =>
    api.postDownload(`/api/course-versions/${cv}/export`, { format, part, item_ids: itemIds ?? null },
      `${part === "key" ? "answer_key" : "question_paper"}.${format}`),
  async pageImage(cv: number, page: number): Promise<string> {
    const u = getUser();
    const res = await fetch(`${BASE}/api/course-versions/${cv}/source/pages/${page}`, {
      credentials: "include",
      headers: u ? { "X-Dev-User": u.email } : {},
    });
    if (!res.ok) throw new ApiError(res.status, "Could not load the page image.");
    return URL.createObjectURL(await res.blob());
  },
  sourceUrl: (id: number) => `${BASE}/api/course-versions/${id}/source`,
  async downloadSource(id: number, filename: string) {
    const u = getUser();
    const res = await fetch(`${BASE}/api/course-versions/${id}/source`, {
      credentials: "include",
      headers: u ? { "X-Dev-User": u.email } : {},
    });
    if (!res.ok) throw new ApiError(res.status, "Could not download the source file.");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};

/** Poll a job until it finishes (plan 1.9 / 2.7). Throws ApiError if it failed. */
export async function waitJob(id: number, onProgress?: (j: Job) => void, intervalMs = 1000): Promise<Job> {
  for (;;) {
    const j = await api.job(id);
    onProgress?.(j);
    if (j.status === "done") return j;
    if (j.status === "failed") throw new ApiError(j.error_status ?? 500, j.error ?? "The job failed.");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/** Which sign-in the server uses: "dev" (header) or "sso" (university, cookie). */
export async function authConfig(): Promise<{ mode: string; login_url: string | null; notice?: string | null }> {
  try {
    const res = await fetch(`${BASE}/api/auth/config`, { credentials: "include" });
    return res.ok ? await res.json() : { mode: "dev", login_url: null };
  } catch {
    return { mode: "dev", login_url: null }; // older server or network error: never hang on "Loading…"
  }
}

export const ssoLoginUrl = (next = "/") => `${BASE}/api/auth/login?next=${encodeURIComponent(next)}`;

export async function ssoLogout(): Promise<void> {
  await fetch(`${BASE}/api/auth/logout`, { method: "POST", credentials: "include" });
}
