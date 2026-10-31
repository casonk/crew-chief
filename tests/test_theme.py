"""The vendored system theme matches its source, and the generators use tokens, not colours."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

from crew_chief import benchui, theme
from crew_chief import routerbench as rb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO.parent / "traction-control" / "themes"
LITERAL = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3,6}\b")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class VendoredThemeTests(unittest.TestCase):
    @unittest.skipUnless(SOURCE.is_dir(), "traction-control is not next to this repository")
    def test_vendored_files_match_traction_control(self):
        for name, source in (
            ("theme.css", "portfolio-theme.css"),
            ("theme.js", "portfolio-theme.js"),
        ):
            self.assertEqual(
                (theme.DIR / name).read_text(encoding="utf-8"),
                (SOURCE / source).read_text(encoding="utf-8"),
                f"{name} is stale; run traction-control/scripts/render_portfolio_theme.py "
                "--install src/crew_chief/theme",
            )

    def test_theme_defines_several_themes_and_a_switcher(self):
        self.assertGreaterEqual(theme.CSS.count("[data-theme="), 3)
        self.assertIn("data-theme-switcher", theme.SWITCHER)
        self.assertIn("PortfolioTheme", theme.JS)


class GeneratorStyleTests(unittest.TestCase):
    def test_generator_styles_use_tokens_not_literal_colours(self):
        report = load_script("report")
        tb = load_script("test_benchmark")
        self.assertFalse(LITERAL.findall(report.CSS), "report.py CSS has a literal colour")
        for name in ("report", "test_benchmark"):
            source = (REPO / "scripts" / f"{name}.py").read_text(encoding="utf-8")
            self.assertEqual(LITERAL.findall(source), [], f"{name}.py has a literal colour")
        self.assertIn("var(--surface)", report.CSS)
        self.assertTrue(callable(tb.render_html))

    def test_report_pages_carry_the_theme_and_a_switcher(self):
        tb = load_script("test_benchmark")
        page = tb.render_html({"created_at": "2026-10-30", "results": [], "tasks": [1]})
        self.assertIn("data-theme-switcher", page)
        self.assertIn("PortfolioTheme", page)
        self.assertIn("var(--bg)", page)

    def test_routebench_chart_follows_the_theme_with_midnight_fallbacks(self):
        result = {
            "strategies": {
                "single:a": {"ms_mean": 80.0, "accuracy": 0.9},
                "oracle": {"ms_mean": 60.0, "accuracy": 0.95},
            },
            "pareto": ["single:a"],
        }
        svg = rb.render_svg(result)
        self.assertIn("var(--accent,#5b7fff)", svg)
        self.assertIn("var(--purple,#a06fff)", svg)
        self.assertNotIn('stroke-opacity="0.3"', svg)

    def test_pages_load_the_portfolio_top_bar_from_the_shared_caddy(self):
        from crew_chief.benchui_page import PAGE

        tag = '<script src="/_portfolio/chrome.js" defer></script>'
        self.assertEqual(PAGE.count(tag), 1)
        report = benchui.with_home_link(b"<html><head><title>r</title></head><body>x</body></html>")
        self.assertEqual(report.decode().count(tag), 1)
        self.assertLess(report.decode().index(tag), report.decode().index("</head>"))
        self.assertEqual(benchui.with_home_link(report).decode().count(tag), 1)

    def test_bench_pages_use_tokens(self):
        from crew_chief.benchui_page import PAGE

        self.assertIn("data-theme-switcher", PAGE)
        self.assertEqual(LITERAL.findall(PAGE.replace(theme.CSS, "").replace(theme.JS, "")), [])
        self.assertIn(b"var(--surface", benchui.with_home_link(b"<body></body>"))


if __name__ == "__main__":
    unittest.main()
