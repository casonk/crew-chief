"""Serving-policy review, launch checks, GGUF download verification, router validation.

These decide what gets served, launched and trusted: a policy entry without evidence is
an error, a launch against a model that cannot call tools fails early with the choices,
and a downloaded model file is accepted only if its size and SHA-256 are exactly the
recorded ones. All network access is replaced; downloads go to temporary directories.
"""

from __future__ import annotations

import hashlib
import io
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from crew_chief import code_launcher, gguf_sources, model_router
from crew_chief.serving_policy import (
    EVIDENCE_MAX_AGE_DAYS,
    ModelPolicy,
    PolicyError,
    ServingPolicy,
    TaskPolicy,
    load_policy,
    pulled_models,
    review,
)

TODAY = date(2026, 11, 2)


def write(text: str) -> Path:
    tmp = TemporaryDirectory()
    write.keep.append(tmp)
    path = Path(tmp.name) / "policy.toml"
    path.write_text(text, encoding="utf-8")
    return path


write.keep = []


class PolicyLoading(unittest.TestCase):
    def test_a_missing_file_and_bad_toml_are_policy_errors_naming_the_file(self):
        with self.assertRaisesRegex(PolicyError, "not found"):
            load_policy(Path("/nonexistent/policy.toml"))
        path = write("[models.m\n")
        with self.assertRaises(PolicyError) as raised:
            load_policy(path)
        self.assertIn(str(path), str(raised.exception))

    def test_speculative_decoding_and_drafts_need_the_llamacpp_backend(self):
        for body in (
            '[models."m"]\nspeculative = "ngram-mod"\n',
            '[models."m"]\nbackend = "ollama"\ndraft = "small"\n',
        ):
            with self.subTest(body=body), self.assertRaises(PolicyError):
                load_policy(write(body))

    def test_a_draft_must_be_text(self):
        with self.assertRaisesRegex(PolicyError, "draft must be a model name"):
            load_policy(write('[models."m"]\nbackend = "llamacpp"\ndraft = 5\n'))


class PolicyReview(unittest.TestCase):
    def review(self, models=(), tasks=(), root=None, **kwargs):
        policy = ServingPolicy(models={m.name: m for m in models}, tasks={t.name: t for t in tasks})
        return review(policy, root or Path("/nonexistent-repo"), today=TODAY, **kwargs)

    def test_a_default_model_needs_evidence_and_a_reviewed_date(self):
        errors, _ = self.review([ModelPolicy(name="m:1b", status="default")])
        self.assertTrue(any("no benchmark evidence" in e for e in errors))
        self.assertTrue(any("no reviewed date" in e for e in errors))

    def test_cited_evidence_must_exist(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "results").mkdir()
            (Path(tmp) / "results" / "ok.md").write_text("x", encoding="utf-8")
            model = ModelPolicy(
                name="m:1b", status="beta", reviewed="2026-10-30",
                evidence=("results/ok.md", "results/gone.md"),
            )  # fmt: skip
            errors, _ = self.review([model], root=Path(tmp))
        self.assertEqual(
            [e for e in errors if "evidence file missing" in e],
            ["m:1b (beta): evidence file missing: results/gone.md"],
        )

    def test_a_malformed_reviewed_date_is_an_error_and_a_stale_one_a_warning(self):
        bad = ModelPolicy(name="a:1b", status="beta", reviewed="yesterday", evidence=())
        errors, _ = self.review([bad])
        self.assertTrue(any("reviewed must be YYYY-MM-DD" in e for e in errors))
        stale_day = (TODAY - timedelta(days=EVIDENCE_MAX_AGE_DAYS + 1)).isoformat()
        fresh_day = (TODAY - timedelta(days=EVIDENCE_MAX_AGE_DAYS)).isoformat()
        stale = ModelPolicy(name="s:1b", status="default", reviewed=stale_day, evidence=("e",))
        fresh = ModelPolicy(name="f:1b", status="default", reviewed=fresh_day, evidence=("e",))
        _, warnings = self.review([stale, fresh])
        self.assertTrue(any("s:1b" in w and "re-benchmark" in w for w in warnings))
        self.assertFalse(any("f:1b" in w for w in warnings))

    def test_a_llamacpp_entry_needs_context_and_measured_memory_unless_retired(self):
        incomplete = ModelPolicy(name="l:1b", backend="llamacpp")
        errors, _ = self.review([incomplete])
        self.assertTrue(any("need context and gpu_mib" in e for e in errors))
        errors, _ = self.review([ModelPolicy(name="l:1b", backend="llamacpp", status="retired")])
        self.assertFalse(any("need context" in e for e in errors))

    def test_task_chains_must_name_live_models_and_cited_evidence_must_exist(self):
        models = [ModelPolicy(name="ok:1b"), ModelPolicy(name="old:1b", status="retired")]
        task = TaskPolicy(
            name="route", model="ok:1b", fallback=("old:1b", "ghost:1b"),
            evidence=("results/gone.md",),
        )  # fmt: skip
        errors, _ = self.review(models, [task])
        self.assertTrue(any("evidence file missing: results/gone.md" in e for e in errors))
        self.assertTrue(any("old:1b is retired" in e for e in errors))
        self.assertTrue(any("ghost:1b is not in the serving policy" in e for e in errors))

    def test_a_systemone_task_warns_that_fallbacks_are_ignored(self):
        task = TaskPolicy(name="gate", model="ok:1b", runner="systemone", fallback=("ok:1b",))
        _, warnings = self.review([ModelPolicy(name="ok:1b")], [task])
        self.assertTrue(any("fallback models are ignored" in w for w in warnings))

    def test_drift_against_what_ollama_has_pulled(self):
        models = [
            ModelPolicy(name="listed:1b"),
            ModelPolicy(name="missing:1b"),
            ModelPolicy(name="old:1b", status="retired"),
            ModelPolicy(name="cold:1b"),
        ]
        errors, warnings = self.review(
            models,
            pulled=["listed:1b", "old:1b", "unlisted:1b", "cold:1b"],
            below_hot={"cold:1b": "warm"},
        )
        self.assertEqual(
            errors, ["unlisted:1b: pulled in Ollama but missing from the serving policy"]
        )
        joined = "\n".join(warnings)
        self.assertIn("missing:1b: in the policy but not pulled", joined)
        self.assertIn("old:1b: retired but still on hot storage", joined)
        self.assertIn("cold:1b: unreviewed but stored in warm", joined)
        self.assertNotIn("listed:1b", joined)

    def test_without_a_pulled_list_there_is_no_drift_check(self):
        _, warnings = self.review([ModelPolicy(name="missing:1b")])
        self.assertEqual(warnings, [])


class PulledModels(unittest.TestCase):
    def test_names_are_read_from_the_tags_endpoint(self):
        reply = io.BytesIO(b'{"models": [{"name": "a:1"}, {"name": "b:2"}]}')
        reply.__enter__ = lambda self=reply: self
        reply.__exit__ = lambda *a: False
        with mock.patch(
            "crew_chief.serving_policy.urllib.request.urlopen", return_value=reply
        ) as urlopen:
            self.assertEqual(pulled_models("http://h:1"), ["a:1", "b:2"])
        self.assertEqual(urlopen.call_args.args[0], "http://h:1/api/tags")

    def test_an_unreachable_ollama_is_a_policy_error_naming_the_url(self):
        for error in (urllib.error.URLError("down"), OSError("reset")):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch("crew_chief.serving_policy.urllib.request.urlopen", side_effect=error),
                self.assertRaisesRegex(PolicyError, "not reachable at http://h:1"),
            ):
                pulled_models("http://h:1")


class LaunchChecks(unittest.TestCase):
    def test_an_unreachable_ollama_stops_the_launch_with_how_to_start_it(self):
        with mock.patch.object(
            code_launcher, "_get_json", side_effect=urllib.error.URLError("refused")
        ):
            with self.assertRaisesRegex(code_launcher.LaunchError, "not reachable.*start.sh"):
                code_launcher.ollama_tool_models("http://h:1")

    def test_only_models_that_advertise_tool_calling_are_usable_and_a_failing_probe_skips_one(self):
        def get(url, timeout, payload=None):
            if url.endswith("/api/tags"):
                return {
                    "models": [{"name": "b:1"}, {"name": "a:1"}, {"name": "c:1"}, {"name": "d:1"}]
                }
            return {
                "a:1": {"capabilities": ["completion", "tools"]},
                "b:1": {"capabilities": ["completion"]},
                "d:1": {"capabilities": ["tools"]},
            }.get(payload["model"]) or (_ for _ in ()).throw(urllib.error.URLError("boom"))

        with mock.patch.object(code_launcher, "_get_json", side_effect=get):
            self.assertEqual(code_launcher.ollama_tool_models("http://h:1"), ["a:1", "d:1"])

    def test_a_model_that_cannot_call_tools_is_refused_with_the_choices(self):
        with mock.patch.object(code_launcher, "ollama_tool_models", return_value=["a:1", "b:1"]):
            with self.assertRaises(code_launcher.LaunchError) as raised:
                code_launcher.check_model("ollama", "http://h:1", "other:9")
        self.assertIn("a:1", str(raised.exception))
        self.assertIn("b:1", str(raised.exception))
        with mock.patch.object(code_launcher, "ollama_tool_models", return_value=[]):
            with self.assertRaisesRegex(code_launcher.LaunchError, r"\(none\)"):
                code_launcher.check_model("ollama", "http://h:1", "x:1")

    def test_a_listed_tool_model_passes(self):
        with mock.patch.object(code_launcher, "ollama_tool_models", return_value=["a:1"]):
            code_launcher.check_model("ollama", "http://h:1", "a:1")

    def test_llamacpp_is_checked_for_reachability_only(self):
        with mock.patch.object(code_launcher, "_get_json", return_value={}) as get:
            code_launcher.check_model("llamacpp", "http://h:2", "m:1")
        self.assertEqual(get.call_args.args[0], "http://h:2/health")
        with mock.patch.object(code_launcher, "_get_json", side_effect=OSError("refused")):
            with self.assertRaisesRegex(code_launcher.LaunchError, "crew-chief serve m:1"):
                code_launcher.check_model("llamacpp", "http://h:2", "m:1")


class Response:
    def __init__(self, data: bytes, status: int = 200):
        self._io, self.status = io.BytesIO(data), status

    def read(self, n=-1):
        return self._io.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class GgufDownload(unittest.TestCase):
    def source(self, data: bytes, **overrides):
        base = dict(
            model="m:1b",
            repo="org/repo",
            file="m.gguf",
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
        )
        return gguf_sources.GgufSource(**{**base, **overrides})

    def fetch(self, source, directory, opener):
        return gguf_sources.fetch(source, directory, log=lambda line: None, opener=opener)

    def test_a_good_download_is_verified_and_moved_into_place(self):
        data = b"model-weights" * 10
        with TemporaryDirectory() as tmp:
            path = self.fetch(
                self.source(data), Path(tmp) / "gguf", lambda request, timeout: Response(data)
            )
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["m.gguf"])

    def test_the_wrong_size_is_refused_and_nothing_is_published(self):
        data = b"model-weights"
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "gguf"
            with self.assertRaisesRegex(gguf_sources.SourceError, "got 5 bytes"):
                self.fetch(
                    self.source(data), directory, lambda request, timeout: Response(b"short")
                )
            self.assertFalse((directory / "m.gguf").exists())

    def test_a_checksum_mismatch_discards_the_download(self):
        data = b"model-weights"
        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "gguf"
            tampered = b"MODEL-WEIGHTS"
            with self.assertRaisesRegex(gguf_sources.SourceError, "SHA-256 mismatch"):
                self.fetch(
                    self.source(data), directory, lambda request, timeout: Response(tampered)
                )
            self.assertEqual(list(directory.iterdir()), [])

    def test_a_partial_file_is_resumed_with_a_range_request(self):
        data = b"0123456789"
        seen = {}

        def opener(request, timeout):
            seen["range"] = request.get_header("Range")
            return Response(data[4:], status=206)

        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "m.gguf.partial").write_bytes(data[:4])
            path = self.fetch(self.source(data), directory, opener)
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(seen["range"], "bytes=4-")

    def test_a_server_that_ignores_range_restarts_the_file_instead_of_appending(self):
        data = b"0123456789"
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "m.gguf.partial").write_bytes(data[:4])
            path = self.fetch(
                self.source(data), directory, lambda request, timeout: Response(data, status=200)
            )
            self.assertEqual(path.read_bytes(), data)

    def test_a_complete_partial_file_is_verified_without_downloading(self):
        data = b"0123456789"
        opener = mock.Mock(side_effect=AssertionError("must not download"))
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "m.gguf.partial").write_bytes(data)
            self.assertEqual(self.fetch(self.source(data), Path(tmp), opener).read_bytes(), data)

    def test_the_directory_is_hot_unless_a_lower_tier_is_named(self):
        tiers = {"hot": Path("/h"), "warm": Path("/w"), "cold": Path("/c")}
        self.assertEqual(gguf_sources.gguf_dir("hot", tiers), gguf_sources.HOT_GGUF_DIR)
        self.assertEqual(gguf_sources.gguf_dir("warm", None), gguf_sources.HOT_GGUF_DIR)
        self.assertEqual(gguf_sources.gguf_dir("warm", tiers), Path("/w/gguf"))

    def test_the_sources_file_must_be_readable_toml(self):
        with self.assertRaises(gguf_sources.SourceError):
            gguf_sources.load_sources(Path("/nonexistent/sources.toml"))
        with self.assertRaises(gguf_sources.SourceError):
            gguf_sources.load_sources(write("[models\n"))


class RouterValidation(unittest.TestCase):
    def route(self, **overrides):
        kwargs = dict(
            task={"name": "t", "prompt": "p", "test_command": "pytest", "editable_paths": []},
            repo="r", candidates=["a", "b"], fallback="a", router_model="rm", url="http://h",
        )  # fmt: skip
        kwargs.update(overrides)
        return model_router.route_test_repair(**kwargs)

    def test_bad_inputs_are_refused_before_any_model_is_asked(self):
        with mock.patch.object(model_router, "SystemOneRunner") as runner:
            for overrides, message in (
                ({"candidates": ["a"]}, "at least two"),
                ({"candidates": ["a", "a"]}, "at least two"),
                ({"fallback": "z"}, "fallback must be one"),
                ({"min_confidence": -0.1}, "between 0 and 1"),
                ({"min_confidence": 1.5}, "between 0 and 1"),
                ({"min_confidence": float("nan")}, "between 0 and 1"),
                ({"min_confidence": float("inf")}, "between 0 and 1"),
                ({"timeout": 0}, "timeout must be positive"),
            ):
                with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                    self.route(**overrides)
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
