"""Tests for crew_chief.serving_policy and its use by `crew-chief code` — offline."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from crew_chief.code_launcher import resolve_serving
from crew_chief.serving_policy import (
    DEFAULT_POLICY_PATH,
    REPO_ROOT,
    ModelPolicy,
    PolicyError,
    ServingPolicy,
    load_policy,
    review,
)

TODAY = date(2026, 10, 21)


def _write(body: str) -> Path:
    tmp = TemporaryDirectory()
    path = Path(tmp.name) / "policy.toml"
    path.write_text(body, encoding="utf-8")
    _write.keep.append(tmp)  # keep the directory alive for the test run
    return path


_write.keep = []


class LoadTests(unittest.TestCase):
    def test_tracked_policy_is_valid_and_its_evidence_exists(self):
        policy = load_policy(DEFAULT_POLICY_PATH)
        errors, _ = review(policy, REPO_ROOT, today=TODAY)
        self.assertEqual(errors, [])
        self.assertEqual(policy.get("qwen3:32b").backend, "llamacpp")

    def test_rejects_unknown_values_and_keys(self):
        for body in (
            '[models."m"]\nstatus = "great"\n',
            '[models."m"]\nbackend = "vllm"\n',
            '[models."m"]\nkv_cache = "q2"\n',
            '[models."m"]\nbackend = "llamacpp"\nspeculative = "magic"\n',
            '[models."m"]\nbackend = "ollama"\nspeculative = "ngram-mod"\n',
            '[models."m"]\nbackend = "ollama"\ndraft = "d"\n',
            '[models."m"]\nbackend = "llamacpp"\ndraft = "d"\nspeculative = "ngram-mod"\n',
            '[models."m"]\nbackend = "llamacpp"\ndraft = "d"\ndraft_tokens = "many"\n',
            '[models."m"]\ncontext = "big"\n',
            '[models."m"]\nspeed = 9\n',
            '[models."m"]\nevidence = "one.md"\n',
        ):
            with self.subTest(body=body), self.assertRaises(PolicyError):
                load_policy(_write(body))

    def test_speculative_accepted_for_llamacpp(self):
        policy = load_policy(
            _write('[models."m"]\nbackend = "llamacpp"\nspeculative = "ngram-mod"\n')
        )
        self.assertEqual(policy.get("m").speculative, "ngram-mod")

    def test_draft_defaults_to_eight_tokens(self):
        policy = load_policy(_write('[models."m"]\nbackend = "llamacpp"\ndraft = "d"\n'))
        self.assertEqual((policy.get("m").draft, policy.get("m").draft_tokens), ("d", 8))

    def test_missing_file(self):
        with self.assertRaises(PolicyError):
            load_policy(Path("/nonexistent/policy.toml"))


class ReviewTests(unittest.TestCase):
    def policy(self, *models: ModelPolicy) -> ServingPolicy:
        return ServingPolicy(models={m.name: m for m in models})

    def test_reviewed_entries_need_evidence_and_a_date(self):
        errors, _ = review(self.policy(ModelPolicy("m", status="default")), today=TODAY)
        self.assertTrue(any("no benchmark evidence" in e for e in errors))
        self.assertTrue(any("no reviewed date" in e for e in errors))

    def test_llamacpp_entries_need_context_and_gpu_memory(self):
        entry = ModelPolicy("m", backend="llamacpp")
        errors, _ = review(self.policy(entry), today=TODAY)
        self.assertTrue(any("context and gpu_mib" in e for e in errors))

    def test_missing_evidence_file_and_stale_review(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.md").write_text("x")
            entry = ModelPolicy(
                "m", status="beta", evidence=("ok.md", "gone.md"), reviewed="2026-01-01"
            )
            errors, warnings = review(self.policy(entry), root, today=TODAY)
        self.assertEqual(errors, ["m (beta): evidence file missing: gone.md"])
        self.assertTrue(any("re-benchmark" in w for w in warnings))

    def test_drift_against_pulled_models(self):
        policy = self.policy(
            ModelPolicy("listed"),
            ModelPolicy("not-pulled"),
            ModelPolicy("old", status="retired"),
        )
        errors, warnings = review(policy, pulled=["listed", "old", "new"], today=TODAY)
        self.assertEqual(errors, ["new: pulled in Ollama but missing from the serving policy"])
        self.assertIn("not-pulled: in the policy but not pulled", warnings)
        self.assertIn(
            "old: retired but still on hot storage; run `crew-chief storage apply`", warnings
        )


class StubDriftTests(unittest.TestCase):
    def test_stubs_of_retired_models_are_expected_and_unretired_ones_flagged(self):
        policy = ServingPolicy(
            models={
                "old": ModelPolicy("old", status="retired"),
                "back": ModelPolicy("back", status="unreviewed"),
            }
        )
        _, warnings = review(
            policy,
            pulled=["old", "back"],
            today=TODAY,
            below_hot={"old:latest": "warm", "back:latest": "cold"},
        )
        self.assertFalse(any(w.startswith("old:") for w in warnings))
        self.assertIn(
            "back: unreviewed but stored in cold; run `crew-chief storage restore back`", warnings
        )


class CanonicalNameTests(unittest.TestCase):
    def test_untagged_names_mean_latest(self):
        policy = ServingPolicy(models={"nimble": ModelPolicy("nimble", status="unreviewed")})
        errors, warnings = review(policy, pulled=["nimble:latest"], today=TODAY)
        self.assertEqual((errors, warnings), ([], []))
        self.assertIs(policy.get("nimble:latest"), policy.models["nimble"])
        self.assertIsNone(policy.get("nimble:9b"))


class ResolveTests(unittest.TestCase):
    POLICY = ServingPolicy(
        models={
            "big": ModelPolicy("big", status="beta", backend="llamacpp", context=32768),
            "small": ModelPolicy("small", status="default", backend="ollama"),
            "fresh": ModelPolicy("fresh"),
            "gone": ModelPolicy("gone", status="retired"),
        },
        backend_urls={"llamacpp": "http://localhost:9999"},
    )

    def resolve(self, model, **kwargs):
        return resolve_serving(model, policy_loader=lambda: self.POLICY, **kwargs)

    def test_policy_picks_backend_url_and_context(self):
        backend, url, context, notes = self.resolve("big")
        self.assertEqual((backend, url, context), ("llamacpp", "http://localhost:9999", 32768))
        self.assertEqual(notes, [])

    def test_explicit_arguments_override_with_a_note(self):
        backend, url, context, notes = self.resolve(
            "big", backend="ollama", url="http://x", context=8192
        )
        self.assertEqual((backend, url, context), ("ollama", "http://x", 8192))
        self.assertTrue(any("overriding" in n for n in notes))

    def test_unlisted_and_unreviewed_models_get_notes(self):
        self.assertTrue(any("not in the serving policy" in n for n in self.resolve("other")[3]))
        self.assertTrue(any("unreviewed" in n for n in self.resolve("fresh")[3]))

    def test_retired_model_is_served_with_a_note(self):
        backend, _, _, notes = self.resolve("gone")
        self.assertEqual(backend, "ollama")
        self.assertTrue(any("retired" in n and "slower storage" in n for n in notes))

    def test_unreadable_policy_never_blocks(self):
        def broken():
            raise PolicyError("nope")

        backend, url, _, notes = resolve_serving("x", policy_loader=broken)
        self.assertEqual((backend, url), ("ollama", "http://localhost:11434"))
        self.assertTrue(any("unavailable" in n for n in notes))


if __name__ == "__main__":
    unittest.main()


TASK_POLICY = """
[models."a:1"]
status = "default"
evidence = ["results/e.md"]
reviewed = "2026-10-01"

[models."b:1"]
status = "retired"

[tasks."code"]
status = "beta"
model = "a:1"
fallback = ["a:1"]
evidence = ["results/e.md"]
reviewed = "2026-10-01"
"""


class TaskRoutingTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "results").mkdir()
        (Path(tmp.name) / "results" / "e.md").write_text("x")
        return Path(tmp.name)

    def test_a_task_gives_an_ordered_chain(self):
        policy = load_policy(_write(TASK_POLICY))
        self.assertEqual(policy.task("code").chain, ["a:1", "a:1"])
        self.assertEqual(review(policy, self._root(), today=TODAY), ([], []))

    def test_task_chain_only_serves_chat_tasks(self):
        from crew_chief.serving_policy import task_chain

        chat = load_policy(_write(TASK_POLICY))
        self.assertEqual(task_chain("code", lambda: chat), ["a:1", "a:1"])
        self.assertEqual(task_chain("other", lambda: chat), [])
        decision = load_policy(
            _write(
                TASK_POLICY.replace(
                    'status = "beta"\nmodel', 'status = "beta"\nrunner = "systemone"\nmodel'
                )
            )
        )
        self.assertEqual(task_chain("code", lambda: decision), [])

    def test_unreadable_policy_yields_no_chain(self):
        from crew_chief.serving_policy import task_chain

        def boom():
            raise PolicyError("nope")

        self.assertEqual(task_chain("code", boom), [])

    def test_review_flags_missing_evidence_unknown_and_retired_models(self):
        policy = load_policy(
            _write(TASK_POLICY.replace('fallback = ["a:1"]', 'fallback = ["b:1", "c:1"]'))
        )
        errors, _ = review(policy, self._root(), today=TODAY)
        self.assertTrue(any("b:1 is retired" in e for e in errors))
        self.assertTrue(any("c:1 is not in the serving policy" in e for e in errors))
        bare = load_policy(
            _write(TASK_POLICY.split("[tasks")[0] + '[tasks."t"]\nstatus = "beta"\nmodel = "a:1"\n')
        )
        errors, _ = review(bare, self._root(), today=TODAY)
        self.assertIn("task t (beta): no taskbench evidence cited", errors)

    def test_invalid_tasks_are_rejected(self):
        for bad in ('runner = "magic"', 'status = "retired"', "bogus = 1", "fallback = 3"):
            with self.assertRaises(PolicyError, msg=bad):
                load_policy(_write(f'[tasks."t"]\nmodel = "a:1"\n{bad}\n'))
        with self.assertRaises(PolicyError):
            load_policy(_write('[tasks."t"]\nstatus = "beta"\n'))

    def test_the_shipped_policy_routes_message_routing(self):
        policy = load_policy(DEFAULT_POLICY_PATH)
        self.assertEqual(policy.task("message-routing").runner, "systemone")
        self.assertEqual(review(policy, REPO_ROOT, today=TODAY)[0], [])
