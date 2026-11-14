"""An ignored message stays unread, so each poll sees it again; its decision is logged once."""

from __future__ import annotations

import json
import logging
import subprocess
import unittest
from unittest import mock

from crew_chief import listener
from crew_chief.config_loader import GmailConfig
from crew_chief.listener import IncomingMessage, _claim_gmail_message, poll_gmail

RUN = "crew_chief.listener.subprocess.run"


def poll(*messages: dict):
    cfg = GmailConfig(
        enabled=True,
        shock_relay_dir="/relay",
        config_path="/relay/c.yaml",
        trusted_senders=["alice@example.com"],
        reply_to="me@example.com",
    )
    payload = json.dumps({"messages": list(messages)})
    done = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
    with mock.patch(RUN, return_value=done):
        return poll_gmail(cfg)


class LogOnce(unittest.TestCase):
    def setUp(self) -> None:
        listener._logged_once.clear()
        self.addCleanup(listener._logged_once.clear)

    def test_an_untrusted_sender_is_logged_on_the_first_poll_only(self) -> None:
        stranger = {"message_id": "<a@x>", "from": "bob@example.com", "text": "hi"}
        with self.assertLogs("crew_chief.listener", logging.DEBUG) as first:
            poll(stranger)
        self.assertTrue(any("untrusted sender bob@example.com" in line for line in first.output))
        with self.assertNoLogs("crew_chief.listener", logging.DEBUG):
            poll(stranger)
            poll(stranger)

    def test_a_different_message_from_the_same_sender_is_logged_again(self) -> None:
        poll({"message_id": "<a@x>", "from": "bob@example.com", "text": "hi"})
        with self.assertLogs("crew_chief.listener", logging.DEBUG):
            poll({"message_id": "<b@x>", "from": "bob@example.com", "text": "hi"})

    def test_a_repeated_warning_is_logged_once_so_it_cannot_pin_the_log_level(self) -> None:
        auto = {
            "message_id": "<c@x>",
            "from": "alice@example.com",
            "text": "away",
            "headers": {"Auto-Submitted": "auto-replied"},
        }
        with self.assertLogs("crew_chief.listener", logging.WARNING) as first:
            poll(auto)
        self.assertEqual(len(first.output), 1)
        with self.assertNoLogs("crew_chief.listener", logging.WARNING):
            poll(auto)

    def test_an_already_processed_message_is_reported_once(self) -> None:
        msg = IncomingMessage(
            channel="gmail",
            sender="alice@example.com",
            text="!date",
            subject="s",
            raw={"message_id": "<d@x>"},
        )
        seen: set[str] = set()
        self.assertTrue(_claim_gmail_message(msg, seen))
        with self.assertLogs("crew_chief.listener", logging.INFO) as first:
            self.assertFalse(_claim_gmail_message(msg, seen))
        self.assertEqual(len(first.output), 1)
        with self.assertNoLogs("crew_chief.listener", logging.INFO):
            self.assertFalse(_claim_gmail_message(msg, seen))

    def test_the_memory_is_bounded(self) -> None:
        with mock.patch.object(listener, "_LOGGED_ONCE_LIMIT", 3):
            for i in range(10):
                listener._log_once({"message_id": f"<{i}>"}, logging.DEBUG, "x %s", i)
        self.assertLessEqual(len(listener._logged_once), 3)
