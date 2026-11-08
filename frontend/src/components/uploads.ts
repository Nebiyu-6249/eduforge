import { useSyncExternalStore } from "react";
import { api, ApiError } from "../api";
import type { Job } from "../types";
import { announceJob } from "./Activity";

/* The upload queue, kept outside React so it carries on while the teacher
   moves around the app (like Google Drive's upload panel). Each file is sent
   with byte progress, up to three at once; once sent, the server reads it in
   the background and the row follows that work until it is ready. Only
   closing or reloading the tab loses bytes still being sent: the browser asks
   first, and the page lists those files afterwards so they can be added again. */

export type Phase = "waiting" | "uploading" | "reading" | "ready" | "failed";

export interface UploadRow {
  id: number;
  scope: string;           // "materials:3", "syllabus"
  name: string;
  size: number;
  phase: Phase;
  sent: number;
  started: number | null;  // ms, when sending began
  jobId: number | null;
  jobProgress: number;
  timeLeft: string | null; // words, from the server while reading
  error: string | null;
  link: string | null;     // where the finished file opens (a new syllabus)
}

type Sender = (file: File, onProgress: (sent: number, total: number) => void) => Promise<Job>;

const PARALLEL = 3;
const UNSENT_KEY = "eduforge.unsent-uploads";
const BOOT = Date.now();  // when this page load began

let rows: UploadRow[] = [];
const files = new Map<number, { file: File; send: Sender; onSettled?: () => void }>();
const listeners = new Set<() => void>();
let nextId = 1;

function emit() {
  rows = [...rows];
  listeners.forEach((l) => l());
}

function patch(id: number, p: Partial<UploadRow>) {
  rows = rows.map((r) => (r.id === id ? { ...r, ...p } : r));
  emit();
}

export function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useUploads(scope: string): UploadRow[] {
  const all = useSyncExternalStore(subscribe, () => rows);
  return all.filter((r) => r.scope === scope);
}

/** Add files to the queue. `onSettled` runs as each one finishes (to refresh a list). */
export function enqueue(scope: string, list: File[], send: Sender, onSettled?: () => void, maxBytes?: number) {
  for (const file of list) {
    const id = nextId++;
    const tooBig = maxBytes !== undefined && file.size > maxBytes;
    rows.push({
      id, scope, name: file.name, size: file.size, phase: tooBig ? "failed" : "waiting", sent: 0, started: null,
      jobId: null, jobProgress: 0, timeLeft: null, link: null,
      error: tooBig ? `This file is larger than ${Math.round(maxBytes! / 1048576)} MB, the most one upload can be.` : null,
    });
    if (!tooBig) files.set(id, { file, send, onSettled });
  }
  emit();
  pump();
}

export function remove(id: number) {
  rows = rows.filter((r) => r.id !== id || r.phase === "uploading" || r.phase === "reading");
  files.delete(id);
  emit();
}

export function clearFinished(scope: string) {
  rows = rows.filter((r) => r.scope !== scope || !(r.phase === "ready" || r.phase === "failed"));
  emit();
}

/** A file rejected before sending (too large) cannot be retried as it is. */
export const canRetry = (id: number) => files.has(id);

export function retry(id: number) {
  if (!files.has(id)) return;
  patch(id, { phase: "waiting", sent: 0, started: null, jobId: null, jobProgress: 0, timeLeft: null, error: null });
  pump();
}

function pump() {
  while (rows.filter((r) => r.phase === "uploading").length < PARALLEL) {
    const next = rows.find((r) => r.phase === "waiting");
    if (!next) return;
    start(next.id);
  }
}

async function start(id: number) {
  const f = files.get(id);
  if (!f) return;
  patch(id, { phase: "uploading", started: Date.now(), sent: 0 });
  let job: Job;
  try {
    job = await f.send(f.file, (sent) => patch(id, { sent }));
  } catch (e) {
    patch(id, { phase: "failed", error: e instanceof ApiError ? e.message : String(e) });
    pump();
    return;
  }
  announceJob();
  patch(id, { phase: "reading", sent: f.file.size, jobId: job.id, jobProgress: job.progress, timeLeft: job.time_left });
  pump();
  follow(id, job);
}

async function follow(id: number, job: Job) {
  let j = job;
  while (j.status === "queued" || j.status === "running") {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      j = await api.job(j.id);
    } catch {
      continue;  // a sleeping server: keep waiting
    }
    patch(id, { jobProgress: j.progress, timeLeft: j.time_left });
  }
  const f = files.get(id);
  if (j.status === "done") {
    patch(id, { phase: "ready", jobProgress: 100, timeLeft: null, link: j.link ?? null });
  } else {
    patch(id, { phase: "failed", error: j.error ?? "Couldn't read this file." });
  }
  f?.onSettled?.();
}

// ---- time left, in words -------------------------------------------------
export function words(secs: number | null): string | null {
  if (secs === null || !Number.isFinite(secs)) return null;
  if (secs < 60) return "less than a minute left";
  const m = Math.round(secs / 60);
  return m <= 1 ? "about a minute left" : m > 60 ? "more than an hour left" : `about ${m} minutes left`;
}

/** Seconds left to send this row, from its own rate so far. */
export function sendSecondsLeft(r: UploadRow): number | null {
  if (r.phase !== "uploading" || !r.started) return null;
  const elapsed = (Date.now() - r.started) / 1000;
  if (elapsed < 1 || r.sent === 0) return null;
  return ((r.size - r.sent) / r.sent) * elapsed;
}

/** "12 files · about 3 minutes left" for the whole batch. */
export function batchSummary(list: UploadRow[]): string | null {
  const open = list.filter((r) => r.phase === "waiting" || r.phase === "uploading" || r.phase === "reading");
  if (!open.length) return null;
  const rates = list.filter((r) => r.phase === "uploading" && r.started && r.sent > 0)
    .map((r) => r.sent / Math.max(1, (Date.now() - r.started!) / 1000));
  const rate = rates.length ? rates.reduce((a, b) => a + b, 0) : null;
  const bytes = open.filter((r) => r.phase !== "reading").reduce((s, r) => s + (r.size - r.sent), 0);
  const reading = open.some((r) => r.phase === "reading") ? 30 : 0;  // reading time is reported per file
  const secs = rate ? bytes / rate + reading : null;
  const left = words(secs);
  return `${open.length} file${open.length === 1 ? "" : "s"}${left ? ` · ${left}` : ""}`;
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} bytes`;
  if (n < 1048576) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1048576).toFixed(n < 10485760 ? 1 : 0)} MB`;
}

// ---- leaving the page while bytes are on their way -----------------------
export function sendingNames(): string[] {
  return rows.filter((r) => r.phase === "uploading" || r.phase === "waiting").map((r) => r.name);
}

window.addEventListener("beforeunload", (e) => {
  const names = sendingNames();
  if (!names.length) return;
  try {
    sessionStorage.setItem(UNSENT_KEY, JSON.stringify({ names, at: Date.now() }));
  } catch {
    /* nothing to keep */
  }
  e.preventDefault();
  e.returnValue = `${names.length} file${names.length === 1 ? " is" : "s are"} still uploading. Leave anyway?`;
});

/** Files that were still uploading when the page was last closed (shown once). */
export function takeUnsent(): string[] {
  try {
    const v = sessionStorage.getItem(UNSENT_KEY);
    if (!v) return [];
    const saved = JSON.parse(v) as { names: string[]; at: number };
    // Saved during this page load means the teacher chose to stay: nothing was lost.
    if (saved.at >= BOOT) return [];
    sessionStorage.removeItem(UNSENT_KEY);
    return saved.names;
  } catch {
    return [];
  }
}

