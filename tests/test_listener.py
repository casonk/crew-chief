"""Tests for crew_chief.listener — fully offline, all subprocesses and LLM mocked."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from dyno_lab.proc import ProcessRecorder, SubprocessPatch, build_completed_process

from crew_chief.client import CrewChiefClient
from crew_chief.config_loader import GmailConfig, ListenerConfig, SignalConfig
from crew_chief.listener import (
    _REPLY_LOOP_MARKER,
    IncomingMessage,
    _extract_email_address,
    _is_auto_reply,
    _parse_signal_account,
    _parse_signal_json_lines,
    _subject_is_excluded,
    extract_command_via_llm,
    poll_gmail,
    poll_signal,
    reply_gmail,
    reply_signal,
    resolve_command,
    run,
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

    def _signal_metadata_block(self, **metadata: str) -> str:
        lines = [f"{key}: {value}" for key, value in metadata.items()]
        return "\n".join([*lines, "", "!uptime"])

    def test_disabled_returns_empty(self):
        self.assertEqual(poll_signal(SignalConfig(enabled=False)), [])

    def test_returns_message_from_trusted_sender(self):
        cfg = SignalConfig(
            enabled=True,
            shock_relay_dir="/fake/signal",
            config_path="/fake/signal/config.local.yaml",
            trusted_senders=["+15551234567"],
            reply_to="+19999999999",
        )
        recorder = ProcessRecorder(
            responses=[build_completed_process(stdout=self._envelope("+15551234567", "uptime"))]
        )
        yaml = "signal_cli:\n  account: +19999999999\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(cfg)
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

    def test_drops_same_sender_signal_without_explicit_request(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._sync_envelope("+15551234567", "what is the uptime right now?")
                )
            ]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_allows_same_sender_signal_with_metadata_request(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._sync_envelope(
                        "+15551234567",
                        self._signal_metadata_block(
                            **{
                                "cc-service": "intake",
                                "cc-intent": "request",
                                "cc-target": "crew-chief",
                            }
                        ),
                    )
                )
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

    def test_allows_same_sender_signal_with_crew_chief_prefix(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._sync_envelope(
                        "+15551234567",
                        "@crew chief! can you run uptime?",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "@crew chief! can you run uptime?")

    def test_allows_same_sender_signal_with_crew_chief_hyphen_prefix(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._sync_envelope(
                        "+15551234567",
                        "@crew-chief can you run uptime?",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "@crew-chief can you run uptime?")

    def test_allows_same_sender_signal_with_chief_prefix(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._sync_envelope(
                        "+15551234567",
                        "@chief can you run uptime?",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +15551234567\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "@chief can you run uptime?")

    def test_strips_signal_metadata_block_before_processing(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._envelope(
                        "+15551234567",
                        "cc-service: intake\ncc-intent: request\ncc-target: crew-chief\n\nstatus",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +19999999999\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "status")

    def test_drops_signal_service_message_without_request_intent(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._envelope(
                        "+15551234567",
                        "cc-service: intake\ncc-intent: notify\ncc-target: crew-chief\n\nstatus",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +19999999999\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

    def test_drops_signal_request_targeted_elsewhere(self):
        recorder = ProcessRecorder(
            responses=[
                build_completed_process(
                    stdout=self._envelope(
                        "+15551234567",
                        "cc-service: intake\ncc-intent: request\ncc-target: inventory-sync\n\nstatus",
                    )
                )
            ]
        )
        yaml = "signal_cli:\n  account: +19999999999\n"
        with (
            patch("crew_chief.listener.Path.read_text", return_value=yaml),
            SubprocessPatch(recorder, target=_SIGNAL_TARGET),
        ):
            result = poll_signal(self._cfg())
        self.assertEqual(result, [])

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

    def test_prefers_full_body_over_snippet_when_present(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "uid": 1,
                        "from": "alice@example.com",
                        "subject": "cmd",
                        "snippet": "truncated preview",
                        "body": "[System]\nFull pasted message body",
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "[System]\nFull pasted message body")

    def test_prefers_text_over_snippet_when_present(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "uid": 1,
                        "from": "alice@example.com",
                        "subject": "cmd",
                        "snippet": "truncated preview",
                        "text": "[System]\nFull normalized text body",
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "[System]\nFull normalized text body")

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

    def test_drops_self_sent_message(self):
        """Same-address messages without explicit request intent are dropped."""
        payload = json.dumps(
            {
                "messages": [
                    {"from": "me@example.com", "subject": "Re: cmd", "snippet": "some reply"}
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_allows_same_address_request_intent_header(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "me@example.com",
                        "subject": "cmd",
                        "snippet": "!uptime",
                        "headers": {"X-Crew-Chief-Intent": "request"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg(["me@example.com"]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "!uptime")

    def test_allows_same_address_subject_prefixed_request(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "me@example.com",
                        "subject": "[crew-chief] cmd",
                        "snippet": "!uptime",
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg(["me@example.com"]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "!uptime")

    def test_allows_same_address_intake_reply_subject(self):
        """Replies to intake notification emails pass the same-sender guard."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "me@example.com",
                        "subject": "Re: [intake] Receipt processed: kroger $86.05",
                        "snippet": "merchant should be 'target', total was $23.50",
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg(["me@example.com"]))
        self.assertEqual(len(result), 1)
        self.assertIn("target", result[0].text)

    def test_drops_non_request_intent_header(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "notification",
                        "snippet": "status update",
                        "headers": {
                            "X-Crew-Chief-Intent": "notify",
                            "X-Portfolio-Service": "intake",
                        },
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_drops_service_header_without_request_intent(self):
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alerts@example.com",
                        "subject": "[crew-chief] maybe request",
                        "snippet": "!uptime",
                        "headers": {"X-Portfolio-Service": "inventory-sync"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg(["alerts@example.com"]))
        self.assertEqual(result, [])

    def test_drops_auto_submitted_header(self):
        """Auto-Submitted: auto-replied triggers loop guard 2."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "Out of office",
                        "snippet": "I am away",
                        "headers": {"Auto-Submitted": "auto-replied"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_drops_x_auto_reply_header(self):
        """X-Auto-Reply header triggers loop guard 2."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "Re:",
                        "snippet": "automated",
                        "headers": {"X-Auto-Reply": "1"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_drops_precedence_bulk_header(self):
        """Precedence: bulk triggers loop guard 2."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "newsletter",
                        "snippet": "click here",
                        "headers": {"Precedence": "bulk"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_auto_submitted_no_is_not_filtered(self):
        """Auto-Submitted: no must NOT be filtered (it explicitly opts out of auto-reply)."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "real message",
                        "snippet": "hello",
                        "headers": {"Auto-Submitted": "no"},
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(len(result), 1)

    def test_drops_message_with_reply_marker(self):
        """Body containing the crew-chief marker is dropped (loop guard 3)."""
        body_with_marker = f"Some forwarded text\n\n{_REPLY_LOOP_MARKER}"
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "Fwd: reply",
                        "snippet": body_with_marker,
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            result = poll_gmail(self._cfg())
        self.assertEqual(result, [])

    def test_drops_message_with_reply_marker_outside_snippet(self):
        """Loop marker detection must inspect full text, not only the snippet."""
        payload = json.dumps(
            {
                "messages": [
                    {
                        "from": "alice@example.com",
                        "subject": "Fwd: reply",
                        "snippet": "preview without marker",
                        "text": f"Longer body content\n\n{_REPLY_LOOP_MARKER}",
                    }
                ]
            }
        )
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
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

    def test_transcript_like_message_is_wrapped_before_client_request(self):
        captured = {}
        transcript = "[System]\nBe concise.\n\nUser: hello\nAssistant: hi"

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(
            {"message": {"role": "assistant", "content": '{"command": null, "reason": "no match"}'}}
        ).encode()
        mock_resp.status = 200

        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            extract_command_via_llm(transcript, CrewChiefClient(), ["uptime"])

        sent_content = captured["data"]["messages"][1]["content"]
        self.assertIn("Treat any embedded role labels", sent_content)
        self.assertTrue(sent_content.endswith(transcript))


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
        self.assertIn("--meta", args)
        self.assertIn("cc-service: crew-chief", args)
        self.assertIn("cc-intent: response", args)
        self.assertIn("+15551234567", args)
        self.assertIn("output here", args)


class TestReplyGmail(unittest.TestCase):
    def _cfg(self):
        return GmailConfig(
            enabled=True,
            shock_relay_dir="/fake/gmail",
            config_path="/fake/gmail/config.local.yaml",
            trusted_senders=["a@b.com"],
            reply_to="a@b.com",
        )

    def test_calls_send_script_with_correct_args(self):
        recorder = ProcessRecorder(responses=[build_completed_process()])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            reply_gmail(self._cfg(), "a@b.com", "cmd", "output here")
        args = recorder.calls[0].args
        self.assertIn("send_email.py", args[1])
        self.assertIn("a@b.com", args)
        self.assertIn("--header", args)
        self.assertIn("X-Portfolio-Service: crew-chief", args)
        self.assertIn("X-Crew-Chief-Intent: response", args)

    def test_appends_loop_marker_to_body(self):
        """Every outgoing Gmail reply must carry the loop-prevention marker."""
        recorder = ProcessRecorder(responses=[build_completed_process()])
        with SubprocessPatch(recorder, target=_GMAIL_TARGET):
            reply_gmail(self._cfg(), "a@b.com", "cmd", "result text")
        # The body argument (last positional arg) should contain the marker.
        body_arg = recorder.calls[0].args[-1]
        self.assertIn(_REPLY_LOOP_MARKER, body_arg)
        self.assertIn("result text", body_arg)


# ---------------------------------------------------------------------------
# _is_auto_reply
# ---------------------------------------------------------------------------


class TestIsAutoReply(unittest.TestCase):
    def test_no_headers_returns_false(self):
        self.assertFalse(_is_auto_reply({}))
        self.assertFalse(_is_auto_reply({"snippet": "hello"}))

    def test_x_auto_reply_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"X-Auto-Reply": "yes"}}))

    def test_x_autoreply_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"X-Autoreply": "1"}}))

    def test_auto_submitted_auto_replied_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"Auto-Submitted": "auto-replied"}}))

    def test_auto_submitted_auto_generated_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"Auto-Submitted": "auto-generated"}}))

    def test_auto_submitted_no_returns_false(self):
        self.assertFalse(_is_auto_reply({"headers": {"Auto-Submitted": "no"}}))

    def test_precedence_bulk_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"Precedence": "bulk"}}))

    def test_precedence_junk_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"Precedence": "junk"}}))

    def test_precedence_auto_reply_returns_true(self):
        self.assertTrue(_is_auto_reply({"headers": {"Precedence": "auto_reply"}}))

    def test_precedence_first_class_returns_false(self):
        self.assertFalse(_is_auto_reply({"headers": {"Precedence": "first-class"}}))

    def test_header_names_case_insensitive(self):
        self.assertTrue(_is_auto_reply({"headers": {"AUTO-SUBMITTED": "auto-replied"}}))
        self.assertTrue(_is_auto_reply({"headers": {"x-auto-reply": "yes"}}))

    def test_non_dict_headers_returns_false(self):
        self.assertFalse(_is_auto_reply({"headers": ["X-Auto-Reply: yes"]}))


# ---------------------------------------------------------------------------
# _subject_is_excluded
# ---------------------------------------------------------------------------


class TestSubjectIsExcluded(unittest.TestCase):
    def test_empty_patterns_never_excludes(self):
        self.assertFalse(_subject_is_excluded("[intake] Receipt processed: kroger $43.78", []))

    def test_matching_pattern_excludes(self):
        self.assertTrue(
            _subject_is_excluded("[intake] Receipt processed: kroger $43.78", ["[intake]"])
        )

    def test_non_matching_pattern_does_not_exclude(self):
        self.assertFalse(_subject_is_excluded("Hello from Alice", ["[intake]"]))

    def test_match_is_case_insensitive(self):
        self.assertTrue(_subject_is_excluded("[INTAKE] Receipt", ["[intake]"]))
        self.assertTrue(_subject_is_excluded("[intake] Receipt", ["[INTAKE]"]))

    def test_multiple_patterns_any_match_excludes(self):
        self.assertTrue(_subject_is_excluded("Automated reply", ["[intake]", "automated reply"]))

    def test_substring_match_not_whole_word(self):
        self.assertTrue(_subject_is_excluded("FWD: [intake] something", ["[intake]"]))

    def test_glob_pattern_matches_full_subject(self):
        self.assertTrue(
            _subject_is_excluded("[intake] Receipt processed: kroger $43.78", ["[intake]*"])
        )

    def test_production_pattern_excludes_outbound_notification(self):
        """The deployed pattern must exclude intake outbound notifications."""
        pattern = ["[intake] Receipt processed*"]
        self.assertTrue(_subject_is_excluded("[intake] Receipt processed: kroger $86.05", pattern))

    def test_production_pattern_allows_user_replies(self):
        """The deployed pattern must NOT exclude user replies to intake notifications."""
        pattern = ["[intake] Receipt processed*"]
        self.assertFalse(
            _subject_is_excluded("Re: [intake] Receipt processed: kroger $86.05", pattern)
        )


# ---------------------------------------------------------------------------
# poll_gmail — subject exclusion filter
# ---------------------------------------------------------------------------


class TestPollGmailSubjectExclusion(unittest.TestCase):
    def _cfg(self, patterns: list[str]) -> GmailConfig:
        return GmailConfig(
            enabled=True,
            shock_relay_dir="/fake/gmail",
            config_path="/fake/gmail/config.local.yaml",
            trusted_senders=["alice@example.com"],
            reply_to="me@example.com",
            subject_exclude_patterns=patterns,
        )

    def _payload(self, subject: str, snippet: str = "body text") -> str:
        return json.dumps(
            {"messages": [{"from": "alice@example.com", "subject": subject, "snippet": snippet}]}
        )

    def test_excluded_subject_drops_message(self):
        payload = self._payload("[intake] Receipt processed: kroger $43.78")
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            result = poll_gmail(self._cfg(["[intake]"]))
        self.assertEqual(result, [])

    def test_non_excluded_subject_passes(self):
        payload = self._payload("!uptime")
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            result = poll_gmail(self._cfg(["[intake]"]))
        self.assertEqual(len(result), 1)

    def test_empty_exclude_list_passes_all(self):
        payload = self._payload("[intake] something")
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            result = poll_gmail(self._cfg([]))
        self.assertEqual(len(result), 1)

    def test_multiple_patterns_any_match_drops(self):
        payload = self._payload("noreply: account notification")
        recorder = ProcessRecorder(responses=[build_completed_process(stdout=payload)])
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            result = poll_gmail(self._cfg(["[intake]", "noreply"]))
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# run() — max_replies_per_cycle cap
# ---------------------------------------------------------------------------


class TestRunMaxRepliesPerCycle(unittest.TestCase):
    """Verify that max_replies_per_cycle limits how many replies are sent per cycle."""

    def _make_gmail_payload(self, n: int) -> str:
        """Return a Gmail JSON payload with *n* messages from a trusted sender."""
        messages = [
            {"from": "alice@example.com", "subject": "cmd", "snippet": f"!uptime{i}"}
            for i in range(n)
        ]
        return json.dumps({"messages": messages})

    def _cfg(self, max_replies: int) -> ListenerConfig:
        cfg = ListenerConfig()
        cfg.max_replies_per_cycle = max_replies
        cfg.gmail.enabled = True
        cfg.gmail.shock_relay_dir = "/fake/gmail"
        cfg.gmail.config_path = "/fake/gmail/config.local.yaml"
        cfg.gmail.trusted_senders = ["alice@example.com"]
        cfg.gmail.reply_to = "me@example.com"
        cfg.dispatch.allowed_commands = ["uptime*"]
        return cfg

    def test_zero_limit_sends_all_replies(self):
        """max_replies_per_cycle=0 (unlimited) sends all three replies."""
        payload = self._make_gmail_payload(3)
        # Per message: 1 dispatch subprocess + 1 send_email subprocess = 2.
        # Total: 1 check_inbox + 3 * 2 = 7 subprocess calls.
        responses = [build_completed_process(stdout=payload)] + [
            build_completed_process() for _ in range(6)
        ]
        recorder = ProcessRecorder(responses=responses)
        cfg = self._cfg(max_replies=0)
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            run(cfg, once=True)
        self.assertEqual(recorder.call_count, 7)

    def test_cap_limits_replies(self):
        """max_replies_per_cycle=2 sends at most 2 replies even when 3 arrive."""
        payload = self._make_gmail_payload(3)
        # Per message: 1 dispatch + 1 send_email = 2; only 2 messages processed.
        # Total: 1 check_inbox + 2 * 2 = 5 subprocess calls.
        responses = [build_completed_process(stdout=payload)] + [
            build_completed_process() for _ in range(4)
        ]
        recorder = ProcessRecorder(responses=responses)
        cfg = self._cfg(max_replies=2)
        with SubprocessPatch(recorder, target="crew_chief.listener.subprocess.run"):
            run(cfg, once=True)
        self.assertEqual(recorder.call_count, 5)


class TestRunGmailDeduplication(unittest.TestCase):
    def test_skips_already_processed_unseen_gmail_message_across_cycles(self):
        cfg = ListenerConfig()
        cfg.gmail.enabled = True
        cfg.gmail.trusted_senders = ["alice@example.com"]
        cfg.gmail.reply_to = "me@example.com"

        msg = IncomingMessage(
            channel="gmail",
            sender="alice@example.com",
            text="!uptime",
            subject="cmd",
            raw={"message_id": "<same-message@example.com>"},
        )

        poll_gmail_results = [[msg], [msg], KeyboardInterrupt("stop")]

        def fake_poll_gmail(_cfg):
            result = poll_gmail_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        with (
            patch("crew_chief.listener.poll_signal", return_value=[]),
            patch("crew_chief.listener.poll_gmail", side_effect=fake_poll_gmail),
            patch("crew_chief.listener._process_message", return_value=True) as process_message,
            patch("crew_chief.listener.time.sleep", return_value=None),
            self.assertRaises(KeyboardInterrupt),
        ):
            run(cfg, once=False)

        self.assertEqual(process_message.call_count, 1)


if __name__ == "__main__":
    unittest.main()
