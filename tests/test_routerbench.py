"""Tests for crew_chief.routerbench — offline; candidates and the router are faked."""

from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crew_chief import routerbench as rb
from crew_chief import taskbench as tb

TASK = tb.Task(
    "toy",
    "",
    {"kind": tb.Question("kind", "choice", "Which?", {"a": "A", "b": "B"})},
    [
        {"state": "d1", "expected": {"kind": "a"}},
        {"state": "d2", "expected": {"kind": "b"}},
        {"state": "h1", "expected": {"kind": "a"}, "split": "test"},
        {"state": "h2", "expected": {"kind": "b"}, "split": "test"},
        {"state": "h3", "expected": {"kind": "a"}, "split": "test"},
        {"state": "h4", "expected": {"kind": "b"}, "split": "test"},
    ],
)
TRUTH = ["a", "b", "a", "b", "a", "b"]


def calls(values, confidence, ms):
    return {
        i: rb.Call(v, TRUTH[i], {v: c} if v else None, ms)
        for i, (v, c) in enumerate(zip(values, confidence, strict=True))
    }


# `fast` is right on train and on h1/h2 but unsure and wrong on h3/h4; `slow` is always right.
MEASURED = {
    "systemone:fast": calls(["a", "b", "a", "b", "b", "a"], [0.9, 0.9, 0.9, 0.9, 0.5, 0.5], 10.0),
    "systemone:slow": calls(TRUTH, [0.99] * 6, 100.0),
}


class FakeRouter:
    name = "systemone:picker"

    def __init__(self, picks=None):
        self.picks = picks

    def answer(self, task, state):
        item = state.rsplit("Item: ", 1)[1]
        model = "slow" if item in ("h3", "h4") else "fast"
        value = self.picks(item) if self.picks else model
        return {
            "model": tb.Answer(
                value, {m: float(m == value) for m in task.questions["model"].labels}
            )
        }


def ticking_clock(step=0.005):
    """Each router call reads the clock twice; make every call last `step` seconds."""
    return itertools.chain.from_iterable((t, t + step) for t in itertools.count(0, 1))


def benchmark(router=None):
    with (
        patch.object(
            rb.tb, "make_runner", side_effect=lambda spec, task: SimpleNamespace(name=spec)
        ),
        patch.object(rb, "collect", side_effect=lambda task, runner: MEASURED[runner.name]),
    ):
        return rb.run_benchmark(
            [TASK],
            ["systemone:fast", "systemone:slow"],
            router or FakeRouter(),
            thresholds=(0.8,),
            clock=ticking_clock().__next__,
        )


class StrategyTests(unittest.TestCase):
    def test_strategy_quality_and_latency(self):
        s = benchmark()["strategies"]
        self.assertEqual((s["single:fast"]["accuracy"], s["single:fast"]["ms_mean"]), (0.5, 10.0))
        self.assertEqual((s["single:slow"]["accuracy"], s["single:slow"]["ms_mean"]), (1.0, 100.0))
        self.assertEqual(s["lookup"]["accuracy"], 0.5)  # a train tie goes to the faster model
        self.assertEqual((s["oracle"]["accuracy"], s["oracle"]["ms_mean"]), (1.0, 55.0))
        # Confident h1/h2 stop at the fast model; unsure h3/h4 pay for both calls.
        self.assertEqual((s["cascade@0.8"]["accuracy"], s["cascade@0.8"]["ms_mean"]), (1.0, 60.0))
        # The router call (5 ms) is added to the chosen model's call.
        routed = s["route:systemone:picker"]
        self.assertEqual((routed["accuracy"], routed["ms_mean"]), (1.0, 60.0))

    def test_pareto_front_drops_dominated_strategies(self):
        # lookup picks the same model as single:fast, so they tie. slow, cascade and
        # route all reach 1.0 at 60+ ms: cascade (60) and route (60) tie for the best
        # of those. The oracle (55 ms) is a bound and stays off the front.
        self.assertEqual(
            benchmark()["pareto"],
            ["cascade@0.8", "lookup", "route:systemone:picker", "single:fast"],
        )

    def test_macro_f1_and_confusion_follow_the_final_answers(self):
        result = benchmark()["strategies"]["single:fast"]
        self.assertEqual(result["macro_f1"], 0.5)
        counts = result["confusion"]["toy"]["counts"]
        self.assertEqual(counts, {"a": {"a": 1, "b": 1}, "b": {"a": 1, "b": 1}})

    def test_router_pick_matrix_compares_with_fastest_correct(self):
        picks = benchmark()["router_picks"]
        self.assertEqual((picks["fast"]["fast"], picks["slow"]["slow"]), (2, 2))

    def test_invalid_pick_falls_back_and_is_counted(self):
        result = benchmark(FakeRouter(picks=lambda item: None))
        routed = result["strategies"]["route:systemone:picker"]
        self.assertEqual(routed["accuracy"], 0.5)  # lookup's choice (fast) for every item
        self.assertEqual(result["router_picks"]["slow"]["invalid"], 2)

    def test_profiles_use_dev_items_only(self):
        profile = rb.dev_profile(TASK, MEASURED["systemone:fast"])
        self.assertEqual(profile, {"accuracy": 1.0, "ms": 10.0})

    def test_router_sees_profiles_not_held_out_outcomes(self):
        rtask = rb.router_task(TASK, {"fast": {"accuracy": 1.0, "ms": 10.0}})
        self.assertIn("1.00 accuracy", rtask.questions["model"].criteria["fast"])
        self.assertIn("10 ms", rtask.questions["model"].criteria["fast"])


class ReportTests(unittest.TestCase):
    def test_markdown_and_svg(self):
        result = benchmark()
        md = rb.render_markdown(result, "now", chart="x.svg")
        self.assertIn("| single:fast | 4 | 0.50 |", md)
        self.assertIn("![accuracy against mean latency](x.svg)", md)
        self.assertIn("## Router picks against the fastest correct candidate", md)
        self.assertIn("## Confusion matrix: route:systemone:picker / toy", md)
        svg = rb.render_svg(result)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("single:slow", svg)

    def test_needs_two_distinct_candidates(self):
        with self.assertRaises(rb.RouteError):
            rb.run_benchmark([TASK], ["systemone:fast"], FakeRouter())
        with self.assertRaises(rb.RouteError):
            rb.run_benchmark([TASK], ["systemone:x", "ollama:x"], FakeRouter())


if __name__ == "__main__":
    unittest.main()
