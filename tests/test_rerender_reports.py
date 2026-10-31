"""scripts/rerender_reports.py keeps saved benchmark reports on the current theme."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "rerender_reports", ROOT / "scripts/rerender_reports.py"
)
rerender = importlib.util.module_from_spec(spec)
sys.modules["rerender_reports"] = rerender
spec.loader.exec_module(rerender)

SAMPLE = ROOT / "results" / "bench-20260621.json"
STALE = "<style>/* Generated from themes/themes.toml by an old script */:root{--old:1}</style>"


@unittest.skipUnless(SAMPLE.is_file(), "sample benchmark result is not checked out")
class RerenderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        shutil.copy(SAMPLE, self.dir / "bench-20260621.json")
        (self.dir / "bench-20260621.html").write_text(
            f"<html><head>{STALE}</head><body>old</body></html>"
        )

    def run_main(self, *argv):
        sys.argv = ["rerender_reports.py", "--results", str(self.dir), *argv]
        return rerender.main()

    def test_a_stale_report_is_found_and_check_does_not_change_it(self):
        before = (self.dir / "bench-20260621.html").read_text()
        self.assertEqual(self.run_main("--check"), 1)
        self.assertEqual((self.dir / "bench-20260621.html").read_text(), before)

    def test_rendering_brings_it_to_the_current_theme_and_is_then_idempotent(self):
        self.assertEqual(self.run_main(), 0)
        page = (self.dir / "bench-20260621.html").read_text()
        self.assertTrue(rerender.is_current(self.dir / "bench-20260621.html"))
        self.assertNotIn("--old:1", page)
        self.assertEqual(self.run_main("--check"), 0)

    def test_force_rebuilds_a_report_whose_theme_is_already_current(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.run_main("--check"), 0)  # current: nothing to do
        page = self.dir / "bench-20260621.html"
        page.write_text(page.read_text() + "<!-- edited -->")
        self.assertEqual(self.run_main("--force"), 0)
        self.assertNotIn("<!-- edited -->", page.read_text())

    def test_an_old_routebench_chart_is_redrawn_with_label_placement(self):
        route = {
            "strategies": {
                "a": {"n": 1, "accuracy": 0.9, "ms_mean": 100.0},
                "b": {"n": 1, "accuracy": 0.9, "ms_mean": 100.0},
            },
            "pareto": ["a"],
        }
        (self.dir / "routebench-1.json").write_text(json.dumps(route))
        svg = self.dir / "routebench-1.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>old</text></svg>')
        self.assertEqual(self.run_main("--check"), 1)
        self.assertEqual(self.run_main(), 0)
        self.assertIn('data-layout="2"', svg.read_text())
        self.assertEqual(self.run_main("--check"), 0)
        ys = [
            float(y)
            for y in re.findall(r'<text x="[\d.]+" y="([\d.]+)">[ab]</text>', svg.read_text())
        ]
        self.assertEqual(len(ys), 2)
        self.assertGreaterEqual(abs(ys[0] - ys[1]), 12)  # two close points, labels apart

    def test_latest_links_and_reports_without_json_are_left_alone(self):
        (self.dir / "bench-latest.html").symlink_to("bench-20260621.html")
        (self.dir / "bench-latest.json").symlink_to("bench-20260621.json")
        (self.dir / "bench-20260101.html").write_text("<p>no data</p>")
        found = [p.name for p in rerender.reports(self.dir)]
        self.assertEqual(found, ["bench-20260621.json"])


if __name__ == "__main__":
    unittest.main()
