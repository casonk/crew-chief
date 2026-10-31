"""The Weekly report's charts: one per prompt, the scale chosen by a selector."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("report", ROOT / "scripts" / "report.py")
report = importlib.util.module_from_spec(spec)
sys.modules["report"] = report
spec.loader.exec_module(report)

PT = {
    "fast": {"p": {"tokens_per_sec": 200.0, "ttft_ms": 50.0}},
    "slow": {"p": {"tokens_per_sec": 20.0, "ttft_ms": 5000.0}},
    "broken": {"p": {"error": "x"}},
}
MODELS = ["fast", "slow", "broken"]


def widths(chart: str) -> dict[str, int]:
    return {
        m: int(w)
        for m, w in re.findall(
            r'title="([^"]+)">[^<]*</div><div class="bar-track"><div class="bar-fill" style="width:(\d+)%',
            chart,
        )
    }


class ChartTests(unittest.TestCase):
    def test_the_log_and_linear_ttft_charts_differ_only_in_scale(self):
        log = widths(report._ttft_bar_chart(MODELS, PT, "p", log=True))
        lin = widths(report._ttft_bar_chart(MODELS, PT, "p", log=False))
        self.assertEqual(set(log), {"fast", "slow"})  # errors are left out
        self.assertEqual(lin["slow"], 100)
        self.assertEqual(lin["fast"], 2)  # 50 ms against 5 s: a sliver on a linear scale
        self.assertGreater(log["fast"], 40)  # but well visible on a log scale

    def test_a_short_bar_has_no_label_inside_it_and_a_long_one_does(self):
        chart = report._ttft_bar_chart(MODELS, PT, "p", log=False)
        fast = chart.split('title="fast"')[1].split('<div class="bar-val">')[0]
        slow = chart.split('title="slow"')[1].split('<div class="bar-val">')[0]
        self.assertNotIn("<span>", fast)
        self.assertIn("<span>", slow)
        self.assertIn(
            '<div class="bar-val">50 ms</div>', chart
        )  # the value is still shown beside it

    def test_one_heading_per_prompt_and_a_view_for_each_scale(self):
        section = report._chart_section(MODELS, PT, ["p", "q"])
        self.assertEqual(re.findall(r"<h3>(\w+)</h3>", section), ["p", "q"])
        for view in ("tps", "ttft-log", "ttft-lin"):
            self.assertEqual(section.count(f'class="chart-view" data-view="{view}"'), 2)
        self.assertEqual(section.count('id="chart-view"'), 1)  # one selector for every chart

    def test_the_selector_lists_the_views_and_defaults_to_throughput(self):
        section = report._chart_section(MODELS, PT, ["p"])
        options = re.findall(r'<option value="([\w-]+)">', section)
        self.assertEqual(options, ["tps", "ttft-log", "ttft-lin"])
        self.assertIn('class="section charts" data-view="tps"', section)

    def test_without_javascript_every_view_shows(self):
        # hiding is scoped to the .js class, which only the script adds
        self.assertIn(".js .charts .chart-view { display: none; }", report.CHART_CSS)
        self.assertIsNone(
            re.search(r"(?m)^\.charts \.chart-view \{ display: none", report.CHART_CSS)
        )
        self.assertIn('classList.add("js")', report.CHART_JS)


if __name__ == "__main__":
    unittest.main()
