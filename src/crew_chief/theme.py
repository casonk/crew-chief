"""crew_chief.theme — the portfolio's shared colour themes, for pages and reports.

The themes are defined once, in traction-control (``themes/themes.toml``,
``docs/system-theme.md``). ``theme/portfolio-theme.{css,js}`` here are vendored
copies of its rendered output; a test compares them with the source whenever
traction-control sits next to this repository. Pages style themselves only with
the tokens (``var(--surface)``), include ``HEAD`` once and may place ``SWITCHER``
anywhere; the page then follows the system theme or the viewer's saved choice.
Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

DIR = Path(__file__).resolve().parent / "theme"
CSS = (DIR / "portfolio-theme.css").read_text(encoding="utf-8")
JS = (DIR / "portfolio-theme.js").read_text(encoding="utf-8")
HEAD = f"<style>{CSS}</style><script>{JS}</script>"
SWITCHER = '<select data-theme-switcher class="theme-switch"></select>'

# Tokens other than the theme's own, shared by every page here. Uses tokens only.
SWITCHER_CSS = (
    ".theme-switch{background:var(--surface);color:var(--text);border:1px solid var(--border);"
    "border-radius:6px;padding:4px 8px;font:inherit;font-size:13px}"
)
