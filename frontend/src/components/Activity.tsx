import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Job } from "../types";
import Icon from "./Icon";

/* Work that keeps going when the teacher leaves the page, shown the way Google
   Drive's upload panel and Microsoft 365's activity list show it: a small icon
   with a count while anything runs, a panel with a row per piece of work, and
   a note when something finishes while you were looking at something else. */

/** Pages dispatch this after starting work, so the panel starts watching at once. */
export const JOB_STARTED = "eduforge:job-started";
export const announceJob = () => window.dispatchEvent(new Event(JOB_STARTED));
/** Fired with the finished job as detail, so pages showing it can refresh. */
export const JOB_FINISHED = "eduforge:job-finished";

const FAST_MS = 3000;
const SLOW_MS = 30000;

interface Toast {
  id: number;
  text: string;
  link: string | null;
  ok: boolean;
}

function statusLine(j: Job): string {
  if (j.status === "queued") return "Waiting to start";
  if (j.status === "running") return j.time_left ?? "Working";
  if (j.status === "done") return "Ready";
  return j.error ?? "Could not be finished";
}

export default function Activity() {
  const [active, setActive] = useState<Job[]>([]);
  const [recent, setRecent] = useState<Job[]>([]);
  const [open, setOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [said, setSaid] = useState("");
  const known = useRef<Set<number>>(new Set());
  const first = useRef(true);
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const nav = useNavigate();

  const toast = (t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((xs) => [...xs.slice(-2), { ...t, id }]);
    setSaid(t.text);
    window.setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), 9000);
  };

  const loadRecent = useCallback(() => api.recentJobs().then(setRecent).catch(() => undefined), []);

  const poll = useCallback(async () => {
    window.clearTimeout(timer.current);
    let now: Job[] = [];
    try {
      now = await api.activeJobs();
      setActive(now);
      const ids = new Set(now.map((j) => j.id));
      const gone = [...known.current].filter((id) => !ids.has(id));
      known.current = ids;
      if (gone.length && !first.current) {
        const finished = await Promise.all(gone.map((id) => api.job(id).catch(() => null)));
        for (const j of finished) {
          if (!j || !j.title) continue;
          window.dispatchEvent(new CustomEvent(JOB_FINISHED, { detail: j }));
          toast(j.status === "done"
            ? { text: `${j.title} is ready.`, link: j.link, ok: true }
            : { text: `${j.title} could not be finished. ${j.error ?? ""}`.trim(), link: j.link, ok: false });
        }
        loadRecent();
        window.dispatchEvent(new Event("eduforge:version-changed"));  // the bell refreshes too
      }
      first.current = false;
    } catch {
      /* the server may be asleep; try again on the slow beat */
    }
    timer.current = window.setTimeout(poll, now.length ? FAST_MS : SLOW_MS);
  }, [loadRecent]);

  useEffect(() => {
    poll();
    loadRecent();
    const kick = () => window.setTimeout(poll, 300);
    window.addEventListener(JOB_STARTED, kick);
    return () => {
      window.clearTimeout(timer.current);
      window.removeEventListener(JOB_STARTED, kick);
    };
  }, [poll, loadRecent]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, []);

  const go = (link: string | null) => {
    setOpen(false);
    if (link) nav(link);
  };
  const shownRecent = recent.filter((r) => !active.some((a) => a.id === r.id)).slice(0, 8);

  return (
    <>
      <div className="bell activity" ref={box}>
        <button className="ghost" aria-expanded={open} aria-haspopup="true"
          aria-label={active.length ? `Work in progress, ${active.length} running` : "Work in progress"}
          onClick={() => { setOpen(!open); if (!open) loadRecent(); }}>
          <Icon name="activity" size={20} />
          {active.length > 0 && <span className="dot busy" aria-hidden="true">{active.length}</span>}
        </button>
        {open && (
          <div className="popover activity-pop">
            <header><h3>Work in progress</h3></header>
            <div className="list">
              {active.length === 0 && shownRecent.length === 0 && (
                <p className="empty-note">
                  Nothing is running. When you create a quiz or add slides, the work shows here and keeps
                  going if you leave the page.
                </p>
              )}
              {active.map((j) => (
                <div key={j.id} className="job-row">
                  <div className="job-head">
                    <strong>{j.title ?? "Working"}</strong>
                    {j.course_label && <span className="small muted">{j.course_label}</span>}
                  </div>
                  <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                    aria-valuenow={j.progress} aria-label={`${j.title ?? "Work"} progress`}>
                    <span style={{ width: `${Math.max(4, j.progress)}%` }} />
                  </div>
                  <div className="job-foot">
                    <span className="small muted">{statusLine(j)}</span>
                    {j.link && <button className="link small" onClick={() => go(j.link)}>View</button>}
                  </div>
                </div>
              ))}
              {shownRecent.length > 0 && <div className="pop-sub">Finished today</div>}
              {shownRecent.map((j) => (
                <div key={j.id} className={`job-row ${j.status}`}>
                  <div className="job-head">
                    <strong>{j.title ?? "Work"}</strong>
                    {j.course_label && <span className="small muted">{j.course_label}</span>}
                  </div>
                  <div className="job-foot">
                    <span className={`small ${j.status === "failed" ? "err-text" : "muted"}`}>
                      {j.status === "done" ? "Ready" : j.error ?? "Could not be finished"}
                    </span>
                    {j.link && (
                      <button className="link small" onClick={() => go(j.link)}>
                        {j.status === "done" ? "Open" : "Try again"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="sr-only" aria-live="polite">{said}</div>
      {toasts.length > 0 && (
        <div className="toast-stack">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.ok ? "" : "bad"}`} role="status">
              <span>{t.text}</span>
              {t.link && (
                <button className="toast-act" onClick={() => {
                  setToasts((xs) => xs.filter((x) => x.id !== t.id));
                  go(t.link);
                }}>{t.ok ? "Open" : "See why"}</button>
              )}
              <button className="toast-x" aria-label="Dismiss" onClick={() => setToasts((xs) => xs.filter((x) => x.id !== t.id))}>
                <Icon name="close" size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
