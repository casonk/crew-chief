"""Routing benchmark edges: unusable inputs, a router that fails, dropped items and reports.

Candidates and the router are faked, as in ``test_routerbench``. A benchmark that quietly
compares different items, or scores a failed router as a pick, would report a number that
means nothing, so these pin the refusals and what is counted as dropped or missed.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crew_chief import routerbench as rb
from crew_chief import taskbench as tb
from tests.test_routerbench import MEASURED, TASK, FakeRouter, benchmark, ticking_clock


class CallAndCollect(unittest.TestCase):
    def test_a_call_knows_whether_it_was_right_and_how_sure_it_was(self):
        sure = rb.Call("a", "a", {"a": 0.9, "b": 0.1}, 5.0)
        self.assertTrue(sure.correct)
        self.assertEqual(sure.confidence, 0.9)
        self.assertFalse(rb.Call("b", "a", {"b": 1.0}, 5.0).correct)
        self.assertIsNone(rb.Call("a", "a", None, 5.0).confidence)
        self.assertIsNone(rb.Call("a", "a", {}, 5.0).confidence)

    def test_items_a_runner_did_not_answer_are_left_out(self):
        result = {
            "rows": [
                {
                    "item": 0,
                    "ms": 3.0,
                    "answers": {"kind": {"value": "a", "expected": "a", "p": {"a": 1.0}}},
                },
                {"item": 1, "ms": 4.0, "answers": {}},
                {"item": 2, "ms": 5.0},
            ]
        }
        with patch.object(rb.tb, "run", return_value=result):
            got = rb.collect(TASK, object())
        self.assertEqual(list(got), [0])
        self.assertEqual((got[0].value, got[0].ms), ("a", 3.0))


class Refusals(unittest.TestCase):
    def run_with(self, tasks, measured=MEASURED, candidates=("systemone:fast", "systemone:slow")):
        with (
            patch.object(
                rb.tb, "make_runner", side_effect=lambda spec, task: SimpleNamespace(name=spec)
            ),
            patch.object(rb, "collect", side_effect=lambda task, runner: measured[runner.name]),
        ):
            return rb.run_benchmark(
                tasks,
                list(candidates),
                FakeRouter(),
                thresholds=(0.8,),
                clock=ticking_clock().__next__,
            )

    def test_a_task_with_more_than_one_question_is_refused_by_name(self):
        two = tb.Task(
            "pair", "",
            {"x": tb.Question("x", "choice", "?", {"a": "A", "b": "B"}), "y": tb.Question("y", "choice", "?", {"a": "A", "b": "B"})},
            [{"state": "s", "expected": {"x": "a", "y": "b"}, "split": "test"}],
        )  # fmt: skip
        with self.assertRaisesRegex(
            rb.RouteError, "pair: routing benchmarks take single-question tasks"
        ):
            self.run_with([two])

    def test_a_task_with_no_test_item_every_candidate_answered_is_refused(self):
        partial = {
            "systemone:fast": {i: c for i, c in MEASURED["systemone:fast"].items() if i < 2},
            "systemone:slow": MEASURED["systemone:slow"],
        }
        with self.assertRaisesRegex(
            rb.RouteError, "toy: no test items answered by every candidate"
        ):
            self.run_with([TASK], measured=partial)

    def test_an_item_a_candidate_failed_is_dropped_everywhere_and_counted(self):
        missing_one = {
            "systemone:fast": {i: c for i, c in MEASURED["systemone:fast"].items() if i != 5},
            "systemone:slow": MEASURED["systemone:slow"],
        }
        result = self.run_with([TASK], measured=missing_one)
        self.assertEqual(result["dropped_items"], 1)
        for name, strategy in result["strategies"].items():
            self.assertEqual(strategy["per_task"]["toy"]["n"], 3, name)


class RouterFailures(unittest.TestCase):
    def test_a_router_that_errors_is_a_missed_pick_that_falls_back_not_a_crash(self):
        class Broken(FakeRouter):
            def answer(self, task, state):
                raise OSError("router down")

        result = benchmark(Broken())
        # no held-out pick is a model; each is recorded as invalid and the routed strategy
        # falls back rather than leaving the items unanswered
        picks = result["router_picks"]
        self.assertEqual(sum(row["invalid"] for row in picks.values()), 4)
        self.assertEqual(sum(row[m] for row in picks.values() for m in ("fast", "slow", "none")), 0)
        routed = result["strategies"]["route:systemone:picker"]
        self.assertEqual(routed["n"], 4)
        self.assertIsNotNone(routed["accuracy"])

    def test_a_pick_that_is_not_a_candidate_is_counted_as_invalid(self):
        result = benchmark(FakeRouter(picks=lambda item: "nonexistent"))
        self.assertEqual(sum(row["invalid"] for row in result["router_picks"].values()), 4)


class Reports(unittest.TestCase):
    def test_the_markdown_mentions_dropped_items_and_the_accuracy_table(self):
        result = benchmark()
        result["dropped_items"] = 2
        text = rb.render_markdown(result, "20261102-000000", chart="chart.svg")
        self.assertIn("2 items were dropped (a candidate errored).", text)
        self.assertIn("![accuracy against mean latency](chart.svg)", text)
        self.assertIn("## Accuracy by task", text)
        self.assertIn("| toy |", text)

    def test_without_a_chart_or_dropped_items_neither_line_appears(self):
        text = rb.render_markdown(benchmark(), "stamp")
        self.assertNotIn("were dropped", text)
        self.assertNotIn("accuracy against mean latency", text)

    def test_a_score_cell_is_gated_a_number_or_a_dash_for_what_is_not_ranked(self):
        block = {"ranking": [{"name": "fast", "score": None}, {"name": "slow", "score": 0.9123}]}
        self.assertEqual(rb._score_cell(block, "fast"), "gated")
        self.assertEqual(rb._score_cell(block, "slow"), "0.912")
        self.assertEqual(rb._score_cell(block, "oracle"), "—")

    def test_the_json_round_trips_and_ends_with_a_newline(self):
        result = benchmark()
        text = rb.to_json(result)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["tasks"], result["tasks"])

    def test_an_unanswered_item_is_a_miss_in_the_confusion_counts(self):
        outcomes = {
            "toy": [
                rb.Outcome(None, "a", 1.0),
                rb.Outcome("a", "a", 1.0),
                rb.Outcome("b", "a", 1.0),
            ]
        }
        summary = rb.summarize({"toy": ["a", "b"]}, outcomes)
        self.assertEqual(summary["n"], 3)
        self.assertAlmostEqual(summary["accuracy"], 1 / 3, places=2)
        confusion = summary["confusion"]["toy"]
        # the unanswered item is counted as unanswered, not as any label, and still counts in support
        self.assertEqual(confusion["invalid"], {"a": 1, "b": 0})
        self.assertEqual(confusion["counts"]["a"], {"a": 1, "b": 1})
        self.assertEqual(confusion["per_label"]["a"]["support"], 3)


if __name__ == "__main__":
    unittest.main()
