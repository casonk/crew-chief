"""crew_chief.render — turn rows from the result store into the output a caller asks for.

``render(conn, run_id, chart, fmt, theme)`` answers one request: a chart as SVG, or a table as
CSV, JSON, Markdown or a themed HTML page. Nothing is precomputed or stored per format, so a new
view is one function here. Stdlib only.

An SVG styles itself with the portfolio tokens (``var(--surface)``). Inline in a page it inherits the
page's theme; as a standalone file it carries its own: the requested theme, or the viewer's light or
dark setting when none is named.
"""

from __future__ import annotations

import contextlib
import csv
import html
import io
import json
import math
import re
import sqlite3
from typing import Any

from crew_chief import resultstore, theme, viewer

CHARTS: dict[str, tuple[str, ...]] = {
    "scatter": ("svg",),
    "bars": ("svg",),
    "table": ("csv", "json", "md", "html"),
    "tasks": ("csv", "json", "md", "html"),
}
CONTENT_TYPES = {
    "svg": "image/svg+xml",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}
TOKENS = ("bg", "surface", "border", "text", "muted", "accent", "green", "purple", "yellow", "red")
_BLOCK = re.compile(r':root\[data-theme="([a-z-]+)"\]\s*\{(.*?)\}', re.S)
_DECL = re.compile(r"--([a-z0-9-]+):\s*([^;]+);")


class RenderError(ValueError):
    """A request for something this module cannot draw."""


def theme_tokens() -> dict[str, dict[str, str]]:
    """The tokens of every named theme, read from the vendored portfolio theme."""
    return {
        name: {k: v.strip() for k, v in _DECL.findall(body)}
        for name, body in _BLOCK.findall(theme.CSS)
    }


def _vars(tokens: dict[str, str]) -> str:
    return ";".join(f"--{k}:{tokens[k]}" for k in TOKENS if k in tokens)


def svg_style(name: str | None) -> str:
    """A ``<style>`` for a standalone SVG: the named theme, or light/dark following the viewer."""
    themes = theme_tokens()
    if name:
        if name not in themes:
            raise RenderError(f"unknown theme {name!r}; use one of {', '.join(sorted(themes))}")
        return f"<style>svg{{{_vars(themes[name])}}}</style>"
    dark, light = themes.get("midnight", {}), themes.get("daylight", {})
    return (
        f"<style>svg{{{_vars(dark)}}}"
        f"@media (prefers-color-scheme: light){{svg{{{_vars(light)}}}}}</style>"
    )


def pareto(rows: list[dict[str, Any]]) -> set[str]:
    """Performers no other performer matches on both accuracy and speed while beating on one."""
    front = set()
    for r in rows:
        dominated = any(
            o is not r
            and o["accuracy"] >= r["accuracy"]
            and o["ms_mean"] <= r["ms_mean"]
            and (o["accuracy"] > r["accuracy"] or o["ms_mean"] < r["ms_mean"])
            for o in rows
        )
        if not dominated:
            front.add(r["performer"])
    return front


def nudge_label(placed: list[tuple[float, float, float]], x0: float, x1: float, y: float) -> float:
    """The y for a label spanning x0..x1 that does not overprint one already placed.

    ``placed`` holds (x0, x1, y) of the labels drawn so far and is added to. The label keeps its
    own y if it can, else moves up or down in 12 px steps.
    """
    for nudge in (0, -12, 12, -24, 24, -36, 36):
        if not any(x0 < b1 and x1 > b0 and abs(y + nudge - by) < 12 for b0, b1, by in placed):
            y += nudge
            break
    placed.append((x0, x1, y))
    return y


def _svg_open(width: int, height: int, standalone: bool, name: str | None) -> list[str]:
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'font-family="sans-serif" font-size="11" fill="currentColor" role="img" '
        'style="color:var(--text,#e2e4f0)">'
    )
    out = [head]
    if standalone:
        out.append(svg_style(name))
    out.append(f'<rect width="{width}" height="{height}" style="fill:var(--surface,#1a1d27)"/>')
    return out


def scatter_svg(
    rows: list[dict[str, Any]], standalone: bool = True, name: str | None = None
) -> str:
    """Accuracy (y) against mean latency per item (x, log scale), one dot per performer."""
    rows = [r for r in rows if r["accuracy"] is not None and r["ms_mean"] is not None]
    if not rows:
        raise RenderError("no accuracy and latency to plot in this run")
    width, height, left, right, top, bottom = 760, 420, 56, 170, 20, 48
    xs = [max(r["ms_mean"], 1.0) for r in rows]
    ys = [r["accuracy"] for r in rows]
    lo, hi = math.log10(min(xs) * 0.8), math.log10(max(xs) * 1.25)
    if hi - lo < 0.3:
        lo, hi = lo - 0.15, hi + 0.15
    y_lo = max(0.0, math.floor((min(ys) - 0.05) * 20) / 20)
    front = pareto(rows)

    def px(ms: float) -> float:
        return left + (math.log10(max(ms, 1.0)) - lo) / (hi - lo) * (width - left - right)

    def py(acc: float) -> float:
        return top + (1 - (acc - y_lo) / (1 - y_lo)) * (height - top - bottom)

    out = _svg_open(width, height, standalone, name)
    out.append(
        f'<rect x="{left}" y="{top}" width="{width - left - right}" height="{height - top - bottom}" '
        'fill="none" style="stroke:var(--border,#2e3250)"/>'
    )
    out.append(
        f'<text x="{left + (width - left - right) / 2}" y="{height - 10}" text-anchor="middle">'
        "mean ms per item (log scale; lower is faster)</text>"
    )
    mid = top + (height - top - bottom) / 2
    out.append(
        f'<text x="14" y="{mid}" text-anchor="middle" transform="rotate(-90 14 {mid})">'
        "accuracy (higher is better)</text>"
    )
    for k in range(round((1 - y_lo) / 0.05) + 1):
        acc = y_lo + k * 0.05
        out.append(f'<text x="{left - 6}" y="{py(acc) + 4:.1f}" text-anchor="end">{acc:.2f}</text>')
        out.append(
            f'<line x1="{left}" x2="{width - right}" y1="{py(acc):.1f}" y2="{py(acc):.1f}" '
            'style="stroke:var(--border,#2e3250);stroke-opacity:0.5"/>'
        )
    for tick in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
        if lo <= math.log10(tick) <= hi:
            out.append(
                f'<text x="{px(tick):.1f}" y="{height - bottom + 16}" text-anchor="middle">{tick}</text>'
            )
    placed: list[tuple[float, float, float]] = []  # label boxes already drawn: (x0, x1, y)
    for r in sorted(rows, key=lambda r: r["ms_mean"]):
        x, y, on_front = px(r["ms_mean"]), py(r["accuracy"]), r["performer"] in front
        colour = "var(--accent,#5b7fff)" if on_front else "var(--muted,#8890b0)"
        fill = colour if on_front else "none"
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if on_front else 4}" '
            f'style="fill:{fill};stroke:{colour}" stroke-width="1.5">'
            f"<title>{html.escape(r['performer'])}: {r['accuracy']:.3f} accuracy, "
            f"{r['ms_mean']:.0f} ms</title></circle>"
        )
        x0, x1 = x + 8, x + 8 + 6.2 * len(r["performer"])
        label_y = nudge_label(placed, x0, x1, y + 4)
        out.append(f'<text x="{x0:.1f}" y="{label_y:.1f}">{html.escape(r["performer"])}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def bars_svg(rows: list[dict[str, Any]], standalone: bool = True, name: str | None = None) -> str:
    """Accuracy per performer as horizontal bars, with the mean latency beside each."""
    rows = [r for r in rows if r["accuracy"] is not None]
    if not rows:
        raise RenderError("no accuracy to plot in this run")
    row_h, left, right, top = 26, 190, 90, 16
    width, height = 760, top + row_h * len(rows) + 28
    span = width - left - right
    out = _svg_open(width, height, standalone, name)
    for k in range(0, 11, 2):
        x = left + span * k / 10
        out.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{height - 28}" '
            'style="stroke:var(--border,#2e3250);stroke-opacity:0.6"/>'
        )
        out.append(f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle">{k / 10:.1f}</text>')
    for i, r in enumerate(rows):
        y = top + i * row_h
        w = span * max(0.0, min(1.0, r["accuracy"]))
        out.append(
            f'<text x="{left - 8}" y="{y + 16}" text-anchor="end">{html.escape(r["performer"])}</text>'
        )
        out.append(
            f'<rect x="{left}" y="{y + 3}" width="{w:.1f}" height="{row_h - 8}" rx="3" '
            'style="fill:var(--accent,#5b7fff)"/>'
        )
        ms = r["ms_mean"]
        label = f"{r['accuracy']:.3f}" + (f" · {ms:.0f} ms" if ms is not None else "")
        out.append(f'<text x="{left + w + 6:.1f}" y="{y + 16}">{label}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# -- tables ------------------------------------------------------------------

_COLUMNS = {
    "table": ["performer", "n", "accuracy", "macro_f1", "ms_mean", "ms_median", "ms_p90"],
    "tasks": ["task", "performer", "n", "accuracy", "macro_f1", "ms_mean"],
}


def _cell(value: Any, column: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.1f}" if column.startswith("ms_") else f"{value:.3f}"
    return str(value)


def _table(rows: list[dict[str, Any]], columns: list[str], fmt: str) -> str:
    if fmt == "json":
        return json.dumps([{c: r.get(c) for c in columns} for r in rows], indent=2) + "\n"
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([[_cell(r.get(c), c) for c in columns] for r in rows])
        return buf.getvalue()
    if fmt == "md":
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        lines += [
            "| " + " | ".join(_cell(r.get(c), c).replace("|", "\\|") for c in columns) + " |"
            for r in rows
        ]
        return "\n".join(lines) + "\n"
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_cell(r.get(c), c))}</td>" for c in columns) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# The view tab each rendering belongs to (see ``BenchApp.view_items``); the others mark no tab.
VIEW_KEYS = {
    ("table", "html"): "html",
    ("table", "md"): "md",
    ("scatter", "svg"): "svg",
    ("bars", "svg"): "bars",
    ("table", "csv"): "csv",
}


def _page(conn: sqlite3.Connection, run_id: int, name: str, source: str, extra: str = "") -> str:
    """The run as one themed page: both charts inline, then the tables."""
    perf = resultstore.performers(conn, run_id)
    parts: list[str] = []
    for chart in (scatter_svg, bars_svg):
        with contextlib.suppress(RenderError):  # a run with no latency has no scatter
            parts.append(chart(perf, standalone=False))
    parts.append("<h2>Performers</h2>" + _table(perf, _COLUMNS["table"], "html"))
    by_task = resultstore.tasks(conn, run_id)
    if by_task:
        parts.append("<h2>By task</h2>" + _table(by_task, _COLUMNS["tasks"], "html"))
    return viewer.page(
        name, f'<div class="doc">{"".join(parts)}</div>', f"/files/results/{source}", extra
    )


def render(
    conn: sqlite3.Connection,
    run_id: int,
    chart: str,
    fmt: str,
    theme_name: str | None = None,
    extra: str = "",
) -> tuple[bytes, str]:
    """The requested rendering of one run and its content type."""
    if chart not in CHARTS or fmt not in CHARTS[chart]:
        offered = ", ".join(f"{c}.{f}" for c, fs in CHARTS.items() for f in fs)
        raise RenderError(f"cannot render {chart}.{fmt}; available: {offered}")
    run = conn.execute("SELECT source FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise RenderError(f"no run {run_id}")
    perf = resultstore.performers(conn, run_id)
    if fmt == "svg":
        draw = scatter_svg if chart == "scatter" else bars_svg
        return draw(perf, True, theme_name).encode(), CONTENT_TYPES["svg"]
    rows = perf if chart == "table" else resultstore.tasks(conn, run_id)
    if fmt == "html":
        page = _page(conn, run_id, run["source"], run["source"], extra)
        return page.encode(), CONTENT_TYPES["html"]
    return _table(rows, _COLUMNS[chart], fmt).encode(), CONTENT_TYPES[fmt]
