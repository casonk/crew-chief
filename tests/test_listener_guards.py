"""What the listener refuses to read, act on, or answer.

The listener reads messages from channels other people can write to and replies on
them, so its value is in what it ignores: untrusted senders, its own replies coming
back around, mail that is not addressed to it, and more replies per cycle than the
operator allowed. Every external process (``signal-cli``, the mail scripts) and the
model are stubbed; nothing here sends or receives anything.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from crew_chief import listener
from crew_chief.config_loader import GmailConfig, ListenerConfig, SignalConfig
from crew_chief.listener import (
    _REPLY_LOOP_MARKER,
    IncomingMessage,
    _claim_gmail_message,
    _gmail_body_candidates,
    _gmail_body_text,
    _gmail_headers,
    _gmail_message_fingerprint,
    _is_explicit_crew_chief_request,
    _is_explicit_signal_request,
    _process_message,
    _split_signal_metadata_block,
    extract_command_via_llm,
    poll_gmail,
    poll_signal,
    reply_gmail,
    reply_signal,
    resolve_command,
    run,
)

RUN = "crew_chief.listener.subprocess.run"


def done(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def envelope(source: str, text: str, kind: str = "dataMessage") -> str:
    if kind == "sync":
        env = {"sourceNumber": source, "syncMessage": {"sentMessage": {"message": text}}}
    else:
        env = {"sourceNumber": source, "dataMessage": {"message": text}}
    return json.dumps({"envelope": env})


class SignalPolling(unittest.TestCase):
    def cfg(self, **kwargs) -> SignalConfig:
        base = {
            "enabled": True,
            "shock_relay_dir": "/relay",
            "config_path": "/relay/config.yaml",
            "trusted_senders": ["+1555"],
            "reply_to": "+1999",
        }
        return SignalConfig(**{**base, **kwargs})

    def poll(self, stdout: str = "", cfg: SignalConfig | None = None, **run_kwargs):
        with (
            mock.patch.object(listener, "_parse_signal_account", return_value="+1999"),
            mock.patch(RUN, return_value=done(stdout), **run_kwargs) as run,
        ):
            return poll_signal(cfg or self.cfg()), run

    def test_disabled_or_unconfigured_never_starts_signal_cli(self) -> None:
        for cfg in (
            self.cfg(enabled=False),
            self.cfg(config_path=""),
            self.cfg(shock_relay_dir=""),
        ):
            with self.subTest(cfg=cfg), mock.patch(RUN) as run:
                self.assertEqual(poll_signal(cfg), [])
            run.assert_not_called()

    def test_an_unreadable_config_or_missing_account_yields_nothing(self) -> None:
        with mock.patch.object(listener, "_parse_signal_account", side_effect=OSError("denied")):
            self.assertEqual(poll_signal(self.cfg()), [])
        with mock.patch.object(listener, "_parse_signal_account", return_value=""):
            self.assertEqual(poll_signal(self.cfg()), [])

    def test_a_failing_signal_cli_yields_nothing_rather_than_raising(self) -> None:
        for outcome in (
            {"side_effect": FileNotFoundError()},
            {"side_effect": subprocess.TimeoutExpired("signal-cli", 15)},
            {"return_value": done(returncode=1, stderr="boom")},
        ):
            with (
                self.subTest(outcome=outcome),
                mock.patch.object(listener, "_parse_signal_account", return_value="+1999"),
                mock.patch(RUN, **outcome),
            ):
                self.assertEqual(poll_signal(self.cfg()), [])

    def test_a_trusted_sender_is_returned_with_the_original_envelope(self) -> None:
        messages, run = self.poll(envelope("+1555", "!uptime"))
        self.assertEqual(
            [(m.sender, m.text, m.channel) for m in messages], [("+1555", "!uptime", "signal")]
        )
        self.assertIn("--output=json", run.call_args.args[0])
        self.assertIn("+1999", run.call_args.args[0])

    def test_an_untrusted_sender_is_ignored(self) -> None:
        messages, _ = self.poll(envelope("+1777", "!uptime"))
        self.assertEqual(messages, [])

    def test_a_note_to_self_from_the_linked_device_is_read(self) -> None:
        messages, _ = self.poll(envelope("+1555", "!uptime", kind="sync"))
        self.assertEqual([m.text for m in messages], ["!uptime"])

    def test_receipts_typing_indicators_and_empty_messages_are_skipped(self) -> None:
        stream = "\n".join(
            [
                json.dumps({"envelope": {"sourceNumber": "+1555", "receiptMessage": {}}}),
                json.dumps({"envelope": {"sourceNumber": "+1555", "dataMessage": {"message": ""}}}),
                json.dumps({"envelope": {"sourceNumber": "+1555", "dataMessage": {}}}),
                "not json",
            ]
        )
        messages, _ = self.poll(stream)
        self.assertEqual(messages, [])

    def test_the_old_source_field_is_accepted_when_there_is_no_source_number(self) -> None:
        line = json.dumps({"envelope": {"source": "+1555", "dataMessage": {"message": "!date"}}})
        messages, _ = self.poll(line)
        self.assertEqual([m.sender for m in messages], ["+1555"])

    def test_a_message_from_our_own_number_needs_an_explicit_request(self) -> None:
        cfg = self.cfg(trusted_senders=["+1999"])
        for text, kept in (
            ("our own reply coming back", False),
            ("!uptime", True),
            ("[crew-chief] status", True),
            ("crew-chief what's the disk", True),
            ("@chief status", True),
        ):
            messages, _ = self.poll(envelope("+1999", text), cfg)
            with self.subTest(text=text):
                self.assertEqual(len(messages), 1 if kept else 0)

    def test_metadata_that_is_not_a_request_is_skipped_and_a_request_is_stripped(self) -> None:
        response = "cc-intent: response\ncc-service: intake\n\nreceipt processed"
        request = "cc-intent: request\ncc-target: crew-chief\n\n!uptime"
        other = "cc-intent: request\ncc-target: someone-else\n\n!uptime"
        for text, expected in ((response, []), (other, []), (request, ["!uptime"])):
            messages, _ = self.poll(envelope("+1555", text))
            with self.subTest(text=text):
                self.assertEqual([m.text for m in messages], expected)

    def test_a_metadata_block_with_no_body_is_skipped(self) -> None:
        messages, _ = self.poll(envelope("+1555", "cc-intent: request\n\n"))
        self.assertEqual(messages, [])


class SignalMetadata(unittest.TestCase):
    def test_a_leading_block_of_known_keys_is_split_from_the_body(self) -> None:
        metadata, body = _split_signal_metadata_block(
            "cc-intent: request\nCC-Target: crew-chief\n\nhello\nworld"
        )
        self.assertEqual(metadata, {"cc-intent": "request", "cc-target": "crew-chief"})
        self.assertEqual(body, "hello\nworld")

    def test_anything_else_is_left_whole(self) -> None:
        for text in (
            "",
            "plain message",
            "cc-unknown: x\n\nbody",
            "cc-intent: request\nnot metadata\n\nbody",
            "cc-intent: request",
            "\ncc-intent: request\n\nbody",
        ):
            with self.subTest(text=text):
                metadata, body = _split_signal_metadata_block(text)
                self.assertEqual((metadata, body), ({}, text))

    def test_explicit_signal_requests(self) -> None:
        self.assertTrue(_is_explicit_signal_request("anything", {"cc-intent": "request"}))
        self.assertFalse(_is_explicit_signal_request("anything", {"cc-intent": "response"}))
        for text in ("!run", "  [crew-chief] hi", "Crew Chief, status", "@chief status"):
            self.assertTrue(_is_explicit_signal_request(text, {}), text)
        for text in ("chiefly concerned", "hello"):
            self.assertFalse(_is_explicit_signal_request(text, {}), text)


class SignalReply(unittest.TestCase):
    def test_failures_to_send_are_logged_not_raised(self) -> None:
        cfg = SignalConfig(enabled=True, shock_relay_dir="/relay", config_path="/relay/c.yaml")
        for outcome in (
            {"return_value": done(returncode=1, stderr="bad")},
            {"side_effect": subprocess.TimeoutExpired("send", 30)},
            {"side_effect": FileNotFoundError()},
        ):
            with self.subTest(outcome=outcome), mock.patch(RUN, **outcome):
                reply_signal(cfg, "+1555", "text")


class GmailPolling(unittest.TestCase):
    def cfg(self, **kwargs) -> GmailConfig:
        base = {
            "enabled": True,
            "shock_relay_dir": "/relay",
            "config_path": "/relay/c.yaml",
            "trusted_senders": ["alice@example.com"],
            "reply_to": "me@example.com",
        }
        return GmailConfig(**{**base, **kwargs})

    def message(self, **kwargs) -> dict:
        return {
            "uid": 1,
            "from": "Alice <ALICE@example.com>",
            "subject": "hi",
            "text": "!uptime",
            **kwargs,
        }

    def poll(self, *messages: dict, cfg: GmailConfig | None = None):
        payload = json.dumps({"messages": list(messages)})
        with mock.patch(RUN, return_value=done(payload)):
            return poll_gmail(cfg or self.cfg())

    def test_unconfigured_never_runs_the_mail_script(self) -> None:
        for cfg in (self.cfg(config_path=""), self.cfg(shock_relay_dir="")):
            with self.subTest(cfg=cfg), mock.patch(RUN) as run:
                self.assertEqual(poll_gmail(cfg), [])
            run.assert_not_called()

    def test_a_failing_mail_script_yields_nothing_rather_than_raising(self) -> None:
        for outcome in (
            {"side_effect": FileNotFoundError()},
            {"side_effect": subprocess.TimeoutExpired("check_inbox", 60)},
            {"return_value": done(returncode=2, stderr="auth failed", stdout="partial")},
            {"return_value": done(stdout="not json")},
        ):
            with self.subTest(outcome=outcome), mock.patch(RUN, **outcome):
                self.assertEqual(poll_gmail(self.cfg()), [])

    def test_stderr_noise_on_success_does_not_stop_the_poll(self) -> None:
        payload = json.dumps({"messages": [self.message()]})
        with mock.patch(RUN, return_value=done(payload, stderr="deprecation warning")):
            self.assertEqual(len(poll_gmail(self.cfg())), 1)

    def test_the_sender_address_is_compared_case_insensitively_without_the_display_name(
        self,
    ) -> None:
        messages = self.poll(self.message(), cfg=self.cfg(trusted_senders=["Alice@Example.com"]))
        self.assertEqual([m.sender for m in messages], ["alice@example.com"])

    def test_an_untrusted_sender_is_ignored(self) -> None:
        self.assertEqual(self.poll(self.message(**{"from": "mallory@example.com"})), [])

    def test_an_empty_body_is_skipped(self) -> None:
        self.assertEqual(self.poll(self.message(text="", snippet="")), [])

    def test_mail_for_another_service_without_request_intent_is_skipped(self) -> None:
        for headers in (
            {"X-Portfolio-Service": "intake"},
            {"X-Portfolio-Service": "intake", "X-Crew-Chief-Intent": "response"},
            {"X-Crew-Chief-Intent": "response"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.poll(self.message(headers=headers)), [])

    def test_mail_declaring_itself_a_request_is_kept_even_from_another_service(self) -> None:
        headers = {"X-Portfolio-Service": "intake", "X-Crew-Chief-Intent": "request"}
        self.assertEqual(len(self.poll(self.message(headers=headers))), 1)

    def test_mail_from_our_own_address_needs_an_explicit_request(self) -> None:
        cfg = self.cfg(trusted_senders=["me@example.com"])
        own = {"from": "me@example.com"}
        self.assertEqual(self.poll(self.message(**own), cfg=cfg), [])
        for extra in (
            {"subject": "[crew-chief] status"},
            {"text": "[crew-chief] status"},
            {"subject": "Re: [intake] receipt"},
            {"headers": {"X-Crew-Chief-Intent": "request"}},
        ):
            with self.subTest(extra=extra):
                self.assertEqual(len(self.poll(self.message(**own, **extra), cfg=cfg)), 1)

    def test_our_own_reply_marker_anywhere_in_the_message_drops_it(self) -> None:
        for field in ("text", "body", "snippet", "html"):
            message = self.message(**{field: f"quoted\n{_REPLY_LOOP_MARKER}"})
            if field != "text":
                message["text"] = "!uptime"
            with self.subTest(field=field):
                self.assertEqual(self.poll(message), [])

    def test_auto_replies_are_dropped(self) -> None:
        self.assertEqual(self.poll(self.message(headers={"Auto-Submitted": "auto-replied"})), [])
        self.assertEqual(len(self.poll(self.message(headers={"Auto-Submitted": "no"}))), 1)

    def test_excluded_subjects_are_dropped(self) -> None:
        cfg = self.cfg(subject_exclude_patterns=["[intake]"])
        self.assertEqual(self.poll(self.message(subject="[intake] processed"), cfg=cfg), [])


class GmailHelpers(unittest.TestCase):
    def test_headers_are_lower_cased_trimmed_and_blank_names_dropped(self) -> None:
        raw = {"headers": {" X-Auto ": " 1 ", "": "skipped", "Other": 5}}
        self.assertEqual(_gmail_headers(raw), {"x-auto": "1", "other": "5"})

    def test_headers_that_are_not_a_mapping_are_empty(self) -> None:
        for value in (None, "x", ["a"], 5):
            self.assertEqual(_gmail_headers({"headers": value}), {})
        self.assertEqual(_gmail_headers({}), {})

    def test_the_body_comes_from_text_then_body_then_snippet(self) -> None:
        self.assertEqual(_gmail_body_text({"text": "t", "body": "b", "snippet": "s"}), "t")
        self.assertEqual(_gmail_body_text({"body": "b", "snippet": "s"}), "b")
        self.assertEqual(_gmail_body_text({"snippet": "s"}), "s")
        self.assertEqual(_gmail_body_text({"text": 5, "body": ""}), "")

    def test_every_body_like_field_is_scanned_for_the_loop_marker(self) -> None:
        raw = {"text": "t", "body": "b", "snippet": "s", "html": "h", "other": "o", "x": 1}
        self.assertEqual(_gmail_body_candidates(raw), ["t", "b", "s", "h"])

    def test_explicit_requests_by_intent_prefix_or_service_reply(self) -> None:
        explicit = _is_explicit_crew_chief_request
        self.assertTrue(explicit({"headers": {"x-crew-chief-intent": "request"}}, "", ""))
        self.assertFalse(
            explicit(
                {"headers": {"x-crew-chief-intent": "response"}}, "[crew-chief] x", "[crew-chief]"
            )
        )
        self.assertTrue(explicit({}, "[crew-chief] status", ""))
        self.assertTrue(explicit({}, "hi", "  [CREW-CHIEF] status"))
        self.assertTrue(explicit({}, "Re: [intake] receipt", ""))
        self.assertFalse(explicit({}, "Re: [intake] receipt", "", ("re: [other]",)))
        self.assertFalse(explicit({}, "hello", "world"))

    def msg(self, **raw) -> IncomingMessage:
        return IncomingMessage("gmail", " Alice@Example.com ", "body text", "Subject", raw)

    def test_a_message_is_identified_by_message_id_then_uid_then_content(self) -> None:
        self.assertEqual(
            _gmail_message_fingerprint(self.msg(message_id=" <a@b> ", uid=1)), "message_id:<a@b>"
        )
        self.assertEqual(
            _gmail_message_fingerprint(self.msg(mailbox="INBOX", uid=7)), "uid:INBOX:7"
        )
        fallback = _gmail_message_fingerprint(self.msg(timestamp="2026-01-01"))
        self.assertTrue(
            fallback.startswith("fallback:alice@example.com|subject|2026-01-01|body text")
        )
        bare = IncomingMessage("gmail", "a", "t")
        self.assertEqual(_gmail_message_fingerprint(bare), "fallback:a|||t")

    def test_a_uid_without_a_mailbox_is_not_enough_to_identify_a_message(self) -> None:
        self.assertTrue(_gmail_message_fingerprint(self.msg(uid=7)).startswith("fallback:"))

    def test_a_message_is_claimed_only_the_first_time(self) -> None:
        seen: set[str] = set()
        message = self.msg(message_id="<a@b>")
        self.assertTrue(_claim_gmail_message(message, seen))
        self.assertFalse(_claim_gmail_message(message, seen))
        self.assertTrue(_claim_gmail_message(self.msg(message_id="<other>"), seen))


class GmailReply(unittest.TestCase):
    def cfg(self) -> GmailConfig:
        return GmailConfig(enabled=True, shock_relay_dir="/relay", config_path="/relay/c.yaml")

    def test_the_reply_carries_the_loop_marker_and_a_response_intent(self) -> None:
        with mock.patch(RUN, return_value=done()) as run:
            reply_gmail(self.cfg(), "alice@example.com", "status", "all good")
        cmd = run.call_args.args[0]
        self.assertIn("X-Crew-Chief-Intent: response", cmd)
        self.assertIn("Re: status", cmd)
        self.assertTrue(cmd[-1].endswith(_REPLY_LOOP_MARKER))

    def test_an_empty_subject_gets_a_default_one(self) -> None:
        with mock.patch(RUN, return_value=done()) as run:
            reply_gmail(self.cfg(), "a@example.com", "", "x")
        self.assertIn("crew-chief reply", run.call_args.args[0])

    def test_failures_to_send_are_logged_not_raised(self) -> None:
        for outcome in (
            {"return_value": done(returncode=1, stderr="smtp refused", stdout="x")},
            {"return_value": done(stderr="warning only")},
            {"side_effect": subprocess.TimeoutExpired("send", 30)},
            {"side_effect": FileNotFoundError()},
        ):
            with self.subTest(outcome=outcome), mock.patch(RUN, **outcome):
                reply_gmail(self.cfg(), "a@example.com", "s", "b")


class CommandExtraction(unittest.TestCase):
    ALLOWED = ["uptime", "df*"]

    def ask(self, answer):
        client = mock.Mock()
        if isinstance(answer, Exception):
            client.chat.side_effect = answer
        else:
            client.chat.return_value = answer
        return extract_command_via_llm("how busy is it", client, self.ALLOWED), client

    def test_a_json_command_is_returned_trimmed(self) -> None:
        command, client = self.ask('Sure: {"command": "  uptime "} done')
        self.assertEqual(command, "uptime")
        system = client.chat.call_args.args[0][0]["content"]
        self.assertIn("uptime", system)
        self.assertIn("df*", system)

    def test_anything_unusable_is_no_command(self) -> None:
        for answer in (
            '{"command": null, "reason": "ambiguous"}',
            '{"command": ""}',
            "I cannot help with that",
            "{not json}",
            "} before {",
            "",
            RuntimeError("model down"),
        ):
            with self.subTest(answer=answer):
                self.assertIsNone(self.ask(answer)[0])

    def test_direct_commands_skip_the_model_and_the_bare_prefix_is_nothing(self) -> None:
        cfg = ListenerConfig()
        client = mock.Mock()
        self.assertEqual(resolve_command("  !  df -h ", cfg, client), "df -h")
        self.assertIsNone(resolve_command("!", cfg, client))
        client.chat.assert_not_called()

    def test_natural_language_is_routed_through_the_model_only_when_enabled(self) -> None:
        cfg = ListenerConfig()
        cfg.llm.natural_language = False
        client = mock.Mock()
        self.assertIsNone(resolve_command("how busy is it", cfg, client))
        client.chat.assert_not_called()
        cfg.llm.natural_language = True
        client.chat.return_value = '{"command": "uptime"}'
        self.assertEqual(resolve_command("how busy is it", cfg, client), "uptime")


class ProcessMessage(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = ListenerConfig()
        self.cfg.llm.natural_language = True
        self.client = mock.Mock(model="m")
        self.dispatcher = mock.Mock()
        self.dispatcher.run.return_value = mock.Mock(reply_text=lambda: "output")
        self.replies = {
            "signal": mock.patch.object(listener, "reply_signal").start(),
            "gmail": mock.patch.object(listener, "reply_gmail").start(),
        }
        self.addCleanup(mock.patch.stopall)

    def process(self, text="!uptime", channel="signal", agent=None, gate=None):
        msg = IncomingMessage(
            channel, "+1555" if channel == "signal" else "a@example.com", text, "subj"
        )
        return _process_message(msg, self.cfg, self.client, self.dispatcher, agent, gate)

    def test_a_direct_command_is_dispatched_and_the_reply_says_no_model_was_used(self) -> None:
        self.assertTrue(self.process("!uptime"))
        self.dispatcher.run.assert_called_once_with("uptime")
        reply = self.replies["signal"].call_args.args[2]
        self.assertTrue(reply.startswith("[Model: none — direct command]"))
        self.assertTrue(reply.endswith("output"))

    def test_a_natural_language_command_names_the_routing_model(self) -> None:
        self.client.chat.return_value = '{"command": "uptime"}'
        self.assertTrue(self.process("how busy"))
        self.assertIn("[Model: m (command routing)]", self.replies["signal"].call_args.args[2])

    def test_a_message_with_no_actionable_command_gets_no_reply(self) -> None:
        self.client.chat.return_value = '{"command": null}'
        self.assertFalse(self.process("what is the meaning of life"))
        self.dispatcher.run.assert_not_called()
        self.replies["signal"].assert_not_called()

    def test_replies_go_back_on_the_channel_they_came_from(self) -> None:
        self.process("!uptime", channel="signal")
        self.replies["gmail"].assert_not_called()
        self.cfg.gmail.reply_to = "operator@example.com"
        self.process("!uptime", channel="gmail")
        args = self.replies["gmail"].call_args.args
        self.assertEqual((args[1], args[2]), ("operator@example.com", "subj"))
        self.cfg.gmail.reply_to = ""
        self.process("!uptime", channel="gmail")
        self.assertEqual(self.replies["gmail"].call_args.args[1], "a@example.com")

    def test_the_decision_gate_can_drop_a_chatty_message_but_never_a_direct_command(self) -> None:
        gate = mock.Mock()
        gate.should_skip.return_value = (
            True,
            SimpleNamespace(intent="chat", confidence=0.9, model="g"),
        )
        self.assertFalse(self.process("hello there", gate=gate))
        self.dispatcher.run.assert_not_called()
        self.assertTrue(self.process("!uptime", gate=gate))
        gate.should_skip.assert_called_once()

    def test_the_gate_is_only_consulted_in_natural_language_mode(self) -> None:
        self.cfg.llm.natural_language = False
        gate = mock.Mock()
        self.process("!uptime", gate=gate)
        gate.should_skip.assert_not_called()

    def test_with_an_agent_the_message_goes_to_the_agent_and_the_model_is_reported(self) -> None:
        agent = mock.Mock(last_used_model="big-model")
        agent.run.return_value = "agent answer"
        self.assertTrue(self.process("do a thing", agent=agent))
        agent.run.assert_called_once_with("do a thing")
        self.dispatcher.run.assert_not_called()
        reply = self.replies["signal"].call_args.args[2]
        self.assertTrue(reply.startswith("[Model: big-model]"))
        self.assertIn("agent answer", reply)

    def test_an_agent_that_does_not_know_its_model_is_reported_as_unknown(self) -> None:
        agent = mock.Mock(spec=["run"])
        agent.run.return_value = "x"
        self.process("go", agent=agent)
        self.assertIn("[Model: unknown]", self.replies["signal"].call_args.args[2])


class RunLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = ListenerConfig()
        self.cfg.poll_interval_seconds = 5
        self.signal = mock.patch.object(listener, "poll_signal", return_value=[]).start()
        self.gmail = mock.patch.object(listener, "poll_gmail", return_value=[]).start()
        self.process = mock.patch.object(listener, "_process_message", return_value=True).start()
        mock.patch.object(listener, "CrewChiefClient").start()
        mock.patch.object(listener, "Dispatcher").start()
        mock.patch.object(listener.listener_gate, "build", return_value=None).start()
        self.sleep = mock.patch.object(listener.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    @staticmethod
    def sig(n):
        return [IncomingMessage("signal", f"+{i}", "!x") for i in range(n)]

    @staticmethod
    def mail(ids):
        return [IncomingMessage("gmail", "a@example.com", "!x", raw={"message_id": i}) for i in ids]

    def test_once_runs_one_cycle_and_does_not_sleep(self) -> None:
        self.signal.return_value = self.sig(2)
        run(self.cfg, once=True)
        self.assertEqual(self.process.call_count, 2)
        self.sleep.assert_not_called()

    def test_the_reply_cap_stops_further_replies_in_that_cycle_across_channels(self) -> None:
        self.cfg.max_replies_per_cycle = 2
        self.signal.return_value = self.sig(3)
        self.gmail.return_value = self.mail(["a", "b"])
        run(self.cfg, once=True)
        # two replies sent in total: the third Signal message and both emails are dropped
        self.assertEqual(self.process.call_count, 2)

    def test_the_cap_counts_replies_not_messages(self) -> None:
        self.cfg.max_replies_per_cycle = 1
        self.process.side_effect = [False, True, True]
        self.signal.return_value = self.sig(3)
        run(self.cfg, once=True)
        # the first message got no reply, so it did not use the budget
        self.assertEqual(self.process.call_count, 2)

    def test_zero_means_no_cap(self) -> None:
        self.cfg.max_replies_per_cycle = 0
        self.signal.return_value = self.sig(5)
        run(self.cfg, once=True)
        self.assertEqual(self.process.call_count, 5)

    def test_an_email_already_handled_in_an_earlier_cycle_is_not_answered_twice(self) -> None:
        self.gmail.return_value = self.mail(["same"])
        cycles = iter([None, None, KeyboardInterrupt])

        def stop(_):
            outcome = next(cycles)
            if outcome:
                raise outcome

        self.sleep.side_effect = stop
        with self.assertRaises(KeyboardInterrupt):
            run(self.cfg)
        self.assertEqual(self.process.call_count, 1)

    def test_between_cycles_it_sleeps_out_the_rest_of_the_interval(self) -> None:
        self.sleep.side_effect = KeyboardInterrupt
        with (
            mock.patch.object(listener.time, "monotonic", side_effect=[100.0, 102.0]),
            self.assertRaises(KeyboardInterrupt),
        ):
            run(self.cfg)
        self.sleep.assert_called_once_with(3.0)

    def test_a_cycle_that_overran_the_interval_does_not_sleep(self) -> None:
        self.sleep.side_effect = AssertionError("must not sleep")
        # cycle one starts at 0 and ends at 99 (a 5 s interval); cycle two starts at 100
        self.signal.side_effect = [[], KeyboardInterrupt]
        with (
            mock.patch.object(listener.time, "monotonic", side_effect=[0.0, 99.0, 100.0]),
            self.assertRaises(KeyboardInterrupt),
        ):
            run(self.cfg)


class AgentConstruction(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = ListenerConfig()
        self.cfg.agent.enabled = True
        self.cfg.agent.provider = "fallback"
        self.cfg.agent.fallback_chain = ["ollama", "claude-cli"]
        self.cfg.agent.confidence_threshold = 0.5
        self.cfg.agent.timeout_seconds = 77
        self.cfg.llm.timeout_seconds = 11
        self.names = {}
        for name in ("poll_signal", "poll_gmail"):
            mock.patch.object(listener, name, return_value=[]).start()
        mock.patch.object(listener, "CrewChiefClient").start()
        mock.patch.object(listener, "Dispatcher").start()
        mock.patch.object(listener.listener_gate, "build", return_value=None).start()
        mock.patch.object(
            listener, "build_tools", return_value=[SimpleNamespace(name="shell")]
        ).start()
        self.agent = mock.patch.object(listener, "Agent").start()
        self.cascade = mock.patch.object(listener, "AgentCascade").start()
        self.build_provider = mock.patch.object(
            listener, "build_provider", side_effect=lambda n, c: f"P:{n}"
        ).start()
        self.get_provider = mock.patch.object(
            listener, "get_provider", return_value="CHAIN"
        ).start()
        self.process = mock.patch.object(listener, "_process_message", return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def go(self):
        run(self.cfg, once=True)

    def test_a_fallback_provider_with_a_threshold_builds_one_agent_per_provider(self) -> None:
        self.go()
        providers = [c.kwargs["provider"] for c in self.agent.call_args_list]
        self.assertEqual(providers, ["P:ollama", "P:claude-cli"])
        self.assertTrue(
            all(c.kwargs["confidence_threshold"] == 0.5 for c in self.agent.call_args_list)
        )
        self.cascade.assert_called_once()
        self.get_provider.assert_not_called()

    def test_providers_are_built_with_the_agent_timeout_not_the_listeners(self) -> None:
        self.go()
        config = self.build_provider.call_args.args[1]
        self.assertEqual(config.timeout_seconds, 77)

    def test_a_zero_agent_timeout_falls_back_to_the_llm_timeout(self) -> None:
        self.cfg.agent.timeout_seconds = 0
        self.go()
        self.assertEqual(self.build_provider.call_args.args[1].timeout_seconds, 11)

    def test_a_zero_threshold_or_a_named_provider_builds_one_agent(self) -> None:
        for threshold, provider in ((0.0, "fallback"), (0.5, "ollama")):
            self.agent.reset_mock()
            self.cascade.reset_mock()
            self.cfg.agent.confidence_threshold = threshold
            self.cfg.agent.provider = provider
            with self.subTest(threshold=threshold, provider=provider):
                self.go()
                self.agent.assert_called_once()
                self.cascade.assert_not_called()
                self.assertEqual(self.agent.call_args.kwargs["provider"], "CHAIN")

    def test_the_agent_provider_defaults_to_the_llm_provider_and_chain(self) -> None:
        self.cfg.agent.provider = ""
        self.cfg.agent.fallback_chain = []
        self.cfg.llm.provider = "fallback"
        self.cfg.llm.fallback_chain = ["codex-cli"]
        self.go()
        self.assertEqual([c.kwargs["provider"] for c in self.agent.call_args_list], ["P:codex-cli"])

    def test_the_agent_is_handed_to_message_processing_only_when_enabled(self) -> None:
        from crew_chief import listener as module

        self.cfg.agent.enabled = False
        module.poll_signal.return_value = [IncomingMessage("signal", "+1", "!x")]
        self.go()
        self.assertIsNone(self.process.call_args.args[4])
        self.agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
