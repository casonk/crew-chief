"""crew_chief.theme — the portfolio's shared colour themes, for pages and reports.

The themes are defined once, in traction-control (``themes/themes.toml``,
``docs/system-theme.md``). ``portfolio/theme.{css,js}`` here are vendored
copies of its rendered output (``scripts/portfolio_sites.py vendor``); a test compares them with the source whenever
traction-control sits next to this repository. Pages style themselves only with
the tokens (``var(--surface)``), include ``HEAD`` once and may place ``SWITCHER``
anywhere; the page then follows the system theme or the viewer's saved choice.
Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

DIR = Path(__file__).resolve().parent / "portfolio"
CSS = (DIR / "theme.css").read_text(encoding="utf-8")
JS = (DIR / "theme.js").read_text(encoding="utf-8")
HEAD = f"<style>{CSS}</style><script>{JS}</script>"
SWITCHER = '<select data-theme-switcher class="theme-switch"></select>'

# Tokens other than the theme's own, shared by every page here. Uses tokens only.
SWITCHER_CSS = (
    ".theme-switch{background:var(--surface);color:var(--text);border:1px solid var(--border);"
    "border-radius:6px;padding:4px 8px;font:inherit;font-size:13px}"
)


# The page base and the in-page report nav, shared by every report generator so the Weekly report
# (inference speed) and the Test bench (test outcomes) have the same top: same font, spacing, tab
# size and heading. Tokens only.
REPORT_CSS = (
    "*{box-sizing:border-box}"
    "body{margin:0;padding:2rem 1rem;font:15px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "background:var(--bg);color:var(--text)}"
    ".page{max-width:1200px;margin:0 auto}"
    ".report-nav{display:flex;gap:.6rem;flex-wrap:wrap;margin:0 0 1.3rem;align-items:center}"
    ".report-nav a{padding:.45rem .8rem;border:1px solid var(--border);border-radius:6px;"
    "color:var(--accent);text-decoration:none;background:var(--surface);font-size:.9rem;line-height:1.2}"
    ".report-nav a[aria-current=page]{background:var(--accent);color:var(--accent-ink);"
    "border-color:var(--accent)}"
    ".report-nav .theme-switch{margin-left:auto}"
    "h1{font-size:1.6rem;margin:0 0 .25rem}"
)
REPORT_TABS = (
    ("latest.html", "Inference speed", "speed"),
    ("test-bench-latest.html", "Test outcomes", "tests"),
)


def report_nav(current: str) -> str:
    """The in-page nav between report kinds, with *current* (``speed`` or ``tests``) marked."""
    tabs = "".join(
        f'<a href="{href}"' + (' aria-current="page"' if key == current else "") + f">{label}</a>"
        for href, label, key in REPORT_TABS
    )
    return f'<nav class="report-nav" aria-label="Benchmark reports">{tabs}{SWITCHER}</nav>'
