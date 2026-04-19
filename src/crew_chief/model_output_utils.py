"""Helpers for recovering from malformed model output payloads."""

from __future__ import annotations

from typing import Any

_SCHEMA_STUB_KEYS = frozenset(
    {
        "default",
        "description",
        "enum",
        "examples",
        "format",
        "items",
        "maxLength",
        "minLength",
        "pattern",
        "title",
        "type",
    }
)


def extract_echoed_shell_command(name: str, arguments: Any) -> str | None:
    """Recover a shell command when the model echoed the tool schema.

    Some local tool-capable models incorrectly place the intended shell command
    in ``name`` and echo the ``command`` parameter schema back in
    ``parameters``/``arguments`` instead of producing a proper tool call.
    This helper recognizes that narrow shape and returns the command text.
    """

    if not isinstance(name, str):
        return None
    command = name.strip()
    if not command:
        return None

    if not isinstance(arguments, dict) or set(arguments) != {"command"}:
        return None

    command_arg = arguments.get("command")
    if not isinstance(command_arg, dict):
        return None
    if command_arg.get("type") != "string":
        return None
    if not any(key in command_arg for key in ("description", "title", "examples")):
        return None
    if not set(command_arg).issubset(_SCHEMA_STUB_KEYS):
        return None

    return command


def extract_echoed_shell_command_from_payload(parsed: Any) -> str | None:
    """Return a recovered shell command from a parsed JSON payload if present."""

    if not isinstance(parsed, dict):
        return None
    return extract_echoed_shell_command(
        parsed.get("name", ""),
        parsed.get("parameters", parsed.get("arguments")),
    )
