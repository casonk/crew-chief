"""The Weekly report and the Test bench share one page base and one in-page nav."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from crew_chief import theme

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "results" / "bench-20260621.json"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def nav_of(page: str) -> str:
    return re.search(r'<nav class="report-nav".*?</nav>', page, re.S).group(0)


class NavTests(unittest.TestCase):
    def test_the_nav_marks_the_current_report_and_links_both(self):
        speed, tests = theme.report_nav("speed"), theme.report_nav("tests")
        for nav in (speed, tests):
            self.assertIn('href="latest.html"', nav)
            self.assertIn('href="test-bench-latest.html"', nav)
            self.assertEqual(nav.count('aria-current="page"'), 1)
        self.assertIn('aria-current="page">Inference speed', speed)
        self.assertIn('aria-current="page">Test outcomes', tests)

    def test_the_shared_css_uses_only_theme_tokens(self):
        self.assertNotRegex(theme.REPORT_CSS, r"#[0-9a-fA-F]{3,8}\b")
        self.assertIn(".report-nav", theme.REPORT_CSS)


class GeneratorTests(unittest.TestCase):
    def test_the_test_bench_page_uses_the_shared_chrome_and_is_a_whole_document(self):
        page = load("test_benchmark").render_html({"created_at": "2026-01-01", "results": []})
        self.assertEqual(nav_of(page), theme.report_nav("tests"))
        self.assertIn(theme.REPORT_CSS, page)
        for part in ("<head>", "</head>", "<body>", '<div class="page">', "</body>"):
            self.assertIn(part, page)

    @unittest.skipUnless(SAMPLE.is_file(), "sample benchmark result is not checked out")
    def test_the_weekly_report_uses_the_same_chrome(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.html"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "report.py"),
                    str(SAMPLE),
                    "--out",
                    str(out),
                ],
                check=True,
                capture_output=True,
            )
            page = out.read_text()
        self.assertEqual(nav_of(page), theme.report_nav("speed"))
        self.assertIn(theme.REPORT_CSS, page)


if __name__ == "__main__":
    unittest.main()
