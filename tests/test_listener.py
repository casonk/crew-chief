"""Tests for crew_chief.listener — fully offline, all subprocesses and LLM mocked."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from crew_chief.config_loader import (
    GmailConfig,
    ListenerConfig,
    SignalConfig,
)
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

# ---------------------------------------------------------------------------
# _parse_signal_account
# ---------------------------------------------------------------------------


class TestParseSignalAccount(unittest.TestCase):
    def test_extracts_quoted_account(self):
        yaml = 'signal_cli:\n  account: "+15551234567"\n'
        with patch("builtins.open"), patch("crew_chief.listener.Path.read_text", return_value=yaml):
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
# poll_signal
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

    def _make_envelope(self, source: str, message: str) -> str:
        return json.dumps(
            {
                "envelope": {
                    "sourceNumber": source,
                    "dataMessage": {"message": message},
                }
            }
        )

    def test_disabled_returns_empty(self):
        cfg = SignalConfig(enabled=False)
        result = poll_signal(cfg)
        self.assertEqual(result, [])

    def test_returns_message_from_trusted_sender(self):
        output = self._make_envelope("+15551234567", "uptime")
        mock_proc = MagicMock(stdout=output, returncode=0)
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            patch("crew_chief.listener.subprocess.run", return_value=mock_proc),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "uptime")
        self.assertEqual(result[0].sender, "+15551234567")

    def test_ignores_untrusted_sender(self):
        output = self._make_envelope("+19999999999", "uptime")
        mock_proc = MagicMock(stdout=output, returncode=0)
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            patch("crew_chief.listener.subprocess.run", return_value=mock_proc),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_ignores_non_data_envelopes(self):
        # receipt message, no dataMessage
        output = json.dumps({"envelope": {"sourceNumber": "+15551234567", "receiptMessage": {}}})
        mock_proc = MagicMock(stdout=output, returncode=0)
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            patch("crew_chief.listener.subprocess.run", return_value=mock_proc),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_signal_cli_not_found(self):
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            patch("crew_chief.listener.subprocess.run", side_effect=FileNotFoundError),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# poll_gmail
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

    def _make_payload(self, sender: str, subject: str, snippet: str) -> str:
        return json.dumps(
            {
                "messages": [
                    {
                        "uid": 1,
                        "from": sender,
                        "subject": subject,
                        "snippet": snippet,
                    }
                ]
            }
        )

    def test_disabled_returns_empty(self):
        cfg = GmailConfig(enabled=False)
        result = poll_gmail(cfg)
        self.assertEqual(result, [])

    def test_returns_message_from_trusted_sender(self):
        payload = self._make_payload("alice@example.com", "cmd", "!uptime")
        mock_proc = MagicMock(stdout=payload, returncode=0)
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "!uptime")
        self.assertEqual(result[0].sender, "alice@example.com")

    def test_ignores_untrusted_sender(self):
        payload = self._make_payload("evil@hacker.com", "cmd", "!rm -rf /")
        mock_proc = MagicMock(stdout=payload, returncode=0)
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_handles_display_name_in_from(self):
        payload = self._make_payload("Alice Smith <alice@example.com>", "cmd", "!hostname")
        mock_proc = MagicMock(stdout=payload, returncode=0)
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)

    def test_check_inbox_failure_returns_empty(self):
        mock_proc = MagicMock(stdout="", returncode=1, stderr="error")
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_invalid_json_returns_empty(self):
        mock_proc = MagicMock(stdout="not json", returncode=0)
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])


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
        client = self._client('{"command": "df -h"}')
        result = extract_command_via_llm("disk space?", client, ["df*"])
        self.assertEqual(result, "df -h")

    def test_returns_none_when_command_is_null(self):
        client = self._client('{"command": null, "reason": "not allowed"}')
        result = extract_command_via_llm("delete everything", client, ["df*"])
        self.assertIsNone(result)

    def test_returns_none_on_invalid_json(self):
        client = self._client("Sure, here is your answer!")
        result = extract_command_via_llm("uptime", client, ["uptime"])
        self.assertIsNone(result)

    def test_returns_none_on_llm_error(self):
        client = MagicMock()
        client.chat.side_effect = OSError("connection refused")
        result = extract_command_via_llm("uptime", client, ["uptime"])
        self.assertIsNone(result)

    def test_strips_surrounding_text_from_json(self):
        # Model adds a markdown code fence — we should still extract the JSON.
        client = self._client('```json\n{"command": "uptime"}\n```')
        result = extract_command_via_llm("how long has the system been up?", client, ["uptime"])
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
        cfg = self._cfg()
        client = MagicMock()
        result = resolve_command("!uptime", cfg, client)
        self.assertEqual(result, "uptime")
        client.chat.assert_not_called()

    def test_direct_prefix_with_args(self):
        cfg = self._cfg()
        result = resolve_command("!df -h", cfg, MagicMock())
        self.assertEqual(result, "df -h")

    def test_natural_language_routes_to_llm(self):
        cfg = self._cfg(natural_language=True)
        client = MagicMock()
        client.chat.return_value = '{"command": "uptime"}'
        result = resolve_command("how long has the machine been running?", cfg, client)
        self.assertEqual(result, "uptime")
        client.chat.assert_called_once()

    def test_natural_language_false_ignores_plain_text(self):
        cfg = self._cfg(natural_language=False)
        client = MagicMock()
        result = resolve_command("check disk space", cfg, client)
        self.assertIsNone(result)
        client.chat.assert_not_called()

    def test_empty_direct_command_returns_none(self):
        cfg = self._cfg()
        result = resolve_command("!", cfg, MagicMock())
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# reply helpers (smoke tests — verify subprocess is called correctly)
# ---------------------------------------------------------------------------


class TestReplySigal(unittest.TestCase):
    def test_calls_send_script(self):
        cfg = SignalConfig(
            enabled=True,
            shock_relay_dir="/fake/signal",
            config_path="/fake/signal/config.local.yaml",
            trusted_senders=["+15551234567"],
            reply_to="+15551234567",
        )
        mock_proc = MagicMock(returncode=0, stderr="")
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc) as mock_run:
            reply_signal(cfg, "+15551234567", "output here")
        args = mock_run.call_args[0][0]
        self.assertIn("send_message.py", args[1])
        self.assertIn("+15551234567", args)
        self.assertIn("output here", args)


class TestReplyGmail(unittest.TestCase):
    def test_calls_send_script(self):
        cfg = GmailConfig(
            enabled=True,
            shock_relay_dir="/fake/gmail",
            config_path="/fake/gmail/config.local.yaml",
            trusted_senders=["a@b.com"],
            reply_to="a@b.com",
        )
        mock_proc = MagicMock(returncode=0, stderr="")
        with patch("crew_chief.listener.subprocess.run", return_value=mock_proc) as mock_run:
            reply_gmail(cfg, "a@b.com", "Re: cmd", "output here")
        args = mock_run.call_args[0][0]
        self.assertIn("send_email.py", args[1])
        self.assertIn("a@b.com", args)


if __name__ == "__main__":
    unittest.main()
