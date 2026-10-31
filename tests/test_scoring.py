"""Tests for crew_chief.scoring and its use in the taskbench and routebench reports."""

from __future__ import annotations

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from crew_chief import routerbench as rb
from crew_chief import scoring
from crew_chief import taskbench as tb

PROFILE = scoring.Profile(
    "p",
    "",
    accuracy_weight=0.7,
    target_ms=100,
    ceiling_ms=1000,
    min_accuracy=0.8,
    max_p90_ms=1500,
    tie_margin=0.02,
)


class SpeedTests(unittest.TestCase):
    def test_curve_is_one_under_target_zero_over_ceiling_log_linear_between(self):
        self.assertEqual(scoring.speed_score(50, 100, 1000), 1.0)
        self.assertEqual(scoring.speed_score(100, 100, 1000), 1.0)
        self.assertEqual(scoring.speed_score(1000, 100, 1000), 0.0)
        self.assertEqual(scoring.speed_score(5000, 100, 1000), 0.0)
        self.assertAlmostEqual(scoring.speed_score(math.sqrt(100 * 1000), 100, 1000), 0.5)


class ScoreTests(unittest.TestCase):
    def test_weighted_sum(self):
        got = scoring.score(PROFILE, 0.9, math.sqrt(100 * 1000), 100)
        self.assertAlmostEqual(got.value, 0.7 * 0.9 + 0.3 * 0.5)

    def test_tail_weight_charges_a_slow_p90(self):
        tail = scoring.Profile("t", "", 0.5, 100, 1000, tail_weight=0.5)
        fast_tail = scoring.score(tail, 0.9, 100, 100).value
        slow_tail = scoring.score(tail, 0.9, 100, 1000).value
        self.assertAlmostEqual(fast_tail - slow_tail, 0.5 * 0.5)

    def test_gates_remove_the_score(self):
        low = scoring.score(PROFILE, 0.7, 50, 50)
        self.assertIsNone(low.value)
        self.assertIn("accuracy 0.70", low.gate)
        slow = scoring.score(PROFILE, 0.95, 50, 2000)
        self.assertIsNone(slow.value)
        self.assertIn("p90 2000", slow.gate)

    def test_weight_override_leaves_gates_alone(self):
        self.assertIsNone(scoring.score(PROFILE, 0.7, 50, 50, accuracy_weight=0.99).value)


class RankTests(unittest.TestCase):
    ENTRIES = {
        "fast": (0.91, 70, 100),  # 0.937
        "near": (0.90, 70, 100),  # 0.930: within the tie margin of fast
        "accurate": (0.94, 200, 300),  # 0.868: more accurate, but slower
        "slow": (0.94, 900, 1400),  # 0.672
        "bad": (0.60, 40, 50),  # fails the accuracy gate
    }

    def test_gated_last_and_ties_flagged(self):
        ranking = scoring.rank(PROFILE, self.ENTRIES)
        self.assertEqual(ranking[-1]["name"], "bad")
        self.assertIsNone(ranking[-1]["score"])
        self.assertEqual({r["name"] for r in ranking if r["tied"]}, {"fast", "near"})
        self.assertEqual(ranking[-2]["name"], "slow")

    def test_sensitivity_flips_with_the_weight(self):
        sweep = scoring.sensitivity(PROFILE, self.ENTRIES, (0.5, 1.0))
        self.assertEqual(sweep[0.5], ["fast", "near"])
        self.assertEqual(sweep[1.0], ["accurate", "slow"])  # pure accuracy: speed no longer counts
        self.assertIn(0.7, sweep)  # the profile's own weight is always included


class LoadTests(unittest.TestCase):
    def write(self, text):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "p.toml"
        path.write_text(text)
        return path

    def test_shipped_profiles_load(self):
        names = {p.name for p in scoring.load_profiles()}
        self.assertEqual(names, {"interactive", "batch"})

    def test_rejects_bad_profiles(self):
        for body in (
            "accuracy_weight = 1.5\ntarget_ms = 1\nceiling_ms = 2",
            "accuracy_weight = 0.5\ntarget_ms = 10\nceiling_ms = 5",
            "accuracy_weight = 0.5\ntarget_ms = 1\nceiling_ms = 2\nmin_accuracy = 2",
            'accuracy_weight = "x"\ntarget_ms = 1\nceiling_ms = 2',
        ):
            with self.subTest(body=body), self.assertRaises(scoring.ScoringError):
                scoring.load_profiles(self.write(f"[profiles.x]\n{body}\n"))

    def test_missing_file_and_empty_file(self):
        with self.assertRaises(scoring.ScoringError):
            scoring.load_profiles(Path("/nonexistent/p.toml"))
        with self.assertRaises(scoring.ScoringError):
            scoring.load_profiles(self.write("# nothing\n"))


class ReportTests(unittest.TestCase):
    def test_taskbench_table_has_a_score_column_per_profile(self):
        task = tb.Task(
            "t",
            "",
            {"k": tb.Question("k", "choice", "?", {"a": "A", "b": "B"})},
            [{"state": "x", "expected": {"k": "a"}}],
            {"k": {"default": "a"}},
        )
        result = tb.run(task, tb.RulesRunner(task))
        md = tb.render_markdown([result], task, "now", [PROFILE])
        self.assertIn("score: p |", md)
        self.assertIn("| 0.0 | 0.0 | 1.000 |", md)  # zero latency earns full speed credit
        self.assertIn("- `p`: 0.7 accuracy + 0.3 speed", md)
        self.assertNotIn("score:", tb.render_markdown([result], task, "now"))

    def test_routebench_scores_exclude_the_oracle(self):
        strategies = {
            "single:a": {"accuracy": 0.9, "ms_mean": 80.0, "ms_p90": 90.0},
            "single:b": {"accuracy": 0.95, "ms_mean": 90.0, "ms_p90": 100.0},
            "oracle": {"accuracy": 1.0, "ms_mean": 10.0, "ms_p90": 10.0},
        }
        block = rb.score_strategies(strategies, [PROFILE])["p"]
        self.assertEqual([r["name"] for r in block["ranking"]], ["single:b", "single:a"])
        self.assertEqual(rb._score_cell(block, "oracle"), "—")
        lines = "\n".join(rb._render_scores("p", block))
        self.assertIn("## Scores: p", lines)
        self.assertIn("| accuracy weight | tied for the lead |", lines)


if __name__ == "__main__":
    unittest.main()
