import katex from "katex";
import "katex/dist/katex.min.css";
import { useEffect, useState } from "react";
import { api } from "../api";

const MATH = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;

/** Text with LaTeX between $…$ (inline) or $$…$$ (display), rendered with KaTeX (plan 2.17).
 * Bad LaTeX is shown as source in red rather than hidden. */
export default function MathText({ text }: { text: string | null | undefined }) {
  const s = text ?? "";
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  MATH.lastIndex = 0;
  while ((m = MATH.exec(s))) {
    if (m.index > last) parts.push(s.slice(last, m.index));
    const display = m[1] !== undefined;
    const tex = (m[1] ?? m[2]).trim();
    try {
      parts.push(
        <span key={m.index} dangerouslySetInnerHTML={{ __html: katex.renderToString(tex, { displayMode: display, throwOnError: true }) }} />,
      );
    } catch {
      parts.push(<code key={m.index} style={{ color: "var(--error)" }} title="This LaTeX doesn't render">{m[0]}</code>);
    }
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push(s.slice(last));
  return <>{parts}</>;
}

/** An item's figure (chart from generated data, or rendered diagram), plus its source/data. */
export function FigureView({ itemId, figure }: { itemId: number; figure: any }) {
  const [img, setImg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!figure) return;
    let url: string | null = null;
    setImg(null);
    setFailed(false);
    api.figure(itemId).then((u) => { url = u; setImg(u); }).catch(() => setFailed(true));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [itemId, JSON.stringify(figure)]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!figure) return null;
  return (
    <figure className="item-figure">
      {img && <img src={img} alt={figure.caption || "Item figure"} />}
      {!img && figure.diagram && (
        <>
          {failed && <div className="small muted">Diagram ({figure.diagram.kind}) — no renderer on the server, showing source:</div>}
          <pre className="code-block">{figure.diagram.source}</pre>
        </>
      )}
      {!img && !figure.diagram && !failed && <div className="small muted">Rendering…</div>}
      {figure.caption && <figcaption className="small muted">{figure.caption}</figcaption>}
      {figure.dataset && (
        <div className="small muted">
          Generated data: {figure.dataset.kind}, n = {figure.dataset.n}, seed {figure.dataset.seed ?? 1}.{" "}
          <button className="link small" onClick={() => api.download(`/api/drafts/${itemId}/dataset.csv`, "dataset.csv")}>Download CSV</button>
        </div>
      )}
    </figure>
  );
}
