"""Choosing, building and keying providers: the factory and the API-key lookup.

Keys come from the environment first, then from the password manager through a
subprocess. Every test stubs that subprocess: none of them may reach the real vault.
"""

from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from crew_chief import providers
from crew_chief.providers import (
    FallbackProvider,
    ProviderUnavailableError,
    _build_single_provider,
    _resolve_api_key,
    build_provider,
    get_provider,
)


class FakeProvider:
    def __init__(self, result="ok", error: Exception | None = None, **attributes) -> None:
        self.result, self.error = result, error
        self.prompts: list[str] = []
        for key, value in attributes.items():
            setattr(self, key, value)

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result

    def chat(self, messages, tools=None, system=None):
        if self.error:
            raise self.error
        return self.result


class FallbackGenerate(unittest.TestCase):
    def test_the_first_provider_that_answers_wins_and_the_rest_are_not_asked(self) -> None:
        first, second = FakeProvider("one"), FakeProvider("two")
        self.assertEqual(FallbackProvider([first, second]).generate("hi"), "one")
        self.assertEqual(second.prompts, [])

    def test_an_unavailable_or_failing_provider_hands_over_to_the_next(self) -> None:
        for error in (ProviderUnavailableError("down"), RuntimeError("boom"), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                chain = FallbackProvider([FakeProvider(error=error), FakeProvider("rescued")])
                self.assertEqual(chain.generate("hi"), "rescued")

    def test_when_every_provider_fails_the_last_error_is_raised(self) -> None:
        chain = FallbackProvider(
            [FakeProvider(error=RuntimeError("first")), FakeProvider(error=ValueError("last"))]
        )
        with self.assertRaisesRegex(ValueError, "last"):
            chain.generate("hi")

    def test_every_provider_is_given_the_same_prompt(self) -> None:
        a, b = FakeProvider(error=RuntimeError("x")), FakeProvider("fine")
        FallbackProvider([a, b]).generate("the prompt")
        self.assertEqual((a.prompts, b.prompts), (["the prompt"], ["the prompt"]))

    def test_a_chat_records_which_provider_answered_and_whether_it_reports_tool_use(self) -> None:
        class Reporting(FakeProvider):
            pass

        chain = FallbackProvider(
            [FakeProvider(error=ProviderUnavailableError("x")), Reporting(reports_tool_use=False)]
        )
        chain.chat([])
        self.assertEqual(chain.last_provider_name, "Reporting")
        self.assertIs(chain.last_reports_tool_use, False)
        chain.providers = [FakeProvider()]
        chain.chat([])
        self.assertIs(chain.last_reports_tool_use, True)

    def test_a_failed_chat_forgets_the_previous_winner(self) -> None:
        chain = FallbackProvider([FakeProvider()])
        chain.chat([])
        chain.providers = [FakeProvider(error=RuntimeError("down"))]
        with self.assertRaises(RuntimeError):
            chain.chat([])
        self.assertEqual(chain.last_provider_name, "")
        self.assertIsNone(chain.last_reports_tool_use)


class ResolveApiKey(unittest.TestCase):
    def setUp(self) -> None:
        env = mock.patch.dict("os.environ", {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        import os

        os.environ.pop("CC_TEST_KEY", None)
        self.run_process = mock.patch("subprocess.run").start()
        self.addCleanup(mock.patch.stopall)

    def answer(self, returncode=0, stdout="", stderr=""):
        self.run_process.return_value = SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr
        )

    def test_the_environment_wins_and_the_password_manager_is_not_asked(self) -> None:
        with mock.patch.dict("os.environ", {"CC_TEST_KEY": "from-env"}):
            self.assertEqual(_resolve_api_key("CC_TEST_KEY", "entry"), "from-env")
        self.run_process.assert_not_called()

    def test_with_no_entry_there_is_no_lookup_and_no_key(self) -> None:
        self.assertEqual(_resolve_api_key("CC_TEST_KEY", ""), "")
        self.run_process.assert_not_called()

    def test_the_entry_is_fetched_as_a_password_field_with_a_timeout(self) -> None:
        self.answer(stdout="  s3cret \n")
        self.assertEqual(_resolve_api_key("CC_TEST_KEY", "entry-two"), "s3cret")
        self.assertEqual(
            self.run_process.call_args.args[0],
            ["auto-pass", "get", "entry-two", "--field", "password"],
        )
        self.assertEqual(self.run_process.call_args.kwargs["timeout"], 15)
        self.assertTrue(self.run_process.call_args.kwargs["capture_output"])

    def test_an_env_file_is_passed_before_the_subcommand(self) -> None:
        self.answer(stdout="k")
        _resolve_api_key("CC_TEST_KEY", "e", "/x/auto-pass.env.local")
        self.assertEqual(
            self.run_process.call_args.args[0][:3],
            ["auto-pass", "--env-file", "/x/auto-pass.env.local"],
        )
        self.assertEqual(self.run_process.call_args.args[0][3:5], ["get", "e"])

    def test_a_failed_or_empty_lookup_is_no_key(self) -> None:
        for returncode, stdout in ((1, ""), (2, "partial"), (0, ""), (0, "   \n")):
            self.answer(returncode=returncode, stdout=stdout, stderr="denied")
            with self.subTest(returncode=returncode, stdout=stdout):
                self.assertEqual(_resolve_api_key("CC_TEST_KEY", "e"), "")

    def test_a_missing_binary_or_any_other_failure_is_no_key_not_a_crash(self) -> None:
        for error in (
            FileNotFoundError("auto-pass"),
            subprocess.TimeoutExpired("auto-pass", 15),
            PermissionError("denied"),
        ):
            self.run_process.side_effect = error
            with self.subTest(error=type(error).__name__):
                self.assertEqual(_resolve_api_key("CC_TEST_KEY", "e"), "")

    def test_the_secret_is_never_logged(self) -> None:
        self.answer(stdout="TOPSECRET")
        with self.assertLogs("crew_chief.providers", level="DEBUG") as logs:
            _resolve_api_key("CC_TEST_KEY", "entry-two")
        self.assertNotIn("TOPSECRET", "\n".join(logs.output))


def cfg(**kwargs):
    base = {
        "provider": "ollama",
        "base_url": "http://ollama:11434",
        "model": "default-model",
        "timeout_seconds": 42,
        "task_chains": {},
        "ollama_model_chain": [],
    }
    return SimpleNamespace(**{**base, **kwargs})


class Factory(unittest.TestCase):
    def setUp(self) -> None:
        self.classes = {
            name: mock.patch.object(providers, name).start()
            for name in (
                "OllamaProvider",
                "ClaudeCliProvider",
                "CodexCliProvider",
                "AnthropicProvider",
                "OpenAIProvider",
            )
        }
        self.addCleanup(mock.patch.stopall)
        self.policy_chain = mock.patch.object(
            providers, "_policy_task_chain", return_value=[]
        ).start()
        self.key = mock.patch.object(providers, "_resolve_api_key", return_value="KEY").start()

    def ollama_models(self, provider) -> list[str]:
        return [c.kwargs["model"] for c in self.classes["OllamaProvider"].call_args_list]

    def test_ollama_alone_uses_the_configured_model_url_and_timeout(self) -> None:
        provider = _build_single_provider("ollama", cfg())
        self.assertIs(provider, self.classes["OllamaProvider"].return_value)
        self.classes["OllamaProvider"].assert_called_once_with(
            base_url="http://ollama:11434", model="default-model", timeout=42
        )

    def test_a_configured_chain_becomes_a_fallback_of_one_provider_per_model(self) -> None:
        provider = _build_single_provider("ollama", cfg(ollama_model_chain=["a", "b"]))
        self.assertIsInstance(provider, FallbackProvider)
        self.assertEqual(self.ollama_models(provider), ["a", "b"])

    def test_the_task_chain_precedence(self) -> None:
        chains = {"route": ["task-model"], "default": ["default-model-chain"]}
        config = cfg(task_chains=chains, ollama_model_chain=["plain"])
        self.policy_chain.return_value = ["policy-model"]
        # the listener's own task chain beats the serving policy's
        _build_single_provider("ollama", config, task="route")
        self.assertEqual(self.ollama_models(None), ["task-model"])
        self.classes["OllamaProvider"].reset_mock()
        # then the serving policy's chain for the task
        _build_single_provider("ollama", cfg(task_chains=chains), task="other")
        self.assertEqual(self.ollama_models(None), ["policy-model"])
        self.classes["OllamaProvider"].reset_mock()
        # then the config's default chain, then the plain model chain
        self.policy_chain.return_value = []
        _build_single_provider("ollama", cfg(task_chains=chains), task="other")
        self.assertEqual(self.ollama_models(None), ["default-model-chain"])
        self.classes["OllamaProvider"].reset_mock()
        _build_single_provider("ollama", cfg(ollama_model_chain=["plain"]), task="other")
        self.assertEqual(self.ollama_models(None), ["plain"])

    def test_the_policy_is_only_consulted_when_a_task_is_named(self) -> None:
        _build_single_provider("ollama", cfg())
        self.policy_chain.assert_not_called()
        _build_single_provider("ollama", cfg(), task="route")
        self.policy_chain.assert_called_once_with("route")

    def test_the_cli_providers_take_their_model_tools_sandbox_and_timeout(self) -> None:
        _build_single_provider(
            "claude-cli", cfg(claude_cli_model="opus", claude_cli_allowed_tools="Read")
        )
        self.classes["ClaudeCliProvider"].assert_called_once_with(
            model="opus", allowed_tools="Read", timeout=42
        )
        _build_single_provider(
            "codex-cli", cfg(codex_cli_model="gpt", codex_cli_sandbox="read-only")
        )
        self.classes["CodexCliProvider"].assert_called_once_with(
            model="gpt", sandbox="read-only", timeout=42
        )

    def test_the_cli_providers_have_safe_defaults_when_the_config_is_silent(self) -> None:
        _build_single_provider("claude-cli", cfg())
        self.classes["ClaudeCliProvider"].assert_called_once_with(
            model="", allowed_tools="", timeout=42
        )
        _build_single_provider("codex-cli", cfg())
        self.assertEqual(
            self.classes["CodexCliProvider"].call_args.kwargs["sandbox"], "workspace-write"
        )

    def test_anthropic_resolves_its_key_from_the_configured_variable_and_entry(self) -> None:
        _build_single_provider(
            "anthropic",
            cfg(
                api_key_env="MY_KEY",
                anthropic_api_key_auto_pass_entry="entry-one",
                auto_pass_env_file="/e",
                max_tokens=999,
            ),
        )
        self.key.assert_called_once_with("MY_KEY", "entry-one", "/e")
        self.classes["AnthropicProvider"].assert_called_once_with(
            api_key="KEY", model="default-model", timeout=42, max_tokens=999
        )

    def test_anthropic_defaults_to_the_standard_variable_and_no_entry(self) -> None:
        _build_single_provider("anthropic", cfg())
        self.key.assert_called_once_with("ANTHROPIC_API_KEY", "", "")
        self.assertEqual(self.classes["AnthropicProvider"].call_args.kwargs["max_tokens"], 4096)

    def test_openai_resolves_its_own_key_and_falls_back_to_the_default_model(self) -> None:
        _build_single_provider(
            "openai",
            cfg(
                openai_api_key_env="O_KEY",
                openai_api_key_auto_pass_entry="entry-two",
                openai_model="",
            ),
        )
        self.key.assert_called_once_with("O_KEY", "entry-two", "")
        kwargs = self.classes["OpenAIProvider"].call_args.kwargs
        self.assertEqual(kwargs["model"], providers._DEFAULT_OPENAI_MODEL)
        self.assertEqual(kwargs["api_key"], "KEY")
        _build_single_provider("openai", cfg(openai_model="gpt-x"))
        self.assertEqual(self.classes["OpenAIProvider"].call_args.kwargs["model"], "gpt-x")
        self.key.assert_called_with("OPENAI_API_KEY", "", "")

    def test_an_unknown_name_lists_the_supported_ones(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown provider name 'gemini'") as raised:
            _build_single_provider("gemini", cfg())
        for name in ("ollama", "claude-cli", "codex-cli", "anthropic", "openai", "fallback"):
            self.assertIn(name, str(raised.exception))

    def test_build_provider_is_the_public_name_for_one_provider(self) -> None:
        self.assertIs(build_provider("ollama", cfg()), self.classes["OllamaProvider"].return_value)
        build_provider("ollama", cfg(), task="route")
        self.policy_chain.assert_called_with("route")


class GetProvider(Factory):
    def test_a_plain_provider_name_builds_just_that_provider(self) -> None:
        self.assertIs(
            get_provider(cfg(provider="codex-cli")), self.classes["CodexCliProvider"].return_value
        )

    def test_the_default_provider_is_ollama(self) -> None:
        config = cfg()
        del config.provider
        self.assertIs(get_provider(config), self.classes["OllamaProvider"].return_value)

    def test_fallback_builds_every_named_provider_in_order(self) -> None:
        chain = get_provider(cfg(provider="fallback", fallback_chain=["codex-cli", "ollama"]))
        self.assertIsInstance(chain, FallbackProvider)
        self.assertEqual(
            chain.providers,
            [
                self.classes["CodexCliProvider"].return_value,
                self.classes["OllamaProvider"].return_value,
            ],
        )

    def test_fallback_without_a_chain_tries_ollama_then_claude_then_anthropic(self) -> None:
        chain = get_provider(cfg(provider="fallback"))
        self.assertEqual(
            chain.providers,
            [
                self.classes["OllamaProvider"].return_value,
                self.classes["ClaudeCliProvider"].return_value,
                self.classes["AnthropicProvider"].return_value,
            ],
        )

    def test_the_task_reaches_the_ollama_member_of_a_fallback(self) -> None:
        self.policy_chain.return_value = ["policy-model"]
        get_provider(cfg(provider="fallback", fallback_chain=["ollama"]), task="route")
        self.assertEqual(self.ollama_models(None), ["policy-model"])

    def test_an_unknown_name_in_the_chain_fails_at_build_time(self) -> None:
        with self.assertRaises(ValueError):
            get_provider(cfg(provider="fallback", fallback_chain=["ollama", "nope"]))


if __name__ == "__main__":
    unittest.main()
