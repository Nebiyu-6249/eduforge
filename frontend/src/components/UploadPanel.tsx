import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import Icon from "./Icon";
import {
  batchSummary, canRetry, clearFinished, formatSize, remove, retry, sendSecondsLeft, takeUnsent, useUploads, words,
  type UploadRow,
} from "./uploads";

/* One row per file: name and size, a progress bar, the phase in plain words
   (Uploading, Reading, Ready, Couldn't read this file), time left, and what
   to do next. */

function phaseText(r: UploadRow): string {
  if (r.phase === "waiting") return "Waiting to upload";
  if (r.phase === "uploading") {
    const pct = r.size ? Math.round((100 * r.sent) / r.size) : 0;
    const left = words(sendSecondsLeft(r));
    return `Uploading ${pct}%${left ? ` · ${left}` : ""}`;
  }
  if (r.phase === "reading") return `Reading the file${r.timeLeft ? ` · ${r.timeLeft.toLowerCase()}` : ""}`;
  if (r.phase === "ready") return "Ready";
  return r.error ?? "Couldn't read this file.";
}

function pct(r: UploadRow): number {
  if (r.phase === "uploading") return r.size ? (60 * r.sent) / r.size : 0;    // sending: the first 60%
  if (r.phase === "reading") return 60 + 0.4 * r.jobProgress;                  // reading: the rest
  return r.phase === "ready" ? 100 : 0;
}

export default function UploadPanel({ scope, title }: { scope: string; title: string }) {
  const list = useUploads(scope);
  const here = useLocation().pathname;
  const [unsent] = useState(() => takeUnsent());
  const [showUnsent, setShowUnsent] = useState(unsent.length > 0);
  const [, tick] = useState(0);

  // Keep "time left" moving while bytes are being sent.
  const sending = list.some((r) => r.phase === "uploading");
  useEffect(() => {
    if (!sending) return;
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [sending]);

  if (!list.length && !showUnsent) return null;
  const summary = batchSummary(list);
  const finished = list.some((r) => r.phase === "ready" || r.phase === "failed");

  return (
    <section className="card upload-panel" aria-label={title}>
      {showUnsent && (
        <div className="msg warn">
          <Icon name="warning" size={18} />
          <div className="grow">
            <strong>{unsent.length === 1 ? "One file" : `${unsent.length} files`} did not finish uploading before you left</strong>
            Add {unsent.length === 1 ? "it" : "them"} again: {unsent.join(", ")}.
          </div>
          <button className="ghost" aria-label="Dismiss" onClick={() => setShowUnsent(false)}><Icon name="close" size={16} /></button>
        </div>
      )}
      {list.length > 0 && (
        <>
          <div className="card-head">
            <h2>{title}</h2>
            <span className="muted small" role="status">{summary ?? "All done"}</span>
          </div>
          <ul className="upload-rows">
            {list.map((r) => (
              <li key={r.id} className={`upload-row ${r.phase}`}>
                <div className="upload-name">
                  <strong>{r.name}</strong>
                  <span className="small muted">{formatSize(r.size)}</span>
                </div>
                {r.phase !== "failed" && (
                  <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                    aria-valuenow={Math.round(pct(r))} aria-label={`${r.name}: ${phaseText(r)}`}>
                    <span style={{ width: `${Math.max(r.phase === "waiting" ? 0 : 3, pct(r))}%` }} />
                  </div>
                )}
                <div className="upload-foot">
                  <span className={`small ${r.phase === "failed" ? "err-text" : r.phase === "ready" ? "ok-text" : "muted"}`}>
                    {r.phase === "ready" && <Icon name="check" size={14} />} {phaseText(r)}
                  </span>
                  <span className="row" style={{ gap: 8 }}>
                    {r.phase === "ready" && r.link && r.link !== here && <Link className="link small" to={r.link}>Open</Link>}
                    {r.phase === "failed" && canRetry(r.id) && <button className="link small" onClick={() => retry(r.id)}>Try again</button>}
                    {(r.phase === "failed" || r.phase === "waiting" || r.phase === "ready") && (
                      <button className="link small" onClick={() => remove(r.id)}>Remove</button>
                    )}
                  </span>
                </div>
              </li>
            ))}
          </ul>
          {finished && (
            <button className="link small" onClick={() => clearFinished(scope)}>Clear finished</button>
          )}
          <p className="hint">You can leave this page: files that have finished uploading carry on being read, and show under the clock icon at the top.</p>
        </>
      )}
    </section>
  );
}
