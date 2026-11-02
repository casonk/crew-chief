"""Hosted-provider error classes, runner dispatch, task loading, scoring and store guards.

A hosted API that rejects the key is *unavailable* (a chain moves on), any other API error
is raised with the provider's message; a runner spec picks exactly one runner and reads its
URL from the environment; a bad scoring profile or task file is a named error. Network
access is replaced everywhere.
"""

from __future__ import annotations

import io
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crew_chief import resultstore, scoring, taskbench
from crew_chief.providers.anthropic import AnthropicProvider
from crew_chief.providers.base import ProviderUnavailableError
from crew_chief.providers.openai import OpenAIProvider


def http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.example", code, "x", {}, io.BytesIO(body))  # type: ignore[arg-type]


class HostedApiErrors(unittest.TestCase):
    CASES = (
        (AnthropicProvider, "crew_chief.providers.anthropic.urllib.request.urlopen"),
        (OpenAIProvider, "crew_chief.providers.openai.urllib.request.urlopen"),
    )

    def call(self, cls, target, error):
        provider = cls(api_key="k")
        with mock.patch(target, side_effect=error):
            return provider._post("/x", {})

    def test_a_rejected_key_is_unavailable_so_a_chain_moves_on(self):
        for cls, target in self.CASES:
            for code in (401, 403):
                with (
                    self.subTest(provider=cls.__name__, code=code),
                    self.assertRaises(ProviderUnavailableError) as raised,
                ):
                    self.call(cls, target, http_error(code, b'{"error": {"message": "bad key"}}'))
                self.assertIn("bad key", str(raised.exception))
                self.assertIn(str(code), str(raised.exception))

    def test_any_other_api_error_is_raised_with_the_providers_message(self):
        for cls, target in self.CASES:
            with self.subTest(provider=cls.__name__), self.assertRaises(RuntimeError) as raised:
                self.call(cls, target, http_error(429, b'{"error": {"message": "slow down"}}'))
            self.assertNotIsInstance(raised.exception, ProviderUnavailableError)
            self.assertIn("429", str(raised.exception))
            self.assertIn("slow down", str(raised.exception))

    def test_a_body_that_is_not_json_is_quoted_as_it_is(self):
        for cls, target in self.CASES:
            with (
                self.subTest(provider=cls.__name__),
                self.assertRaisesRegex(RuntimeError, "gateway on fire"),
            ):
                self.call(cls, target, http_error(502, b"gateway on fire"))

    def test_a_json_body_without_an_error_object_falls_back_to_the_text(self):
        for cls, target in self.CASES:
            with self.subTest(provider=cls.__name__), self.assertRaisesRegex(RuntimeError, "oops"):
                self.call(cls, target, http_error(500, b'{"detail": "oops"}'))

    def test_the_key_is_sent_in_the_documented_header_and_never_in_an_error(self):
        for cls, target in self.CASES:
            provider = cls(api_key="SECRET-KEY")
            with (
                mock.patch(target, side_effect=http_error(500, b"boom")) as urlopen,
                self.assertRaises(RuntimeError) as raised,
            ):
                provider._post("/x", {})
            headers = {k.lower(): v for k, v in urlopen.call_args.args[0].header_items()}
            self.assertTrue(
                "SECRET-KEY" in headers.get("x-api-key", headers.get("authorization", ""))
            )
            self.assertNotIn("SECRET-KEY", str(raised.exception))


class MakeRunner(unittest.TestCase):
    def task(self):
        return mock.Mock()

    def test_each_spec_picks_one_kind_of_runner(self):
        task = self.task()
        self.assertIsInstance(taskbench.make_runner("rules", task), taskbench.RulesRunner)
        self.assertIsInstance(taskbench.make_runner("bayes", task), taskbench.BayesRunner)
        fused = taskbench.make_runner("bayes:rules", task)
        self.assertIsInstance(fused, taskbench.BayesFusionRunner)
        self.assertIsInstance(taskbench.make_runner("ollama:m:1b", task), taskbench.OllamaRunner)
        self.assertIsInstance(taskbench.make_runner("llamacpp:m", task), taskbench.LlamaCppRunner)
        self.assertIsInstance(
            taskbench.make_runner("systemone:clef", task), taskbench.SystemOneRunner
        )

    def test_urls_come_from_the_environment_with_local_defaults(self):
        with mock.patch.dict(
            "os.environ",
            {
                "CREW_CHIEF_URL": "http://ollama.test:1/",
                "CREW_CHIEF_LLAMACPP_URL": "http://llama.test:2",
            },
        ):
            self.assertEqual(
                taskbench.make_runner("ollama:m", self.task()).url, "http://ollama.test:1"
            )
            self.assertEqual(
                taskbench.make_runner("llamacpp:m", self.task()).url, "http://llama.test:2"
            )
            self.assertEqual(
                taskbench.make_runner("systemone:m", self.task()).url,
                "http://ollama.test:1/v1/systemone",
            )

    def test_a_runner_that_needs_an_argument_or_a_key_is_refused_by_name(self):
        for spec in ("", "ollama", "ollama:", "llamacpp:", "systemone:", "nonsense", "nonsense:x"):
            with (
                self.subTest(spec=spec),
                self.assertRaisesRegex(taskbench.TaskError, "unknown runner"),
            ):
                taskbench.make_runner(spec, self.task())
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TYPESAFE_API_KEY", None)
            with self.assertRaisesRegex(taskbench.TaskError, "TYPESAFE_API_KEY"):
                taskbench.make_runner("jev", self.task())

    def test_the_hosted_jev_runner_takes_its_key_and_model_from_the_spec_and_environment(self):
        with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "k"}):
            runner = taskbench.make_runner("jev:jev-next", self.task())
        self.assertIsInstance(runner, taskbench.JevRunner)


class TaskLoading(unittest.TestCase):
    def test_a_missing_or_corrupt_task_file_is_a_task_error_naming_it(self):
        with TemporaryDirectory() as tmp:
            absent = Path(tmp) / "absent.json"
            with self.assertRaises(taskbench.TaskError) as raised:
                taskbench.load_task(absent)
            self.assertIn(str(absent), str(raised.exception))
            bad = Path(tmp) / "bad.json"
            bad.write_text("{nope", encoding="utf-8")
            with self.assertRaises(taskbench.TaskError):
                taskbench.load_task(bad)


class ResultEntries(unittest.TestCase):
    def test_a_result_without_latency_or_accuracy_has_no_entry_and_no_score(self):
        profile = scoring.profile_from_dict(
            "p", {"accuracy_weight": 0.5, "target_ms": 1, "ceiling_ms": 9}
        )
        for result in (
            {"questions": {}},
            {"questions": {"q": {"accuracy": None}}, "latency_ms_mean": 1, "latency_ms_p90": 2},
            {"questions": {"q": {"accuracy": 0.9}}},
        ):
            with self.subTest(result=result):
                self.assertIsNone(taskbench.result_entry(result))
                self.assertEqual(taskbench.result_score(result, profile), "—")

    def test_a_scored_result_formats_to_three_places_or_says_it_was_gated(self):
        result = {
            "questions": {"q": {"accuracy": 0.9}},
            "latency_ms_mean": 5.0,
            "latency_ms_p90": 6.0,
        }
        open_profile = scoring.profile_from_dict(
            "p", {"accuracy_weight": 0.5, "target_ms": 1, "ceiling_ms": 9}
        )
        gated = scoring.profile_from_dict(
            "g", {"accuracy_weight": 0.5, "target_ms": 1, "ceiling_ms": 9, "min_accuracy": 0.99}
        )
        self.assertRegex(taskbench.result_score(result, open_profile), r"^\d\.\d{3}$")
        self.assertEqual(taskbench.result_score(result, gated), "gated")


class ScoringProfileGuards(unittest.TestCase):
    BASE = {"accuracy_weight": 0.5, "target_ms": 10, "ceiling_ms": 100}

    def test_each_out_of_range_field_is_refused_by_name(self):
        for change, message in (
            ({"min_accuracy": 1.5}, "min_accuracy must be between 0 and 1"),
            ({"min_accuracy": -0.1}, "min_accuracy"),
            ({"max_p90_ms": 0}, "max_p90_ms must be positive"),
            ({"max_p90_ms": -5}, "max_p90_ms must be positive"),
            ({"tie_margin": -0.01}, "tie_margin cannot be negative"),
            ({"accuracy_weight": 1.1}, "accuracy_weight must be between 0 and 1"),
            ({"target_ms": 100, "ceiling_ms": 10}, "0 < target_ms < ceiling_ms"),
            ({"target_ms": "fast"}, "target_ms must be a number"),
            ({"target_ms": True}, "target_ms must be a number"),
            ({"target_ms": float("inf")}, "target_ms must be a number"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(scoring.ScoringError, message):
                scoring.profile_from_dict("p", {**self.BASE, **change})

    def test_a_missing_or_malformed_profiles_file_is_a_scoring_error_naming_it(self):
        with TemporaryDirectory() as tmp:
            absent = Path(tmp) / "absent.toml"
            with self.assertRaisesRegex(scoring.ScoringError, "not found"):
                scoring.load_profiles(absent)
            bad = Path(tmp) / "bad.toml"
            bad.write_text("[profiles.x\n", encoding="utf-8")
            with self.assertRaises(scoring.ScoringError) as raised:
                scoring.load_profiles(bad)
            self.assertIn(str(bad), str(raised.exception))


class ResultStoreGuards(unittest.TestCase):
    def test_an_unknown_measure_column_is_refused_and_writes_nothing(self):
        conn = resultstore.connect()
        with self.assertRaisesRegex(ValueError, "unknown measure column.*bogus"):
            resultstore._measure(conn, 1, "performer", bogus=1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM measures").fetchone()[0], 0)

    def test_a_store_from_an_older_schema_is_rebuilt_not_trusted(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.sqlite"
            conn = resultstore.connect(path)
            conn.execute("PRAGMA user_version = 0")
            conn.execute("CREATE TABLE IF NOT EXISTS marker(x)")
            conn.commit()
            conn.close()
            conn = resultstore.connect(path)
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], resultstore.SCHEMA_VERSION
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
