"""Tests for crew_chief.taskbench — offline; runners' HTTP calls are faked."""

from __future__ import annotations

import contextlib
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


CLOCKWORK_SUITES = sorted(TASK_FILE.parent.glob("clockwork-*.json"))


class ClockworkSuiteTests(unittest.TestCase):
    def test_suites_cover_every_list(self):
        names = {p.stem for p in CLOCKWORK_SUITES}
        self.assertEqual(
            names,
            {
                f"clockwork-{n}"
                for n in (
                    "grocery-type",
                    "shopping-type",
                    "watch-category",
                    "listen-category",
                    "read-category",
                    "todo-category",
                    "invest-category",
                )
            },
        )

    def test_each_suite_has_both_splits_and_every_label(self):
        for path in CLOCKWORK_SUITES:
            with self.subTest(suite=path.stem):
                task = tb.load_task(path)
                labels = set(task.questions["category"].labels)
                for split in tb.SPLITS:
                    chosen = task.select(split)
                    self.assertEqual(
                        {i["expected"]["category"] for i in chosen.items}, labels, split
                    )


class BacklogTriageSuiteTests(unittest.TestCase):
    PATH = TASK_FILE.parent / "backlog-triage.json"

    def test_one_repository_question_with_unknown_and_both_splits_cover_every_label(self):
        task = tb.load_task(self.PATH)
        self.assertEqual(set(task.questions), {"repo"})  # a group follows from its repository
        labels = set(task.questions["repo"].labels)
        self.assertIn("unknown", labels)
        self.assertEqual(len(labels), 27)  # 26 repositories and unknown
        for split in tb.SPLITS:
            chosen = task.select(split)
            self.assertEqual({i["expected"]["repo"] for i in chosen.items}, labels, split)

    def test_the_active_sorting_variants_are_gone_because_train_is_always_in_the_prompt(self):
        self.assertEqual(list(TASK_FILE.parent.glob("backlog-triage-active-*.json")), [])

    def test_the_suite_is_synthetic_and_plain(self):
        text = self.PATH.read_text(encoding="utf-8")
        for real in ("clockwork", "crew-chief", "tachometer", "magneto", "locility", "career"):
            self.assertNotIn(real, text)
        self.assertNotIn(
            "Examples:", text
        )  # the train split reaches prompts through the protocol, not the file

    def test_it_keeps_vague_entries_that_name_no_repository(self):
        task = tb.load_task(self.PATH)
        vague = [i for i in task.items if i["expected"]["repo"] == "unknown"]
        self.assertGreaterEqual(len(vague), 12)
        self.assertGreaterEqual(len(task.items), 150)


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

    def test_prompt_lists_allowed_values_before_the_input(self):
        text = tb._prompt(self.task, "bee!")
        self.assertLess(text.index("Allowed values"), text.index("INPUT:"))
        self.assertLess(text.index("- a: A"), text.index("bee!"))
        with patch.object(tb, "_post", return_value={"message": {"content": "{}"}}) as post:
            tb.OllamaRunner("m").answer(self.task, "bee!")
        roles = [m["role"] for m in post.call_args.args[1]["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertNotIn("bee!", post.call_args.args[1]["messages"][0]["content"])

    def test_confusion_matrix_counts_and_rates(self):
        task = tb.Task(
            "c",
            "",
            {"kind": tb.Question("kind", "choice", "?", {"a": "A", "b": "B"})},
            [
                {"state": "1", "expected": {"kind": "a"}},
                {"state": "2", "expected": {"kind": "a"}},
                {"state": "3", "expected": {"kind": "b"}},
                {"state": "4", "expected": {"kind": "b"}},
            ],
        )
        picks = iter(["a", "b", "b", None])

        class Fake:
            name = "fake"

            def answer(self, task, state):
                return {"kind": tb.Answer(next(picks))}

        result = tb.run(task, Fake())
        conf = result["questions"]["kind"]["confusion"]
        self.assertEqual(conf["counts"], {"a": {"a": 1, "b": 1}, "b": {"a": 0, "b": 1}})
        self.assertEqual(conf["invalid"], {"a": 0, "b": 1})
        self.assertEqual(conf["per_label"]["a"]["recall"], 0.5)
        self.assertEqual(conf["per_label"]["b"]["precision"], 0.5)
        self.assertEqual(conf["per_label"]["b"]["recall"], 0.5)
        md = tb.render_markdown([result], task, "now")
        self.assertIn("## Confusion matrix: fake / kind", md)
        self.assertIn("| a | 1 | 1 | 0 | 0.50 |", md)
        self.assertIn("| b | 0 | 1 | 1 | 0.50 |", md)

    def test_runner_errors_are_counted_not_raised(self):
        with patch.object(tb, "_post", side_effect=OSError("refused")):
            result = tb.run(self.task, tb.OllamaRunner("m"))
        self.assertEqual(result["errors"], 2)


class SplitTests(unittest.TestCase):
    def _task(self):
        doc = json.loads(json.dumps(MINI))
        doc["items"][1]["split"] = "test"
        return tb.load_task(write_task(doc))

    def test_select_keeps_one_split_and_the_examples(self):
        task = self._task()
        self.assertEqual([i["state"] for i in task.select("train").items], ["bee!"])
        self.assertEqual([i["state"] for i in task.select("test").items], ["ant"])
        self.assertEqual(len(task.select("all").items), 2)
        self.assertEqual(task.select("test").split, "test")
        self.assertEqual(
            [e["state"] for e in task.select("test").examples], ["bee!"]
        )  # train stays

    def test_an_item_with_no_split_is_train_and_the_old_names_still_work(self):
        task = tb.load_task(write_task(MINI))
        self.assertEqual({i["split"] for i in task.items}, {"train"})
        doc = json.loads(json.dumps(MINI))
        doc["items"][0]["split"], doc["items"][1]["split"] = "dev", "heldout"
        old = tb.load_task(write_task(doc))
        self.assertEqual([i["split"] for i in old.items], ["train", "test"])
        self.assertEqual(old.select("heldout").split, "test")
        self.assertEqual(old.select("dev").split, "train")

    def test_unknown_and_empty_splits_are_errors(self):
        task = self._task()
        with self.assertRaises(tb.TaskError):
            task.select("validation")
        with self.assertRaises(tb.TaskError):
            tb.load_task(write_task(MINI)).select("test")  # every item is train: nothing to score

    def test_bad_split_value_and_repeated_state_are_rejected(self):
        bad = json.loads(json.dumps(MINI))
        bad["items"][0]["split"] = "validation"
        with self.assertRaises(tb.TaskError):
            tb.load_task(write_task(bad))
        dup = json.loads(json.dumps(MINI))
        dup["items"][1]["state"] = "  BEE!"
        dup["items"][1]["split"] = "test"
        with self.assertRaises(tb.TaskError):
            tb.load_task(write_task(dup))

    def test_report_names_the_split_and_the_protocol(self):
        task = self._task().select("test")
        result = tb.run(task, tb.make_runner("rules", task))
        report = tb.render_markdown([result], task, "x")
        self.assertIn("1 items (test split)", report)
        self.assertIn("All 1 train examples are in every prompt", report)
        self.assertIn("none is ever shown to a model", report)
        self.assertEqual(
            result["protocol"],
            {"split": "test", "train_examples": 1, "zero_shot": False, "leave_one_out": False},
        )


def prompts_for(task, state):
    """Everything a model of each kind would be sent for *state* (the HTTP layer is not used)."""
    sent = []
    with patch.object(
        tb, "_post", side_effect=lambda url, payload, **kw: sent.append(payload) or {}
    ):
        for runner in (
            tb.OllamaRunner("m"),
            tb.SystemOneRunner("m", "http://x"),
            tb.LlamaCppRunner("m"),
        ):
            with contextlib.suppress(Exception):
                runner.answer(task, state)
    return json.dumps(sent)


class ProtocolTests(unittest.TestCase):
    def _task(self):
        doc = json.loads(json.dumps(MINI))
        doc["items"] += [
            {"state": "cat", "expected": {"kind": "a", "level": "1", "flag": False}},
            {
                "state": "owl",
                "expected": {"kind": "b", "level": "0", "flag": True},
                "split": "test",
            },
            {
                "state": "elk",
                "expected": {"kind": "a", "level": "2", "flag": False},
                "split": "test",
            },
        ]
        doc["items"][1]["split"] = "test"
        return tb.load_task(write_task(doc))

    def test_the_whole_train_set_is_in_every_kind_of_prompt_a_priori(self):
        task = self._task().select("test")
        self.assertEqual({e["state"] for e in task.examples}, {"bee!", "cat"})
        everything = prompts_for(task, "owl")
        for train_state in ("bee!", "cat"):
            self.assertIn(train_state, everything)
        self.assertIn("ANSWER: kind=b, level=2, flag=true", everything)  # the multi-question form
        self.assertIn("EXAMPLES", everything)

    def test_no_test_item_is_ever_shown_to_a_model(self):
        task = self._task().select("test")
        for state in ("owl", "elk", "ant"):
            everything = prompts_for(task, state)
            for held_out in ("owl", "elk", "ant"):
                if held_out != state:
                    self.assertNotIn(
                        f"INPUT: {held_out}", everything, f"{held_out} leaked while scoring {state}"
                    )

    def test_a_train_item_is_scored_without_its_own_example(self):
        task = self._task().select("train")
        self.assertTrue(task.leave_one_out)
        everything = prompts_for(task, "bee!")
        self.assertNotIn("INPUT: bee!\\nANSWER", everything.replace("\\n", "\\n"))
        self.assertNotIn("bee!\\nANSWER", everything)
        self.assertIn("INPUT: cat", everything)  # the other train item is still an example
        self.assertEqual(
            {e["state"] for e in task.examples_for("BEE!  ")}, {"cat"}
        )  # whitespace/case

    def test_scoring_the_test_split_is_not_leave_one_out(self):
        self.assertFalse(self._task().select("test").leave_one_out)
        self.assertTrue(self._task().leave_one_out)  # all: the train half is

    def test_zero_shot_removes_the_examples_and_is_recorded(self):
        task = self._task().select("test").without_examples()
        self.assertTrue(task.zero_shot and not task.examples)
        everything = prompts_for(task, "owl")
        self.assertNotIn("EXAMPLES", everything)
        self.assertNotIn("bee!", everything)
        result = tb.run(task, tb.make_runner("rules", task))
        self.assertTrue(result["protocol"]["zero_shot"])
        self.assertEqual(result["protocol"]["train_examples"], 0)
        self.assertIn("Zero-shot ablation", tb.render_markdown([result], task, "x"))

    def test_system_one_gets_the_examples_in_front_of_the_input_inside_the_state(self):
        task = self._task().select("test")
        request = tb.SystemOneRunner("m", "http://x").request(task, "owl")
        self.assertIn("INPUT: bee!\nANSWER: kind=b, level=2, flag=true", request["state"])
        self.assertTrue(request["state"].endswith("NEW INPUT (decide this one):\nowl"))
        self.assertNotIn("INPUT: bee!", request["questions"]["level"]["instructions"])
        zero = tb.SystemOneRunner("m", "http://x").request(task.without_examples(), "owl")
        self.assertEqual(zero["state"], "owl")

    def test_llamacpp_shows_the_answer_as_the_option_letter(self):
        task = self._task().select("test")
        sent = []
        with patch.object(
            tb,
            "_post",
            side_effect=lambda u, payload, **k: (
                sent.append(payload) or {"choices": [{"message": {"content": "A"}}]}
            ),
        ):
            tb.LlamaCppRunner("m")._one(task, task.questions["kind"], "owl")
        prompt = sent[0]["messages"][0]["content"]
        self.assertIn("INPUT: bee!\nANSWER: B", prompt)  # kind "b" is option B
        self.assertIn("INPUT: cat\nANSWER: A", prompt)

    def test_a_task_without_train_items_runs_without_examples(self):
        doc = json.loads(json.dumps(MINI))
        for item in doc["items"]:
            item["split"] = "test"
        task = tb.load_task(write_task(doc)).select("test")
        self.assertEqual(task.examples, ())
        self.assertNotIn("EXAMPLES", tb._instructions(task, "bee!"))


class ShippedSuiteTests(unittest.TestCase):
    SUITES = ("message-routing", "mail-triage", "receipt-category", "schema-extraction")

    def test_every_suite_has_train_and_test_items_and_no_shared_text(self):
        for name in self.SUITES:
            task = tb.load_task(TASK_FILE.with_name(f"{name}.json"))
            train, test = task.select("train"), task.select("test")
            self.assertGreaterEqual(len(train.items), 16, name)
            self.assertGreaterEqual(len(test.items), 8, name)
            self.assertFalse(
                {i["state"] for i in train.items} & {i["state"] for i in test.items}, name
            )

    def test_every_shipped_suite_is_in_the_standard_protocol_by_default(self):
        for path in sorted(TASK_FILE.parent.glob("*.json")):
            task = tb.load_task(path)
            self.assertTrue(task.examples, f"{path.name} has no train examples")
            test = task.select("test")
            self.assertEqual(test.examples, task.examples, path.name)
            self.assertTrue(test.items, path.name)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"heldout"', text, f"{path.name} still uses the old split name")
            self.assertNotIn('"dev"', text, path.name)


class BayesTests(unittest.TestCase):
    def _task(self):
        doc = json.loads(json.dumps(MINI))
        doc["items"] += [
            {"state": "cat purr", "expected": {"kind": "a", "level": "1", "flag": False}},
            {"state": "cat nap", "expected": {"kind": "a", "level": "1", "flag": False}},
            {"state": "owl hoot", "expected": {"kind": "b", "level": "0", "flag": True}},
            {
                "state": "cat zzz",
                "expected": {"kind": "a", "level": "1", "flag": False},
                "split": "test",
            },
            {
                "state": "owl zzz",
                "expected": {"kind": "b", "level": "0", "flag": True},
                "split": "test",
            },
        ]
        return tb.load_task(write_task(doc))

    def test_the_prior_is_fitted_on_train_alone_and_sums_to_one(self):
        task = self._task().select("test")
        prior = tb.BayesPrior(task, task.examples)
        post = prior.posterior("cat zzz")
        for probs in post.values():
            self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertEqual(max(post["kind"], key=post["kind"].get), "a")
        self.assertNotIn("zzz", prior.vocab)  # test words are never seen

    def test_the_joint_makes_an_unseen_combination_unlikely(self):
        task = self._task().select("test")
        prior = tb.BayesPrior(task, task.examples)
        joint = prior.joint_prior()
        self.assertAlmostEqual(sum(joint.values()), 1.0)
        seen = max(joint.values())
        unseen = min(joint.values())
        self.assertGreater(seen, 3 * unseen)

    def test_the_bayes_runner_scores_test_items_and_leaves_one_out_on_train(self):
        task = self._task()
        result = tb.run(task.select("test"), tb.make_runner("bayes", task))
        self.assertEqual(result["runner"], "bayes")
        self.assertEqual(result["questions"]["kind"]["accuracy"], 1.0)
        train = task.select("train")
        runner = tb.make_runner("bayes", train)
        tb.run(train, runner)
        self.assertTrue(all(len(p.rows) == len(train.examples) - 1 for p in runner.cache.values()))

    def test_fusion_weighs_a_models_answer_against_the_prior(self):
        task = self._task().select("test")

        class Sure:
            name = "sure"

            def answer(self, task, state):
                return {qid: tb.Answer("a" if qid == "kind" else None) for qid in task.questions}

        fused = tb.make_runner("bayes:rules", task)
        self.assertEqual(fused.name, "bayes+rules")
        out = tb.BayesFusionRunner(Sure(), task).answer(task, "owl zzz")
        self.assertIn(out["kind"].value, ("a", "b"))
        self.assertAlmostEqual(sum(out["kind"].probabilities.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
