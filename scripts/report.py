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

# Models known to use Ollama thinking mode (long internal reasoning before first token)
THINKING_MODELS: set[str] = {
    "qwen3:14b",
    "qwen3:14b-q8_0",
    "qwen3:32b",
    "qwen3.5:27b",
}

PROMPT_ORDER = ["latency", "reasoning", "codegen", "summarise"]
TIER_COLORS = {
    "thinking": "#c0392b",
    "fast": "#27ae60",
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
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  background: #f8f9fa;
  color: #212529;
  padding: 2rem 1rem;
}
.page { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 0.75rem; color: #343a40; border-bottom: 2px solid #dee2e6; padding-bottom: 0.3rem; }
h3 { font-size: 0.95rem; margin: 1.25rem 0 0.4rem; color: #495057; }
p.meta { color: #6c757d; font-size: 0.85rem; margin-bottom: 1.2rem; }
.badge {
  display: inline-block; padding: 0.2rem 0.55rem; border-radius: 12px;
  font-size: 0.75rem; margin: 0 0.2rem;
}
.badge-hw   { background: #cce5ff; color: #004085; }
.badge-date { background: #e2e3e5; color: #383d41; }
.badge-warn { background: #fff3cd; color: #856404; }

/* ── Tables ── */
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; margin-bottom: 1rem; }
th, td { padding: 0.4rem 0.6rem; border: 1px solid #dee2e6; text-align: right; }
th { background: #e9ecef; font-weight: 600; }
td.model-name { text-align: left; font-family: monospace; white-space: nowrap; }
td.tier-label { font-size: 0.7rem; color: #6c757d; text-align: left; }

/* throughput colour bands */
.tps-vhigh { background: #d4edda; }
.tps-high  { background: #e9f7ef; }
.tps-mid   { background: #fff9e6; }
.tps-low   { background: #fdecea; }
.tps-err   { background: #f8d7da; color: #721c24; font-style: italic; }

/* TTFT colour bands */
.ttft-fast  { background: #d4edda; }
.ttft-ok    { background: #fff9e6; }
.ttft-slow  { background: #fdecea; }

/* ── Bar charts ── */
.chart { margin: 0.5rem 0 1.5rem; }
.bar-row { display: flex; align-items: center; margin: 3px 0; gap: 8px; }
.bar-model { width: 220px; font-family: monospace; font-size: 0.78rem;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; background: #e9ecef; border-radius: 3px; height: 18px; position: relative; }
.bar-fill  { height: 100%; border-radius: 3px; min-width: 2px;
             display: flex; align-items: center; padding-left: 5px; }
.bar-fill span { color: white; font-size: 0.72rem; white-space: nowrap; }
.bar-val   { width: 70px; font-size: 0.78rem; color: #495057; text-align: right; }

/* ── Trend ── */
.trend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1rem; }
.trend-card { background: white; border: 1px solid #dee2e6; border-radius: 6px; padding: 1rem; }
.trend-card h4 { font-size: 0.85rem; margin-bottom: 0.5rem; font-family: monospace; }

/* ── Section spacing ── */
.section { background: white; border: 1px solid #dee2e6; border-radius: 8px;
           padding: 1.25rem 1.5rem; margin-bottom: 1.5rem; }
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
        return f"{ms/60_000:.1f} min"
    if ms >= 1_000:
        return f"{ms/1_000:.1f} s"
    return f"{ms:.0f} ms"


def _bar_color(model: str) -> str:
    return "#c0392b" if model in THINKING_MODELS else "#2980b9"


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------


def _throughput_table(models: list[str], pt: dict[str, dict[str, dict]], prompts: list[str]) -> str:
    rows = ["<table>", "<thead><tr>"]
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
    rows.append("</tbody></table>")
    return "\n".join(rows)


def _ttft_table(models: list[str], pt: dict[str, dict[str, dict]], prompts: list[str]) -> str:
    rows = ["<table>", "<thead><tr>"]
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
    rows.append("</tbody></table>")
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
            f"<span>{label}</span></div></div>"
            f'<div class="bar-val">{tps:.1f}</div>'
            f"</div>"
        )
    rows.append("</div>")
    return "\n".join(rows)


def _ttft_bar_chart(models: list[str], pt: dict[str, dict[str, dict]], prompt: str) -> str:
    """Log-scale TTFT bars (ms), non-thinking and thinking grouped."""
    values = []
    for model in models:
        r = pt.get(model, {}).get(prompt)
        if r and not r.get("error"):
            values.append((model, r["ttft_ms"]))
    if not values:
        return "<p>No data.</p>"
    max_log = math.log10(max(v for _, v in values) + 1) or 1
    rows = ['<div class="chart">']
    for model, ms in sorted(values, key=lambda x: x[1]):
        pct = max(2, int(math.log10(ms + 1) / max_log * 100))
        color = _bar_color(model)
        label = _fmt_ttft(ms)
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-model" title="{model}">{model}</div>'
            f'<div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%;background:{color}">'
            f"<span>{label}</span></div></div>"
            f'<div class="bar-val">{label}</div>'
            f"</div>"
        )
    rows.append("</div>")
    return "\n".join(rows)


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

    # ── Bar charts
    chart_html = []
    for prompt in prompts:
        chart_html.append(f"<h3>Throughput — {prompt}</h3>")
        chart_html.append(_bar_chart(models, pt, prompt))
        chart_html.append(f"<h3>TTFT — {prompt} (log scale)</h3>")
        chart_html.append(_ttft_bar_chart(models, pt, prompt))
    sections.append(
        '<div class="section"><h2>Charts</h2>' + "\n".join(chart_html) + "</div>"
    )

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
<style>{CSS}</style>
</head>
<body>
<div class="page">
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
