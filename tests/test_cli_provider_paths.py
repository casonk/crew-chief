"""The CLI-backed providers: prompt flattening, failure classification, availability.

``claude`` and ``codex`` are external programs, so a subprocess that fails has to be
classified: *unavailable* (try the next provider, quietly) or *an error* (try the next
provider, loudly). Everything here stubs ``subprocess.run``; no CLI is ever started.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from crew_chief.providers.base import ProviderUnavailableError
from crew_chief.providers.cli import (
    ClaudeCliProvider,
    CodexCliProvider,
    _messages_to_prompt,
)


def done(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events)


class MessagesToPrompt(unittest.TestCase):
    def test_a_lone_user_message_is_sent_verbatim(self) -> None:
        self.assertEqual(_messages_to_prompt([{"role": "user", "content": "hello"}]), "hello")

    def test_a_system_prompt_is_labelled_and_the_user_turn_is_prefixed(self) -> None:
        prompt = _messages_to_prompt([{"role": "user", "content": "hi"}], system="be brief")
        self.assertEqual(prompt, "[System]\nbe brief\n\nUser: hi")

    def test_system_role_messages_are_dropped_from_the_history(self) -> None:
        messages = [{"role": "system", "content": "ignored"}, {"role": "user", "content": "hi"}]
        self.assertEqual(_messages_to_prompt(messages), "hi")

    def test_a_multi_turn_history_carries_role_labels(self) -> None:
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        self.assertEqual(_messages_to_prompt(messages), "User: q1\n\nAssistant: a1\n\nUser: q2")

    def test_an_assistant_tool_call_is_rendered_with_its_arguments(self) -> None:
        messages = [
            {"role": "user", "content": "disk?"},
            {
                "role": "assistant",
                "content": " checking ",
                "tool_uses": [{"name": "shell", "arguments": {"command": "df -h"}}],
            },
        ]
        prompt = _messages_to_prompt(messages)
        self.assertIn("Assistant: checking", prompt)
        self.assertIn("""[Called tool 'shell' with {"command": "df -h"}]""", prompt)

    def test_a_tool_call_with_no_text_adds_no_empty_assistant_line(self) -> None:
        messages = [
            {"role": "assistant", "content": "", "tool_uses": [{"name": "t", "arguments": {}}]}
        ]
        self.assertNotIn("Assistant:", _messages_to_prompt(messages))

    def test_tool_results_are_rendered_by_tool_name(self) -> None:
        messages = [
            {
                "role": "tool_result",
                "results": [{"name": "shell", "content": "ok"}, {"name": "read", "content": "x"}],
            }
        ]
        prompt = _messages_to_prompt(messages)
        self.assertIn("[Tool result — shell]\nok", prompt)
        self.assertIn("[Tool result — read]\nx", prompt)


class ClaudeFailures(unittest.TestCase):
    def provider(self, **kwargs) -> ClaudeCliProvider:
        return ClaudeCliProvider(model="sonnet", **kwargs)

    def chat(self, provider, run, **kwargs):
        with mock.patch("subprocess.run", run):
            return provider.chat([{"role": "user", "content": "hi"}], **kwargs)

    def test_a_good_answer_carries_the_text_stop_reason_and_model(self) -> None:
        run = mock.Mock(
            return_value=done(json.dumps({"result": "hello", "stop_reason": "max_tokens"}))
        )
        result = self.chat(self.provider(), run)
        self.assertEqual(
            (result.content, result.stop_reason, result.model), ("hello", "max_tokens", "sonnet")
        )

    def test_the_command_disables_tools_by_default_and_names_the_model(self) -> None:
        run = mock.Mock(return_value=done(json.dumps({"result": "x"})))
        self.chat(self.provider(), run)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:4], ["claude", "-p", "--output-format", "json"])
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", cmd)
        self.assertEqual(run.call_args.kwargs["input"], "hi")

    def test_allowed_tools_replace_the_no_tools_flag_and_the_system_prompt_is_appended(
        self,
    ) -> None:
        run = mock.Mock(return_value=done(json.dumps({"result": "x"})))
        self.chat(self.provider(allowed_tools="Read,Bash"), run, system="be brief")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "Read,Bash")
        self.assertNotIn("--tools", cmd)
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1], "be brief")
        # the system prompt is appended to Claude Code's own, never mixed into the user turn
        self.assertEqual(run.call_args.kwargs["input"], "hi")

    def test_no_model_leaves_the_cli_default_and_reports_a_generic_name(self) -> None:
        run = mock.Mock(return_value=done(json.dumps({"result": "x"})))
        result = self.chat(ClaudeCliProvider(), run)
        self.assertNotIn("--model", run.call_args.args[0])
        self.assertEqual(result.model, "claude-cli")

    def test_a_missing_binary_is_unavailable(self) -> None:
        with self.assertRaises(ProviderUnavailableError):
            self.chat(self.provider(), mock.Mock(side_effect=FileNotFoundError()))

    def test_a_timeout_is_an_error_not_unavailability(self) -> None:
        run = mock.Mock(side_effect=subprocess.TimeoutExpired("claude", 120))
        with self.assertRaises(RuntimeError) as raised:
            self.chat(self.provider(timeout=120), run)
        self.assertNotIsInstance(raised.exception, ProviderUnavailableError)
        self.assertIn("120", str(raised.exception))

    def test_non_json_output_that_asks_for_a_login_is_unavailable(self) -> None:
        for text in ("Please run /login to continue", "Authentication failed", "Not logged in"):
            with self.subTest(text=text), self.assertRaises(ProviderUnavailableError):
                self.chat(self.provider(), mock.Mock(return_value=done(stdout=text)))

    def test_non_json_output_is_read_from_stderr_when_stdout_is_empty(self) -> None:
        with self.assertRaises(ProviderUnavailableError):
            self.chat(self.provider(), mock.Mock(return_value=done(stderr="Please run /login")))

    def test_other_non_json_output_is_an_error_quoting_it(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "non-JSON output: segfault"):
            self.chat(self.provider(), mock.Mock(return_value=done(stdout="segfault")))

    def test_a_json_error_about_authentication_is_unavailable(self) -> None:
        body = json.dumps({"is_error": True, "result": "Not logged in · Please run /login"})
        with self.assertRaises(ProviderUnavailableError):
            self.chat(self.provider(), mock.Mock(return_value=done(body)))

    def test_any_other_json_error_is_a_plain_error(self) -> None:
        body = json.dumps({"is_error": True, "result": "context window exceeded"})
        with self.assertRaises(RuntimeError) as raised:
            self.chat(self.provider(), mock.Mock(return_value=done(body)))
        self.assertNotIsInstance(raised.exception, ProviderUnavailableError)

    def test_generate_returns_just_the_text(self) -> None:
        run = mock.Mock(return_value=done(json.dumps({"result": "answer"})))
        with mock.patch("subprocess.run", run):
            self.assertEqual(self.provider().generate("hi"), "answer")

    def test_availability_follows_the_login_status(self) -> None:
        cases = (
            (done(json.dumps({"loggedIn": True})), True),
            (done(json.dumps({"loggedIn": False})), False),
            (done(json.dumps({})), False),
            (done("not json"), False),
        )
        for outcome, expected in cases:
            with (
                self.subTest(expected=expected),
                mock.patch("subprocess.run", return_value=outcome),
            ):
                self.assertIs(self.provider().is_available(), expected)

    def test_a_missing_or_slow_cli_is_simply_not_available(self) -> None:
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("claude", 10), OSError()):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch("subprocess.run", side_effect=error),
            ):
                self.assertFalse(self.provider().is_available())


class CodexRuns(unittest.TestCase):
    def provider(self, **kwargs) -> CodexCliProvider:
        return CodexCliProvider(model="o3", **kwargs)

    def chat(self, provider, run, written: str = "", **kwargs):
        """Run chat with a stub that also writes the ``-o`` file, as the real CLI would."""

        def runner(cmd, **kw):
            Path(cmd[cmd.index("-o") + 1]).write_text(written, encoding="utf-8")
            return run(cmd, **kw)

        with mock.patch("subprocess.run", runner):
            return provider.chat([{"role": "user", "content": "hi"}], **kwargs)

    def test_the_answer_file_is_the_result_and_is_removed_afterwards(self) -> None:
        seen = {}

        def run(cmd, **kw):
            seen["out"] = cmd[cmd.index("-o") + 1]
            return done()

        result = self.chat(self.provider(), run, written="  the answer \n")
        self.assertEqual(result.content, "the answer")
        self.assertEqual(result.model, "o3")
        self.assertFalse(Path(seen["out"]).exists())

    def test_the_file_is_removed_even_when_the_run_fails(self) -> None:
        seen = {}

        def run(cmd, **kw):
            seen["out"] = cmd[cmd.index("-o") + 1]
            raise subprocess.TimeoutExpired("codex", 300)

        with self.assertRaises(RuntimeError):
            self.chat(self.provider(), run)
        self.assertFalse(Path(seen["out"]).exists())

    def test_the_command_is_ephemeral_sandboxed_and_names_the_model(self) -> None:
        captured = {}

        def run(cmd, **kw):
            captured.update(cmd=cmd, kw=kw)
            return done()

        self.chat(self.provider(sandbox="read-only", cwd="/empty"), run, written="x", system="sys")
        cmd = captured["cmd"]
        self.assertEqual(cmd[:4], ["codex", "exec", "--json", "--ephemeral"])
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "read-only")
        self.assertEqual(cmd[cmd.index("--model") + 1], "o3")
        self.assertEqual(captured["kw"]["cwd"], "/empty")
        # the system prompt travels in the prompt text, labelled
        self.assertEqual(captured["kw"]["input"], "[System]\nsys\n\nUser: hi")

    def test_no_model_leaves_the_cli_default(self) -> None:
        captured = {}
        self.chat(
            CodexCliProvider(), lambda cmd, **kw: captured.update(cmd=cmd) or done(), written="x"
        )
        self.assertNotIn("--model", captured["cmd"])

    def test_an_empty_answer_file_falls_back_to_message_events(self) -> None:
        events = jsonl(
            {"type": "message", "content": "first"},
            {"type": "agent.message", "text": "second"},
            {"type": "message.completed", "content": ""},
            {"type": "turn.started"},
            {"type": "message", "text": ["not", "text"]},
        )
        result = self.chat(self.provider(), lambda cmd, **kw: done(stdout=events))
        self.assertEqual(result.content, "first\nsecond\n['not', 'text']")

    def test_no_answer_anywhere_is_an_empty_string(self) -> None:
        self.assertEqual(self.chat(self.provider(), lambda cmd, **kw: done()).content, "")

    def test_a_missing_binary_is_unavailable(self) -> None:
        def run(cmd, **kw):
            raise FileNotFoundError()

        with self.assertRaises(ProviderUnavailableError):
            self.chat(self.provider(), run)

    def test_a_timeout_is_an_error_mentioning_the_limit(self) -> None:
        def run(cmd, **kw):
            raise subprocess.TimeoutExpired("codex", 300)

        with self.assertRaisesRegex(RuntimeError, "timed out after 300s"):
            self.chat(self.provider(timeout=300), run)

    def test_an_error_event_about_authentication_is_unavailable(self) -> None:
        for message in ("You are not logged in", "Please log in", "unauthorized request"):
            events = jsonl({"type": "error", "message": message})
            with self.subTest(message=message), self.assertRaises(ProviderUnavailableError):
                self.chat(self.provider(), lambda cmd, events=events, **kw: done(stdout=events))

    def test_a_usage_or_rate_limit_counts_as_unavailable_so_the_chain_moves_on(self) -> None:
        for message in ("You have hit your usage limit", "rate limit exceeded"):
            events = jsonl({"type": "turn.failed", "error": {"message": message}})
            with self.subTest(message=message), self.assertRaises(ProviderUnavailableError):
                self.chat(self.provider(), lambda cmd, events=events, **kw: done(stdout=events))

    def test_other_error_events_are_errors_with_the_message(self) -> None:
        for event in (
            {"type": "error", "message": "context too long"},
            {"type": "turn.failed", "error": {"message": "context too long"}},
        ):
            with (
                self.subTest(event=event),
                self.assertRaisesRegex(RuntimeError, "context too long") as raised,
            ):
                self.chat(self.provider(), lambda cmd, event=event, **kw: done(stdout=jsonl(event)))
            self.assertNotIsInstance(raised.exception, ProviderUnavailableError)

    def test_an_error_event_with_no_message_still_raises_with_the_event(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "turn.failed"):
            self.chat(
                self.provider(), lambda cmd, **kw: done(stdout=jsonl({"type": "turn.failed"}))
            )

    def test_blank_and_malformed_lines_in_the_event_stream_are_skipped(self) -> None:
        stream = "\n   \nnot json\n" + jsonl({"type": "message", "content": "kept"})
        self.assertEqual(
            self.chat(self.provider(), lambda cmd, **kw: done(stdout=stream)).content, "kept"
        )

    def test_an_error_event_is_raised_even_when_the_answer_file_has_text(self) -> None:
        events = jsonl({"type": "error", "message": "boom"})
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self.chat(
                self.provider(), lambda cmd, **kw: done(stdout=events), written="half an answer"
            )

    def test_generate_returns_just_the_text(self) -> None:
        def runner(cmd, **kw):
            Path(cmd[cmd.index("-o") + 1]).write_text("answer", encoding="utf-8")
            return done()

        with mock.patch("subprocess.run", runner):
            self.assertEqual(self.provider().generate("hi"), "answer")

    def test_availability_needs_a_zero_exit_and_a_logged_in_message(self) -> None:
        cases = (
            (done("Logged in using ChatGPT", returncode=0), True),
            (done("Not logged in", returncode=1), False),
            (done("Logged in", returncode=1), False),
            (done("something else", returncode=0), False),
        )
        for outcome, expected in cases:
            with (
                self.subTest(expected=expected, out=outcome.stdout),
                mock.patch("subprocess.run", return_value=outcome),
            ):
                self.assertIs(self.provider().is_available(), expected)

    def test_a_missing_or_slow_cli_is_simply_not_available(self) -> None:
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("codex", 10)):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch("subprocess.run", side_effect=error),
            ):
                self.assertFalse(self.provider().is_available())


if __name__ == "__main__":
    unittest.main()
