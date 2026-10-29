"""Tests for crew_chief.taskbench — offline; runners' HTTP calls are faked."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from crew_chief import taskbench as tb

TASK_FILE = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "decisions" / "message-routing.json"
)

MINI = {
    "name": "mini",
    "questions": {
        "kind": {"type": "choice", "instructions": "Kind?", "criteria": {"a": "A", "b": "B"}},
        "level": {"type": "score", "instructions": "Level?", "criteria": ["low", "mid", "high"]},
        "flag": {"type": "noul", "instructions": "Flag?"},
    },
    "baseline": {
        "kind": {"default": "a", "rules": [{"if_any": ["bee"], "then": "b"}]},
        "flag": {"default": False, "rules": [{"if_any": ["!"], "then": True}]},
    },
    "items": [
        {"state": "bee!", "expected": {"kind": "b", "level": "2", "flag": True}},
        {"state": "ant", "expected": {"kind": "a", "level": "0", "flag": False}},
    ],
}


def write_task(doc: dict) -> Path:
    tmp = TemporaryDirectory()
    write_task.keep.append(tmp)
    path = Path(tmp.name) / "task.json"
    path.write_text(json.dumps(doc))
    return path


write_task.keep = []


class LoadTests(unittest.TestCase):
    def test_shipped_task_loads(self):
        task = tb.load_task(TASK_FILE)
        self.assertEqual(set(task.questions), {"intent", "urgent", "risk"})
        self.assertGreaterEqual(len(task.items), 30)

    def test_rejects_bad_tasks(self):
        bad = [
            {"questions": {}},
            {"questions": {"q": {"type": "essay"}}},
            {"questions": {"q": {"type": "choice", "criteria": {"only": "one"}}}},
            {"questions": {"q": {"type": "score", "criteria": ["x"]}}},
            {**MINI, "items": [{"state": "x", "expected": {"kind": "zzz"}}]},
            {**MINI, "items": [{"state": "x", "expected": {"nope": "a"}}]},
        ]
        for doc in bad:
            with self.subTest(doc=doc), self.assertRaises(tb.TaskError):
                tb.load_task(write_task(doc))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.task = tb.load_task(write_task(MINI))

    def test_rules_runner_and_scoring(self):
        result = tb.run(self.task, tb.RulesRunner(self.task))
        self.assertEqual(result["questions"]["kind"]["accuracy"], 1.0)
        self.assertEqual(result["questions"]["flag"]["accuracy"], 1.0)
        # no rule and no default for "level": every answer is invalid
        self.assertEqual(result["questions"]["level"]["invalid"], 2)

    def test_ollama_schema_and_parsing(self):
        runner = tb.OllamaRunner("m")
        schema = runner.schema(self.task)
        self.assertEqual(schema["properties"]["level"]["enum"], [0, 1, 2])
        self.assertEqual(schema["properties"]["flag"], {"type": "boolean"})
        reply = {"message": {"content": json.dumps({"kind": "b", "level": 2, "flag": True})}}
        with patch.object(tb, "_post", return_value=reply):
            answers = runner.answer(self.task, "bee!")
        self.assertEqual(
            {k: a.value for k, a in answers.items()}, {"kind": "b", "level": "2", "flag": "true"}
        )

    def test_ollama_invalid_json_counts_as_invalid(self):
        with patch.object(tb, "_post", return_value={"message": {"content": "not json"}}):
            answers = tb.OllamaRunner("m").answer(self.task, "x")
        self.assertTrue(all(a.value is None for a in answers.values()))

    def test_llamacpp_probabilities_from_logprobs(self):
        import math

        def reply(letter_probs, picked):
            return {
                "choices": [
                    {
                        "message": {"content": picked},
                        "logprobs": {
                            "content": [
                                {
                                    "top_logprobs": [
                                        {"token": t, "logprob": math.log(p)}
                                        for t, p in letter_probs.items()
                                    ]
                                }
                            ]
                        },
                    }
                ]
            }

        replies = [
            reply({"B": 0.6, "A": 0.2, "x": 0.2}, "B"),  # kind: non-letter token ignored
            reply({"C": 0.9, "B": 0.1}, "C"),  # level
            reply({"A": 0.8, "B": 0.2}, "A"),  # flag: A = true
        ]
        with patch.object(tb, "_post", side_effect=replies):
            answers = tb.LlamaCppRunner("m").answer(self.task, "bee!")
        self.assertEqual(answers["kind"].value, "b")
        self.assertAlmostEqual(answers["kind"].probabilities["b"], 0.75)
        self.assertEqual(answers["level"].value, "2")
        self.assertEqual(answers["flag"].value, "true")

    def test_jev_request_and_response_mapping(self):
        runner = tb.JevRunner("key")
        request = runner.request(self.task, "bee!")
        self.assertEqual(request["model"], "jev-latest")
        self.assertEqual(request["questions"]["level"]["criteria"], ["low", "mid", "high"])
        self.assertNotIn("criteria", request["questions"]["flag"])
        body = {
            "answers": {
                "kind": {
                    "type": "choice",
                    "choice": "b",
                    "confidence": 0.9,
                    "probabilities": {"a": 0.1, "b": 0.9},
                },
                "level": {
                    "type": "score",
                    "score": 1.8,
                    "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8},
                },
                "flag": {"type": "noul", "noul": 0.97},
            }
        }
        answers = tb.parse_jev(self.task, body)
        self.assertEqual([answers[q].value for q in ("kind", "level", "flag")], ["b", "2", "true"])
        self.assertAlmostEqual(answers["flag"].probabilities["false"], 0.03)

    def test_systemone_runner_posts_to_ollama_without_a_key(self):
        runner = tb.make_runner("systemone:nimble", self.task)
        self.assertEqual(runner.url, "http://localhost:11434/v1/systemone")
        body = {"answers": {"flag": {"type": "noul", "noul": 0.2}}}
        with patch.object(tb, "_post", return_value=body) as post:
            answers = runner.answer(self.task, "x")
        self.assertEqual(post.call_args.kwargs["headers"], {})
        self.assertEqual(post.call_args.args[1]["model"], "nimble")
        self.assertEqual(answers["flag"].value, "false")
        self.assertIsNone(answers["kind"].value)

    def test_jev_needs_a_key(self):
        with self.assertRaises(tb.TaskError):
            tb.JevRunner("")

    def test_brier_and_markdown(self):
        self.assertAlmostEqual(tb.brier({"a": 1.0}, "a", ["a", "b"]), 0.0)
        self.assertAlmostEqual(tb.brier({"a": 0.5, "b": 0.5}, "a", ["a", "b"]), 0.5)
        result = tb.run(self.task, tb.RulesRunner(self.task))
        md = tb.render_markdown([result], self.task, "now")
        self.assertIn("| rules | 1.00 |", md)

    def test_runner_errors_are_counted_not_raised(self):
        with patch.object(tb, "_post", side_effect=OSError("refused")):
            result = tb.run(self.task, tb.OllamaRunner("m"))
        self.assertEqual(result["errors"], 2)


class SplitTests(unittest.TestCase):
    def _task(self):
        doc = json.loads(json.dumps(MINI))
        doc["items"][1]["split"] = "heldout"
        return tb.load_task(write_task(doc))

    def test_select_keeps_one_split(self):
        task = self._task()
        self.assertEqual([i["state"] for i in task.select("dev").items], ["bee!"])
        self.assertEqual([i["state"] for i in task.select("heldout").items], ["ant"])
        self.assertEqual(len(task.select("all").items), 2)
        self.assertEqual(task.select("heldout").split, "heldout")

    def test_unknown_and_empty_splits_are_errors(self):
        task = self._task()
        with self.assertRaises(tb.TaskError):
            task.select("test")
        only_dev = tb.load_task(write_task(MINI))
        with self.assertRaises(tb.TaskError):
            only_dev.select("heldout")

    def test_bad_split_value_and_repeated_state_are_rejected(self):
        bad = json.loads(json.dumps(MINI))
        bad["items"][0]["split"] = "train"
        with self.assertRaises(tb.TaskError):
            tb.load_task(write_task(bad))
        dup = json.loads(json.dumps(MINI))
        dup["items"][1]["state"] = "  BEE!"
        dup["items"][1]["split"] = "heldout"
        with self.assertRaises(tb.TaskError):
            tb.load_task(write_task(dup))

    def test_report_names_the_split(self):
        task = self._task().select("heldout")
        result = tb.run(task, tb.make_runner("rules", task))
        self.assertIn("1 items (heldout split)", tb.render_markdown([result], task, "x"))


class ShippedSuiteTests(unittest.TestCase):
    SUITES = ("message-routing", "mail-triage", "receipt-category", "schema-extraction")

    def test_every_suite_has_dev_and_heldout_items_and_no_shared_text(self):
        for name in self.SUITES:
            task = tb.load_task(TASK_FILE.with_name(f"{name}.json"))
            dev, held = task.select("dev"), task.select("heldout")
            self.assertGreaterEqual(len(dev.items), 16, name)
            self.assertGreaterEqual(len(held.items), 8, name)
            self.assertFalse(
                {i["state"] for i in dev.items} & {i["state"] for i in held.items}, name
            )


if __name__ == "__main__":
    unittest.main()
