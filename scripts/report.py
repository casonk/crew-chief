#!/usr/bin/env python3
"""
Generate an HTML benchmark report from one or more bench-*.json result files.

Usage
-----
    # Single run
    python3 scripts/report.py results/bench-20260617.json

    # Multiple runs (adds trend section)
    python3 scripts/report.py results/bench-*.json

    # Explicit output path
    python3 scripts/report.py results/bench-20260617.json --out results/bench-20260617.html
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from crew_chief import theme  # noqa: E402

# Models known to use Ollama thinking mode (long internal reasoning before first token)
THINKING_MODELS: set[str] = {
    "qwen3:14b",
    "qwen3:14b-q8_0",
    "qwen3:32b",
    "qwen3.5:27b",
}

PROMPT_ORDER = ["latency", "reasoning", "codegen", "summarise"]
TIER_COLORS = {
    "thinking": "var(--red)",
    "fast": "var(--green)",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_results(paths: list[pathlib.Path]) -> dict[str, list[dict]]:
    """Return {date_label: [result_dicts]} sorted by date ascending."""
    runs: dict[str, list[dict]] = {}
    for p in sorted(paths):
        label = p.stem  # e.g. "bench-20260617"
        try:
            data = json.loads(p.read_text())
            runs[label] = data
        except Exception as exc:
            print(f"Warning: could not load {p}: {exc}", file=sys.stderr)
    return runs


def pivot(results: list[dict]) -> dict[str, dict[str, dict]]:
    """Return {model: {prompt: result_dict}}."""
    table: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in results:
        table[r["model"]][r["prompt_name"]] = r
    return dict(table)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

CSS = """
* { margin: 0; padding: 0; }
h2 { font-size: 1.15rem; margin: 2rem 0 0.75rem; color: var(--text); border-bottom: 2px solid var(--border); padding-bottom: 0.3rem; }
h3 { font-size: 0.95rem; margin: 1.25rem 0 0.4rem; color: var(--muted); }
p.meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.2rem; }
.badge {
  display: inline-block; padding: 0.2rem 0.55rem; border-radius: 12px;
  font-size: 0.75rem; margin: 0 0.2rem;
}
.badge-hw   { background: var(--accent-dim); color: var(--accent); }
.badge-date { background: var(--surface2); color: var(--muted); }
.badge-warn { background: var(--yellow-dim); color: var(--yellow); }

/* ── Tables ── */
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; margin-bottom: 1rem; }
.table-scroll { max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.table-scroll table { min-width: 560px; }
th, td { padding: 0.4rem 0.6rem; border: 1px solid var(--border); text-align: right; }
th { background: var(--surface2); font-weight: 600; }
td.model-name { text-align: left; font-family: ui-monospace, "Fira Code", monospace; white-space: nowrap; }
td.tier-label { font-size: 0.7rem; color: var(--muted); text-align: left; }

/* throughput colour bands */
.tps-vhigh { background: var(--green-dim); color: var(--green); }
.tps-high  { background: color-mix(in srgb, var(--green-dim) 45%, var(--surface)); }
.tps-mid   { background: color-mix(in srgb, var(--yellow-dim) 45%, var(--surface)); }
.tps-low   { background: color-mix(in srgb, var(--red-dim) 60%, var(--surface)); }
.tps-err   { background: var(--red-dim); color: var(--red); font-style: italic; }

/* TTFT colour bands */
.ttft-fast  { background: var(--green-dim); color: var(--green); }
.ttft-ok    { background: color-mix(in srgb, var(--yellow-dim) 45%, var(--surface)); }
.ttft-slow  { background: color-mix(in srgb, var(--red-dim) 60%, var(--surface)); }

/* ── Bar charts ── */
.chart { margin: 0.5rem 0 1.5rem; }
.bar-row { display: flex; align-items: center; margin: 3px 0; gap: 8px; }
.bar-model { width: 220px; font-family: ui-monospace, "Fira Code", monospace; font-size: 0.78rem;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; min-width: 0; background: var(--surface2); border-radius: 3px; height: 18px; position: relative; }
.bar-fill  { height: 100%; border-radius: 3px; min-width: 2px;
             display: flex; align-items: center; padding-left: 5px; }
.bar-fill span { color: var(--accent-ink); font-size: 0.72rem; white-space: nowrap; }
.bar-val   { width: 70px; font-size: 0.78rem; color: var(--muted); text-align: right; }

/* ── Trend ── */
.trend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1rem; }
.trend-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 1rem; }
.trend-card h4 { font-size: 0.85rem; margin-bottom: 0.5rem; font-family: ui-monospace, "Fira Code", monospace; }

/* ── Section spacing ── */
.section { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
           padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; }

@media (max-width: 640px) {
  body { padding: 1rem 0.75rem; }
  h1 { font-size: 1.35rem; }
  .section { min-width: 0; padding: 1rem 0.75rem; }
  .bar-row { gap: 6px; min-width: 0; }
  .bar-model { width: min(38vw, 140px); flex: 0 0 min(38vw, 140px); font-size: 0.68rem; }
  .bar-val { width: 52px; flex: 0 0 52px; font-size: 0.68rem; }
  .bar-fill span { font-size: 0.62rem; }
  .trend-grid { grid-template-columns: minmax(0, 1fr); }
  .trend-card { min-width: 0; padding: 0.75rem; }
}
"""


def _tps_class(tps: float) -> str:
    if tps >= 200:
        return "tps-vhigh"
    if tps >= 100:
        return "tps-high"
    if tps >= 30:
        return "tps-mid"
    return "tps-low"


def _ttft_class(ms: float) -> str:
    if ms < 500:
        return "ttft-fast"
    if ms < 10_000:
        return "ttft-ok"
    return "ttft-slow"


def _fmt_ttft(ms: float) -> str:
    if ms >= 60_000:
        return f"{ms / 60_000:.1f} min"
    if ms >= 1_000:
        return f"{ms / 1_000:.1f} s"
    return f"{ms:.0f} ms"


def _bar_color(model: str) -> str:
    return "var(--red)" if model in THINKING_MODELS else "var(--accent)"


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------


def _throughput_table(models: list[str], pt: dict[str, dict[str, dict]], prompts: list[str]) -> str:
    rows = ['<div class="table-scroll"><table>', "<thead><tr>"]
    rows.append("<th>Model</th><th>Tier</th>")
    for p in prompts:
        rows.append(f"<th>{p}</th>")
    rows.append("</tr></thead><tbody>")
    for model in models:
        tier = "thinking" if model in THINKING_MODELS else "fast"
        rows.append("<tr>")
        rows.append(f'<td class="model-name">{model}</td>')
        rows.append(f'<td class="tier-label">{tier}</td>')
        for p in prompts:
            r = pt.get(model, {}).get(p)
            if r is None:
                rows.append("<td>—</td>")
            elif r.get("error"):
                rows.append('<td class="tps-err">error</td>')
            else:
                tps = r["tokens_per_sec"]
                rows.append(f'<td class="{_tps_class(tps)}">{tps:.1f}</td>')
        rows.append("</tr>")
    rows.append("</tbody></table></div>")
    return "\n".join(rows)


def _ttft_table(models: list[str], pt: dict[str, dict[str, dict]], prompts: list[str]) -> str:
    rows = ['<div class="table-scroll"><table>', "<thead><tr>"]
    rows.append("<th>Model</th><th>Tier</th>")
    for p in prompts:
        rows.append(f"<th>{p}</th>")
    rows.append("</tr></thead><tbody>")
    for model in models:
        tier = "thinking" if model in THINKING_MODELS else "fast"
        rows.append("<tr>")
        rows.append(f'<td class="model-name">{model}</td>')
        rows.append(f'<td class="tier-label">{tier}</td>')
        for p in prompts:
            r = pt.get(model, {}).get(p)
            if r is None:
                rows.append("<td>—</td>")
            elif r.get("error"):
                rows.append('<td class="tps-err">error</td>')
            else:
                ms = r["ttft_ms"]
                rows.append(f'<td class="{_ttft_class(ms)}">{_fmt_ttft(ms)}</td>')
        rows.append("</tr>")
    rows.append("</tbody></table></div>")
    return "\n".join(rows)


def _bar_chart(models: list[str], pt: dict[str, dict[str, dict]], prompt: str) -> str:
    values = []
    for model in models:
        r = pt.get(model, {}).get(prompt)
        if r and not r.get("error"):
            values.append((model, r["tokens_per_sec"]))
    if not values:
        return "<p>No data.</p>"
    max_val = max(v for _, v in values) or 1
    rows = ['<div class="chart">']
    for model, tps in sorted(values, key=lambda x: -x[1]):
        pct = max(2, int(tps / max_val * 100))
        color = _bar_color(model)
        label = f"{tps:.0f} tok/s"
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-model" title="{model}">{model}</div>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%;background:{color}">'
            f"{'<span>' + label + '</span>' if pct >= 14 else ''}</div></div>"
            f'<div class="bar-val">{tps:.1f}</div>'
            f"</div>"
        )
    rows.append("</div>")
    return "\n".join(rows)


def _ttft_bar_chart(
    models: list[str], pt: dict[str, dict[str, dict]], prompt: str, log: bool = True
) -> str:
    """TTFT bars (ms) on a log or a linear scale, fastest first."""
    values = []
    for model in models:
        r = pt.get(model, {}).get(prompt)
        if r and not r.get("error"):
            values.append((model, r["ttft_ms"]))
    if not values:
        return "<p>No data.</p>"
    top = max(v for _, v in values)
    max_scaled = (math.log10(top + 1) if log else top) or 1
    rows = ['<div class="chart">']
    for model, ms in sorted(values, key=lambda x: x[1]):
        pct = max(2, int((math.log10(ms + 1) if log else ms) / max_scaled * 100))
        color = _bar_color(model)
        label = _fmt_ttft(ms)
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-model" title="{model}">{model}</div>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%;background:{color}">'
            f"{'<span>' + label + '</span>' if pct >= 14 else ''}</div></div>"
            f'<div class="bar-val">{label}</div>'
            f"</div>"
        )
    rows.append("</div>")
    return "\n".join(rows)


CHART_VIEWS = (
    ("tps", "Throughput, tokens / second"),
    ("ttft-log", "Time to first token, log scale"),
    ("ttft-lin", "Time to first token, linear scale"),
)

# Without JavaScript every view shows; with it only the selected one does.
CHART_CSS = """
.chart-controls { margin: 0.5rem 0 0.25rem; display: flex; gap: 0.5rem; align-items: center; }
.js .charts .chart-view { display: none; }
.js .charts[data-view="tps"] .chart-view[data-view="tps"],
.js .charts[data-view="ttft-log"] .chart-view[data-view="ttft-log"],
.js .charts[data-view="ttft-lin"] .chart-view[data-view="ttft-lin"] { display: block; }
.chart-view > p.meta { margin: 0 0 0.3rem; }
"""

CHART_JS = """<script>
(function () {
  var box = document.querySelector(".charts"), pick = document.getElementById("chart-view");
  if (!box || !pick) return;
  var KEY = "bench-chart-view", views = Array.prototype.map.call(pick.options, function (o) { return o.value; });
  document.documentElement.classList.add("js");
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  function show(view) { box.setAttribute("data-view", view); pick.value = view; }
  show(views.indexOf(saved) >= 0 ? saved : views[0]);
  pick.addEventListener("change", function () {
    show(pick.value);
    try { localStorage.setItem(KEY, pick.value); } catch (e) {}
  });
})();
</script>"""


def _chart_section(models: list[str], pt: dict[str, dict[str, dict]], prompts: list[str]) -> str:
    """One chart per prompt, with a scale selector choosing what every chart shows."""
    options = "".join(f'<option value="{key}">{label}</option>' for key, label in CHART_VIEWS)
    parts = [
        f'<div class="section charts" data-view="{CHART_VIEWS[0][0]}"><h2>Charts</h2>',
        '<div class="chart-controls"><label for="chart-view">Show</label>'
        f'<select id="chart-view" class="theme-switch">{options}</select></div>',
    ]
    for prompt in prompts:
        parts.append(f"<h3>{prompt}</h3>")
        for key, label in CHART_VIEWS:
            chart = (
                _bar_chart(models, pt, prompt)
                if key == "tps"
                else _ttft_bar_chart(models, pt, prompt, log=key == "ttft-log")
            )
            parts.append(
                f'<div class="chart-view" data-view="{key}"><p class="meta">{label}</p>{chart}</div>'
            )
    parts.append("</div>" + CHART_JS)
    return "\n".join(parts)


def _trend_section(runs: dict[str, list[dict]], models: list[str]) -> str:
    """Compare tok/s on reasoning across multiple dated runs."""
    labels = list(runs.keys())
    if len(labels) < 2:
        return ""
    cards = []
    for model in models:
        points = []
        for label, results in runs.items():
            for r in results:
                if r["model"] == model and r["prompt_name"] == "reasoning" and not r.get("error"):
                    points.append((label, r["tokens_per_sec"]))
        if len(points) < 2:
            continue
        rows = [f'<div class="trend-card"><h4>{model}</h4>']
        max_tps = max(v for _, v in points) or 1
        for label, tps in points:
            pct = max(2, int(tps / max_tps * 100))
            color = _bar_color(model)
            rows.append(
                f'<div class="bar-row">'
                f'<div class="bar-model">{label}</div>'
                f'<div class="bar-track">'
                f'<div class="bar-fill" style="width:{pct}%;background:{color}">'
                f"<span>{tps:.0f}</span></div></div>"
                f'<div class="bar-val">{tps:.1f}</div>'
                f"</div>"
            )
        rows.append("</div>")
        cards.append("\n".join(rows))
    if not cards:
        return ""
    return (
        '<div class="section">'
        "<h2>Trend — Reasoning tok/s across runs</h2>"
        '<div class="trend-grid">' + "".join(cards) + "</div>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------


def build_report(runs: dict[str, list[dict]], out: pathlib.Path) -> None:
    latest_label = list(runs.keys())[-1]
    latest = runs[latest_label]
    pt = pivot(latest)

    # Model order: non-thinking fast→slow, then thinking fast→slow
    all_models = list(pt.keys())
    non_thinking = sorted(
        [m for m in all_models if m not in THINKING_MODELS],
        key=lambda m: -(pt[m].get("reasoning", {}).get("tokens_per_sec") or 0),
    )
    thinking = sorted(
        [m for m in all_models if m in THINKING_MODELS],
        key=lambda m: -(pt[m].get("reasoning", {}).get("tokens_per_sec") or 0),
    )
    models = non_thinking + thinking

    prompts = [p for p in PROMPT_ORDER if any(p in pt[m] for m in models)]

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_models = len(models)
    n_prompts = len(prompts)

    sections = []

    # ── Throughput table
    sections.append(
        '<div class="section">'
        "<h2>Throughput — tokens / second</h2>"
        "<p>Higher is faster. Colour bands: "
        '<span class="badge tps-vhigh">≥200</span> '
        '<span class="badge tps-high">≥100</span> '
        '<span class="badge tps-mid">≥30</span> '
        '<span class="badge tps-low">&lt;30</span></p>'
        + _throughput_table(models, pt, prompts)
        + "</div>"
    )

    # ── TTFT table
    sections.append(
        '<div class="section">'
        "<h2>Time to First Token (TTFT)</h2>"
        "<p>For thinking models this includes internal reasoning before the first visible token. "
        "Colour bands: "
        '<span class="badge ttft-fast">&lt;500 ms</span> '
        '<span class="badge ttft-ok">&lt;10 s</span> '
        '<span class="badge ttft-slow">≥10 s</span></p>'
        + _ttft_table(models, pt, prompts)
        + "</div>"
    )

    # ── Bar charts: one per prompt, the scale chosen by a selector
    sections.append(_chart_section(models, pt, prompts))

    # ── Trend (if multiple runs)
    trend = _trend_section(runs, models)
    if trend:
        sections.append(trend)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>crew-chief Benchmark — {latest_label}</title>
{theme.HEAD}<style>{theme.SWITCHER_CSS}{theme.REPORT_CSS}{CSS}{CHART_CSS}</style>
</head>
<body>
<div class="page">
{theme.report_nav("speed")}
<h1>crew-chief Model Benchmark</h1>
<p class="meta">
  <span class="badge badge-date">{date_str}</span>
  <span class="badge badge-hw">RTX 3090 24 GB</span>
  <span class="badge badge-hw">Ollama / Podman</span>
  <span class="badge badge-date">{n_models} models &middot; {n_prompts} prompts</span>
  <span class="badge badge-warn">thinking models: TTFT includes internal reasoning tokens</span>
</p>
{"".join(sections)}
</div>
</body>
</html>"""

    out.write_text(html, encoding="utf-8")
    print(f"Report written → {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an HTML benchmark report from bench-*.json result files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="JSON",
        help="One or more bench-*.json result files (multiple = trend section added).",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Output HTML path. Default: replaces .json extension with .html on the last input.",
    )
    args = parser.parse_args()

    paths = [pathlib.Path(p) for p in args.inputs]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"Error: not found: {p}", file=sys.stderr)
        sys.exit(1)

    runs = load_results(paths)
    if not runs:
        print("No valid result files loaded.", file=sys.stderr)
        sys.exit(1)

    out = pathlib.Path(args.out) if args.out else paths[-1].with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    build_report(runs, out)


if __name__ == "__main__":
    main()
