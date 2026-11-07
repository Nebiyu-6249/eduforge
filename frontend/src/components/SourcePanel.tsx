import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api";
import type { SourceRef, SyllabusRecord } from "../types";
import { ptrLabel } from "./util";

/** Lets any field ask the Version page to show where it came from. */
export const SourceContext = createContext<(ptr: string) => void>(() => {});
export const useShowSource = () => useContext(SourceContext);

/** Nearest recorded source for a pointer: '/weekly/4/assessments/0' -> '/weekly/4'. */
export function sourceFor(rec: SyllabusRecord, ptr: string): [string, SourceRef] | null {
  let p = ptr;
  while (p) {
    const ref = rec.sources?.[p];
    if (ref) return [p, ref];
    p = p.slice(0, p.lastIndexOf("/"));
  }
  return null;
}

/** The record beside its source (plan 1.11): page/table/row, the original
 * text and, for PDFs, the page image. */
export default function SourcePanel({ cvId, rec, ptr, isPdf, onClose }: {
  cvId: number; rec: SyllabusRecord; ptr: string; isPdf: boolean; onClose: () => void;
}) {
  const hit = sourceFor(rec, ptr);
  const page = hit?.[1].page ?? null;
  const [img, setImg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setImg(null);
    setErr(null);
    if (!isPdf || page == null) return;
    let url: string | null = null;
    api.pageImage(cvId, page).then((u) => { url = u; setImg(u); }).catch((e) => setErr(e.message));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [cvId, page, isPdf]);

  return (
    <div className="card source-panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>Source · {ptrLabel(ptr)}</h3>
        <button className="icon" onClick={onClose} aria-label="Close source panel">✕</button>
      </div>
      {!hit ? (
        <p className="small muted">No location recorded for this value (it may have been typed in, or transcribed by the model).</p>
      ) : (
        <>
          <p className="small muted" style={{ margin: "4px 0" }}>
            {[page != null && `Page ${page}`, hit[1].table != null && `table ${hit[1].table}`, hit[1].row != null && `row ${hit[1].row}`]
              .filter(Boolean).join(", ") || "Location"}
            {hit[0] !== ptr && ` (nearest: ${ptrLabel(hit[0])})`}
          </p>
          {hit[1].raw_text && <blockquote className="raw">{hit[1].raw_text}</blockquote>}
          {isPdf && page != null && (img
            ? <img src={img} alt={`Page ${page} of the uploaded syllabus`} className="page-img" />
            : <p className="small muted">{err ?? "Loading page…"}</p>)}
        </>
      )}
    </div>
  );
}
