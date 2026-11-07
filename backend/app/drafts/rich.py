"""Math, diagrams, datasets and charts inside items (plan 2.17, 2.18, 2.20).

* Math: LaTeX between $…$ (inline) or $$…$$ (display) in any text field. The UI
  renders it with KaTeX; exports use matplotlib's mathtext, which also serves as
  the syntax check.
* Diagrams: Graphviz / Mermaid / PlantUML source, compiled with the installed
  tool (`dot`, `mmdc`, PlantUML via java + PLANTUML_JAR or a `plantuml` command).
  "Source must compile or the item fails its quality check"; when no renderer is
  installed the check is reported as skipped, never faked.
* Datasets: generated in code with numpy from a seed, so their properties are
  known exactly; charts are drawn from that data with matplotlib, never by the
  model. Summary statistics feed the recomputed answer keys.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import mathtext

_MATH = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)


# --------------------------------------------------------------------------- #
# Math (2.17)
# --------------------------------------------------------------------------- #

def math_segments(text: str) -> list[str]:
    return [a or b for a, b in _MATH.findall(text or "")]


@lru_cache(maxsize=512)
def render_math(latex: str, fontsize: int = 12) -> bytes:
    """PNG of one LaTeX expression. Raises ValueError if it doesn't parse."""
    buf = io.BytesIO()
    try:
        mathtext.math_to_image(f"${latex}$", buf, dpi=200, format="png",
                               prop=matplotlib.font_manager.FontProperties(size=fontsize))
    except Exception as e:
        msg = str(e).strip().split("\n")[0] or f"{type(e).__name__} (unbalanced braces or an unknown command?)"
        raise ValueError(msg) from e
    return buf.getvalue()


def split_math(text: str) -> list[tuple[str, str]]:
    """'Area is $\\pi r^2$.' -> [('text', 'Area is '), ('math', '\\pi r^2'), ('text', '.')]"""
    out, pos = [], 0
    for m in _MATH.finditer(text or ""):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        out.append(("math", m.group(1) or m.group(2)))
        pos = m.end()
    if pos < len(text or ""):
        out.append(("text", text[pos:]))
    return out


# --------------------------------------------------------------------------- #
# Diagrams (2.18)
# --------------------------------------------------------------------------- #

def diagram_renderer(kind: str) -> list[str] | None:
    """Command that turns diagram source on stdin into PNG on stdout, or None."""
    if kind == "graphviz" and shutil.which("dot"):
        return ["dot", "-Tpng"]
    if kind == "plantuml":
        if shutil.which("plantuml"):
            return ["plantuml", "-tpng", "-pipe"]
        jar = os.environ.get("PLANTUML_JAR")
        if jar and Path(jar).exists() and shutil.which("java"):
            return ["java", "-jar", jar, "-tpng", "-pipe"]
    return None


@dataclass
class RenderResult:
    png: bytes | None
    error: str | None = None
    available: bool = True


def render_diagram(kind: str, source: str, timeout: int = 20) -> RenderResult:
    if kind == "mermaid":
        return _render_mermaid(source, timeout)
    cmd = diagram_renderer(kind)
    if cmd is None:
        return RenderResult(None, f"No {kind} renderer installed on the server.", available=False)
    try:
        p = subprocess.run(cmd, input=source.encode(), capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return RenderResult(None, f"{kind} took longer than {timeout}s.")
    if p.returncode != 0 or not p.stdout.startswith(b"\x89PNG"):
        err = (p.stderr or p.stdout).decode(errors="replace").strip().splitlines()
        return RenderResult(None, (err[0] if err else f"{kind} failed")[:300])
    return RenderResult(p.stdout)


def _render_mermaid(source: str, timeout: int) -> RenderResult:
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return RenderResult(None, "No mermaid renderer (mmdc) installed on the server.", available=False)
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "d.mmd", Path(d) / "d.png"
        src.write_text(source, encoding="utf-8")
        try:
            p = subprocess.run([mmdc, "-i", str(src), "-o", str(out)], capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return RenderResult(None, f"mermaid took longer than {timeout}s.")
        if p.returncode != 0 or not out.exists():
            return RenderResult(None, (p.stderr.decode(errors="replace").strip() or "mermaid failed")[:300])
        return RenderResult(out.read_bytes())


# --------------------------------------------------------------------------- #
# Datasets and charts (2.20)
# --------------------------------------------------------------------------- #

class DatasetError(ValueError):
    pass


def _num(params: dict, key: str, default: float) -> float:
    v = params.get(key, default)
    if not isinstance(v, (int, float)):
        raise DatasetError(f"'{key}' must be a number.")
    return float(v)


def generate(spec: dict) -> dict:
    """{'columns': [...], 'rows': [[...]], 'summary': {...}} from a DatasetSpec dict."""
    kind, n, params = spec["kind"], int(spec["n"]), spec.get("params") or {}
    rng = np.random.default_rng(int(spec.get("seed", 1)))
    if kind == "linear":
        lo, hi = _num(params, "x_min", 0), _num(params, "x_max", 10)
        if hi <= lo:
            raise DatasetError("x_max must be greater than x_min.")
        x = np.round(rng.uniform(lo, hi, n), 2)
        y = np.round(_num(params, "intercept", 0) + _num(params, "slope", 1) * x
                     + rng.normal(0, _num(params, "noise_sd", 1), n), 2)
        b, a = np.polyfit(x, y, 1)
        r = float(np.corrcoef(x, y)[0, 1])
        summary = {"n": n, "mean_x": float(x.mean()), "mean_y": float(y.mean()), "sd_x": float(x.std(ddof=1)),
                   "sd_y": float(y.std(ddof=1)), "slope": float(b), "intercept": float(a), "r": r, "r2": r * r}
        return {"columns": ["x", "y"], "rows": [[float(p), float(q)] for p, q in zip(x, y)], "summary": summary}
    if kind == "normal":
        sd = _num(params, "sd", 1)
        if sd <= 0:
            raise DatasetError("sd must be positive.")
        v = np.round(rng.normal(_num(params, "mean", 0), sd, n), 2)
        q1, med, q3 = np.percentile(v, [25, 50, 75])
        summary = {"n": n, "mean": float(v.mean()), "sd": float(v.std(ddof=1)), "median": float(med),
                   "q1": float(q1), "q3": float(q3), "min": float(v.min()), "max": float(v.max())}
        return {"columns": ["value"], "rows": [[float(t)] for t in v], "summary": summary}
    if kind == "binomial":
        trials, p = int(_num(params, "trials", 10)), _num(params, "p", 0.5)
        if not (0 <= p <= 1) or trials < 1:
            raise DatasetError("Need trials ≥ 1 and 0 ≤ p ≤ 1.")
        successes = rng.binomial(trials, p, n)
        summary = {"n": n, "trials": trials, "p": p, "mean": float(successes.mean()), "sd": float(successes.std(ddof=1))}
        return {"columns": ["successes"], "rows": [[int(t)] for t in successes], "summary": summary}
    if kind == "categorical":
        cats = params.get("categories")
        probs = params.get("probs")
        if not isinstance(cats, list) or not cats:
            raise DatasetError("categorical needs a 'categories' list.")
        pr = np.array(probs if isinstance(probs, list) and len(probs) == len(cats) else [1] * len(cats), dtype=float)
        if (pr < 0).any() or pr.sum() == 0:
            raise DatasetError("probs must be non-negative and not all zero.")
        draws = rng.choice(len(cats), size=n, p=pr / pr.sum())
        counts = {str(c): int((draws == i).sum()) for i, c in enumerate(cats)}
        return {"columns": ["category"], "rows": [[str(cats[i])] for i in draws],
                "summary": {"n": n, **{f"count_{k}": v for k, v in counts.items()}}}
    raise DatasetError(f"Unknown dataset kind '{kind}'.")


def render_chart(chart: dict, data: dict, title_fallback: str = "") -> bytes:
    cols, rows = data["columns"], data["rows"]
    fig, ax = plt.subplots(figsize=(5.2, 3.4), dpi=150)
    try:
        t = chart["type"]
        if t in {"scatter", "line"} and len(cols) == 2:
            xs, ys = [r[0] for r in rows], [r[1] for r in rows]
            if t == "line":
                order = np.argsort(xs)
                ax.plot(np.array(xs)[order], np.array(ys)[order])
            else:
                ax.scatter(xs, ys, s=14)
        elif t == "histogram":
            ax.hist([r[0] for r in rows], bins="auto", edgecolor="white")
        elif t == "box":
            ax.boxplot([r[-1] for r in rows], vert=False)
        elif t == "bar":
            counts: dict = {}
            for r in rows:
                counts[r[0]] = counts.get(r[0], 0) + 1
            ax.bar([str(k) for k in counts], list(counts.values()))
        else:
            raise DatasetError(f"A {t} chart doesn't fit a dataset with columns {cols}.")
        ax.set_title(chart.get("title") or title_fallback, fontsize=10)
        ax.set_xlabel(chart.get("x_label") or "")
        ax.set_ylabel(chart.get("y_label") or "")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)


def figure_png(figure: dict | None) -> bytes | None:
    """The image for an item's figure: its chart if it has one, else its diagram."""
    if not figure:
        return None
    if figure.get("dataset") and figure.get("chart"):
        return render_chart(figure["chart"], generate(figure["dataset"]), figure.get("caption", ""))
    if figure.get("diagram"):
        return render_diagram(figure["diagram"]["kind"], figure["diagram"]["source"]).png
    return None


def dataset_csv(figure: dict | None) -> str | None:
    if not figure or not figure.get("dataset"):
        return None
    data = generate(figure["dataset"])
    lines = [",".join(data["columns"])] + [",".join(str(v) for v in r) for r in data["rows"]]
    return "\n".join(lines) + "\n"
