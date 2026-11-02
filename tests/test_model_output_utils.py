"""Recovering a shell command from a model that echoed the tool schema back.

The narrow shape is the whole point: a command is run only when the model clearly
confused the schema with a call. Anything else must stay unrecovered, because the
recovered text is executed.
"""

from __future__ import annotations

import unittest

from crew_chief.model_output_utils import (
    extract_echoed_shell_command,
    extract_echoed_shell_command_from_payload,
)

STUB = {"command": {"type": "string", "description": "the command to run"}}


class ExtractEchoedShellCommand(unittest.TestCase):
    def test_the_schema_echo_yields_the_command_from_the_name(self) -> None:
        self.assertEqual(extract_echoed_shell_command("df -h", STUB), "df -h")

    def test_the_name_is_trimmed(self) -> None:
        self.assertEqual(extract_echoed_shell_command("  uptime \n", STUB), "uptime")

    def test_any_one_documentation_key_is_enough(self) -> None:
        for key in ("description", "title", "examples"):
            with self.subTest(key=key):
                stub = {"command": {"type": "string", key: "x"}}
                self.assertEqual(extract_echoed_shell_command("ls", stub), "ls")

    def test_other_schema_keywords_may_accompany_it(self) -> None:
        stub = {"command": {"type": "string", "description": "d", "minLength": 1, "pattern": "."}}
        self.assertEqual(extract_echoed_shell_command("ls", stub), "ls")

    def test_the_name_must_be_non_empty_text(self) -> None:
        for name in ("", "   ", None, 5, ["ls"], b"ls"):
            with self.subTest(name=name):
                self.assertIsNone(extract_echoed_shell_command(name, STUB))  # type: ignore[arg-type]

    def test_the_arguments_must_be_exactly_the_command_parameter(self) -> None:
        for arguments in (
            None,
            "df -h",
            ["command"],
            {},
            {"cmd": STUB["command"]},
            {**STUB, "extra": 1},
        ):
            with self.subTest(arguments=arguments):
                self.assertIsNone(extract_echoed_shell_command("df -h", arguments))

    def test_a_real_value_for_the_parameter_is_not_an_echo(self) -> None:
        # a proper call puts a string here; only a schema object is recognised
        for value in ("rm -rf /", None, 5, ["ls"]):
            with self.subTest(value=value):
                self.assertIsNone(extract_echoed_shell_command("df -h", {"command": value}))

    def test_the_stub_must_describe_a_string(self) -> None:
        for kind in ("integer", "object", None):
            with self.subTest(type=kind):
                stub = {"command": {"type": kind, "description": "d"}}
                self.assertIsNone(extract_echoed_shell_command("ls", stub))
        self.assertIsNone(extract_echoed_shell_command("ls", {"command": {"description": "d"}}))

    def test_the_stub_must_carry_some_documentation(self) -> None:
        self.assertIsNone(extract_echoed_shell_command("ls", {"command": {"type": "string"}}))

    def test_the_stub_may_hold_only_schema_keywords(self) -> None:
        # an unrecognised key means this is not a bare schema echo
        stub = {"command": {"type": "string", "description": "d", "value": "rm -rf /"}}
        self.assertIsNone(extract_echoed_shell_command("ls", stub))


class ExtractFromPayload(unittest.TestCase):
    def test_parameters_or_arguments_are_both_accepted(self) -> None:
        for key in ("parameters", "arguments"):
            with self.subTest(key=key):
                self.assertEqual(
                    extract_echoed_shell_command_from_payload({"name": "date", key: STUB}), "date"
                )

    def test_parameters_win_over_arguments(self) -> None:
        payload = {"name": "date", "parameters": {"command": "x"}, "arguments": STUB}
        self.assertIsNone(extract_echoed_shell_command_from_payload(payload))

    def test_a_payload_that_is_not_an_object_yields_nothing(self) -> None:
        for payload in (None, "date", ["date"], 5):
            with self.subTest(payload=payload):
                self.assertIsNone(extract_echoed_shell_command_from_payload(payload))

    def test_a_missing_name_or_arguments_yields_nothing(self) -> None:
        self.assertIsNone(extract_echoed_shell_command_from_payload({"parameters": STUB}))
        self.assertIsNone(extract_echoed_shell_command_from_payload({"name": "date"}))
        self.assertIsNone(extract_echoed_shell_command_from_payload({}))


if __name__ == "__main__":
    unittest.main()
