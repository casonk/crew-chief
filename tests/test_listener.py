"""Tests for crew_chief.listener — fully offline, all subprocesses and LLM mocked."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from dyno_lab.proc import ProcessRecorder, SubprocessPatch, build_completed_process

from crew_chief.config_loader import GmailConfig, ListenerConfig, SignalConfig
from crew_chief.listener import (
    _extract_email_address,
    _parse_signal_account,
    _parse_signal_json_lines,
    extract_command_via_llm,
    poll_gmail,
    poll_signal,
    reply_gmail,
    reply_signal,
    resolve_command,
)

_SIGNAL_TARGET = "crew_chief.listener.subprocess.run"
_GMAIL_TARGET = "crew_chief.listener.subprocess.run"


# ---------------------------------------------------------------------------
# _parse_signal_account
# ---------------------------------------------------------------------------


class TestParseSignalAccount(unittest.TestCase):
    def test_extracts_quoted_account(self):
        yaml = 'signal_cli:\n  account: "+15551234567"\n'
        with patch("crew_chief.listener.Path.read_text", return_value=yaml):
            result = _parse_signal_account("/fake/config.local.yaml")
        self.assertEqual(result, "+15551234567")

    def test_extracts_unquoted_account(self):
        yaml = "signal_cli:\n  account: +15550000000\n"
        with patch("crew_chief.listener.Path.read_text", return_value=yaml):
            result = _parse_signal_account("/fake/config.local.yaml")
        self.assertEqual(result, "+15550000000")

    def test_missing_account_returns_empty(self):
        yaml = "signal_cli:\n  bus_name: org.asamk.Signal\n"
        with patch("crew_chief.listener.Path.read_text", return_value=yaml):
            result = _parse_signal_account("/fake/config.local.yaml")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _parse_signal_json_lines
# ---------------------------------------------------------------------------


class TestParseSignalJsonLines(unittest.TestCase):
    def test_parses_single_envelope(self):
        line = json.dumps({"envelope": {"source": "+1", "dataMessage": {"message": "hi"}}})
        result = _parse_signal_json_lines(line)
        self.assertEqual(len(result), 1)

    def test_skips_invalid_json(self):
        lines = 'not-json\n{"envelope": {}}\n'
        result = _parse_signal_json_lines(lines)
        self.assertEqual(len(result), 1)

    def test_empty_output(self):
        self.assertEqual(_parse_signal_json_lines(""), [])

    def test_multiple_lines(self):
        lines = "\n".join(json.dumps({"envelope": {"source": f"+{i}"}}) for i in range(3))
        result = _parse_signal_json_lines(lines)
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# poll_signal (uses SubprocessPatch / ProcessRecorder)
# ---------------------------------------------------------------------------


class TestPollSignal(unittest.TestCase):
    def _cfg(self, trusted=None):
        return SignalConfig(
            enabled=True,
            shock_relay_dir="/fake/signal",
            config_path="/fake/signal/config.local.yaml",
            trusted_senders=trusted or ["+15551234567"],
            reply_to="+15551234567",
        )

    def _envelope(self, source: str, message: str) -> str:
        return json.dumps(
            {"envelope": {"sourceNumber": source, "dataMessage": {"message": message}}}
        )

    def _sync_envelope(self, source: str, message: str) -> str:
        """Linked-device sync envelope (note-to-self from primary device)."""
        return json.dumps(
            {
                "envelope": {
                    "sourceNumber": source,
                    "syncMessage": {"sentMessage": {"destination": source, "message": message}},
                }
            }
        )

    def test_disabled_returns_empty(self):
        self.assertEqual(poll_signal(SignalConfig(enabled=False)), [])

    def test_returns_message_from_trusted_sender(self):
        recorder = ProcessRecorder(
            responses=[build_completed_process(stdout=self._envelope("+15551234567", "uptime"))]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "uptime")
        self.assertEqual(result[0].sender, "+15551234567")

    def test_ignores_untrusted_sender(self):
        recorder = ProcessRecorder(
            responses=[build_completed_process(stdout=self._envelope("+19999999999", "uptime"))]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_ignores_non_data_envelopes(self):
        receipt = json.dumps({"envelope": {"sourceNumber": "+15551234567", "receiptMessage": {}}})
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=receipt)])
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_handles_sync_message_from_linked_device(self):
        """Note-to-self from the primary device arrives as syncMessage.sentMessage."""
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(stdout=self._sync_envelope("+15551234567", "!uptime"))
            ]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "!uptime")
        self.assertEqual(result[0].sender, "+15551234567")

    def test_signal_cli_not_found(self):
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(
                lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()),
                target=_SIGNAL_TARGET,
            ),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_signal_cli_command_constructed_correctly(self):
        recorder = ProcessRecorder(responses=[build_completed_process(stdout="")])
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            poll_signal(self._cfg())
        cmd = recorder.calls[0].args
        self.assertIn("signal-cli", cmd)
        self.assertIn("--output=json", cmd)
        self.assertIn("+15551234567", cmd)
        self.assertIn("receive", cmd)


# ---------------------------------------------------------------------------
# poll_gmail (uses SubprocessPatch / ProcessRecorder)
# ---------------------------------------------------------------------------


class TestPollGmail(unittest.TestCase):
    def _cfg(self, trusted=None):
        return GmailConfig(
            enabled=True,
            shock_relay_dir="/fake/gmail",
            config_path="/fake/gmail/config.local.yaml",
            trusted_senders=trusted or ["alice@example.com"],
            reply_to="me@example.com",
        )

    def _payload(self, sender: str, subject: str, snippet: str) -> str:
        return json.dumps(
            {"messages": [{"uid": 1, "from": sender, "subject": subject, "snippet": snippet}]}
        )

    def test_disabled_returns_empty(self):
        self.assertEqual(poll_gmail(GmailConfig(enabled=False)), [])

    def test_returns_message_from_trusted_sender(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(stdout=self._payload("alice@example.com", "cmd", "!uptime"))
            ]
        )
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "!uptime")
        self.assertEqual(result[0].sender, "alice@example.com")

    def test_ignores_untrusted_sender(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(stdout=self._payload("evil@hacker.com", "cmd", "!rm -rf /"))
            ]
        )
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_handles_display_name_in_from(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._payload("Alice Smith <alice@example.com>", "cmd", "!hostname")
                )
            ]
        )
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)

    def test_check_inbox_failure_returns_empty(self):
        recorder = ProcessRecorder(
            responses=[build_completed_process(returncode=1, stderr="error")]
        )
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_invalid_json_returns_empty(self):
        recorder = ProcessRecorder(responses=[build_completed_process(stdout="not json")])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_check_inbox_called_with_unseen_flag(self):
        recorder = ProcessRecorder(responses=[build_completed_process(stdout='{"messages": []}')])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            poll_gmail(self._cfg())
        cmd = recorder.calls[0].args
        self.assertIn("--unseen", cmd)
        self.assertIn("check_inbox.py", cmd[1])


# ---------------------------------------------------------------------------
# _extract_email_address
# ---------------------------------------------------------------------------


class TestExtractEmailAddress(unittest.TestCase):
    def test_plain_address(self):
        self.assertEqual(_extract_email_address("alice@example.com"), "alice@example.com")

    def test_display_name_form(self):
        self.assertEqual(
            _extract_email_address("Alice Smith <alice@example.com>"), "alice@example.com"
        )

    def test_lowercased(self):
        self.assertEqual(_extract_email_address("BOB@EXAMPLE.COM"), "bob@example.com")


# ---------------------------------------------------------------------------
# extract_command_via_llm
# ---------------------------------------------------------------------------


class TestExtractCommandViaLlm(unittest.TestCase):
    def _client(self, response: str) -> MagicMock:
        client = MagicMock()
        client.chat.return_value = response
        return client

    def test_returns_command_on_valid_json(self):
        result = extract_command_via_llm(
            "disk space?", self._client('{"command": "df -h"}'), ["df*"]
        )
        self.assertEqual(result, "df -h")

    def test_returns_none_when_command_is_null(self):
        result = extract_command_via_llm(
            "delete everything",
            self._client('{"command": null, "reason": "not allowed"}'),
            ["df*"],
        )
        self.assertIsNone(result)

    def test_returns_none_on_invalid_json(self):
        result = extract_command_via_llm("uptime", self._client("Sure!"), ["uptime"])
        self.assertIsNone(result)

    def test_returns_none_on_llm_error(self):
        client = MagicMock()
        client.chat.side_effect = OSError("connection refused")
        result = extract_command_via_llm("uptime", client, ["uptime"])
        self.assertIsNone(result)

    def test_strips_markdown_fences(self):
        result = extract_command_via_llm(
            "how long up?",
            self._client('```json\n{"command": "uptime"}\n```'),
            ["uptime"],
        )
        self.assertEqual(result, "uptime")


# ---------------------------------------------------------------------------
# resolve_command
# ---------------------------------------------------------------------------


class TestResolveCommand(unittest.TestCase):
    def _cfg(self, natural_language: bool = True) -> ListenerConfig:
        cfg = ListenerConfig()
        cfg.llm.natural_language = natural_language
        cfg.dispatch.allowed_commands = ["uptime", "df*"]
        return cfg

    def test_direct_prefix_bypasses_llm(self):
        client = MagicMock()
        result = resolve_command("!uptime", self._cfg(), client)
        self.assertEqual(result, "uptime")
        client.chat.assert_not_called()

    def test_direct_prefix_with_args(self):
        self.assertEqual(resolve_command("!df -h", self._cfg(), MagicMock()), "df -h")

    def test_natural_language_routes_to_llm(self):
        client = MagicMock()
        client.chat.return_value = '{"command": "uptime"}'
        result = resolve_command("how long running?", self._cfg(True), client)
        self.assertEqual(result, "uptime")
        client.chat.assert_called_once()

    def test_natural_language_false_ignores_plain_text(self):
        client = MagicMock()
        result = resolve_command("check disk space", self._cfg(False), client)
        self.assertIsNone(result)
        client.chat.assert_not_called()

    def test_empty_direct_command_returns_none(self):
        self.assertIsNone(resolve_command("!", self._cfg(), MagicMock()))


# ---------------------------------------------------------------------------
# reply helpers — verify subprocess args via ProcessRecorder
# ---------------------------------------------------------------------------


class TestReplySignal(unittest.TestCase):
    def test_calls_send_script_with_correct_args(self):
        cfg = SignalConfig(
            enabled=True,
            shock_relay_dir="/fake/signal",
            config_path="/fake/signal/config.local.yaml",
            trusted_senders=["+15551234567"],
            reply_to="+15551234567",
        )
        recorder = ProcessRecorder(responses=[build_completed_process()])
        with SubprocessPatch(recorder, target=_SIGNAL_TARGET):
            reply_signal(cfg, "+15551234567", "output here")
        args = recorder.calls[0].args
        self.assertIn("send_message.py", args[1])
        self.assertIn("+15551234567", args)
        self.assertIn("output here", args)


class TestReplyGmail(unittest.TestCase):
    def test_calls_send_script_with_correct_args(self):
        cfg = GmailConfig(
            enabled=True,
            shock_relay_dir="/fake/gmail",
            config_path="/fake/gmail/config.local.yaml",
            trusted_senders=["a@b.com"],
            reply_to="a@b.com",
        )
        recorder = ProcessRecorder(responses=[build_completed_process()])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            reply_gmail(cfg, "a@b.com", "cmd", "output here")
        args = recorder.calls[0].args
        self.assertIn("send_email.py", args[1])
        self.assertIn("a@b.com", args)


if __name__ == "__main__":
    unittest.main()
