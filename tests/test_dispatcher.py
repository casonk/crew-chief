"""Tests for crew_chief.dispatcher — all offline."""

from __future__ import annotations

import unittest

from crew_chief.dispatcher import Dispatcher, DispatchResult


class TestIsAllowed(unittest.TestCase):
    def setUp(self):
        self.d = Dispatcher(allowed_commands=["df*", "free*", "uptime", "ls *"])

    def test_exact_match(self):
        self.assertTrue(self.d.is_allowed("uptime"))

    def test_glob_prefix(self):
        self.assertTrue(self.d.is_allowed("df -h"))

    def test_glob_with_arg(self):
        self.assertTrue(self.d.is_allowed("ls /tmp"))

    def test_not_allowed(self):
        self.assertFalse(self.d.is_allowed("rm -rf /"))

    def test_empty_allowed_commands(self):
        d = Dispatcher(allowed_commands=[])
        self.assertFalse(d.is_allowed("uptime"))

    def test_wildcard_allows_all(self):
        d = Dispatcher(allowed_commands=["*"])
        self.assertTrue(d.is_allowed("rm -rf /"))


class TestDispatcherRun(unittest.TestCase):
    def setUp(self):
        self.d = Dispatcher(
            allowed_commands=["echo *", "true", "false"],
            timeout_seconds=5,
            max_output_bytes=100,
        )

    def test_not_allowed_returns_denied_result(self):
        result = self.d.run("rm -rf /")
        self.assertFalse(result.allowed)
        self.assertIsNone(result.returncode)
        self.assertIn("not permitted", result.reply_text())

    def test_successful_command(self):
        result = self.d.run("echo hello")
        self.assertTrue(result.allowed)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.output)
        self.assertTrue(result.success)

    def test_nonzero_exit_code(self):
        result = self.d.run("false")
        self.assertTrue(result.allowed)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(result.success)

    def test_command_not_found(self):
        d = Dispatcher(allowed_commands=["*"])
        result = d.run("nonexistent_binary_xyz_abc_123")
        self.assertTrue(result.allowed)
        self.assertEqual(result.returncode, 127)
        self.assertIn("not found", result.error)

    def test_timeout_expired(self):
        d = Dispatcher(allowed_commands=["sleep *"], timeout_seconds=1)
        result = d.run("sleep 10")
        self.assertTrue(result.allowed)
        self.assertEqual(result.returncode, -1)
        self.assertIn("timed out", result.error)

    def test_output_truncated(self):
        d = Dispatcher(allowed_commands=["echo *"], max_output_bytes=5)
        result = d.run("echo 0123456789abcdef")
        self.assertTrue(result.truncated)
        self.assertIn("[output truncated]", result.reply_text())
        self.assertLessEqual(len(result.output.encode()), 5)

    def test_output_not_truncated_when_small(self):
        result = self.d.run("echo hi")
        self.assertFalse(result.truncated)

    def test_reply_text_includes_command(self):
        result = self.d.run("echo world")
        self.assertIn("$ echo world", result.reply_text())

    def test_reply_text_denied(self):
        result = self.d.run("sudo rm /etc/passwd")
        self.assertIn("not permitted", result.reply_text())

    def test_bad_shell_quoting(self):
        d = Dispatcher(allowed_commands=["*"])
        result = d.run("echo 'unterminated")
        self.assertTrue(result.allowed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot parse", result.error)


class TestDispatchResult(unittest.TestCase):
    def test_success_property(self):
        r = DispatchResult(command="x", allowed=True, output="out", returncode=0, truncated=False)
        self.assertTrue(r.success)

    def test_not_success_if_not_allowed(self):
        r = DispatchResult(command="x", allowed=False, output="", returncode=None, truncated=False)
        self.assertFalse(r.success)

    def test_not_success_if_nonzero(self):
        r = DispatchResult(command="x", allowed=True, output="", returncode=1, truncated=False)
        self.assertFalse(r.success)

    def test_reply_text_no_output(self):
        r = DispatchResult(command="uptime", allowed=True, output="", returncode=0, truncated=False)
        self.assertIn("(no output)", r.reply_text())

    def test_reply_text_with_error(self):
        r = DispatchResult(
            command="missing",
            allowed=True,
            output="",
            returncode=127,
            truncated=False,
            error="Command not found: missing",
        )
        self.assertIn("Command not found", r.reply_text())


if __name__ == "__main__":
    unittest.main()
