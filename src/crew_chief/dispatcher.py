"""crew_chief.dispatcher — safe, allowlisted command execution.

All commands pass through an fnmatch allowlist before execution.  No shell
expansion is used (``shell=False``), so shell injection via message text is
not possible at the subprocess level.

Usage::

    from crew_chief.dispatcher import Dispatcher, DispatchResult

    d = Dispatcher(allowed_commands=["df*", "uptime", "hostname"])
    result = d.run("df -h")
    print(result.output)
"""

from __future__ import annotations

import fnmatch
import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class DispatchResult:
    """Outcome of a single dispatched command."""

    command: str
    allowed: bool
    output: str
    returncode: int | None
    truncated: bool
    error: str = ""

    @property
    def success(self) -> bool:
        return self.allowed and self.returncode == 0

    def reply_text(self) -> str:
        """Format a human-readable reply suitable for sending back to the user."""
        if not self.allowed:
            return f"Command not permitted: {self.command}"
        if self.error:
            return f"Error running `{self.command}`: {self.error}"
        suffix = "\n[output truncated]" if self.truncated else ""
        header = f"$ {self.command}\n"
        return header + (self.output or "(no output)") + suffix


class Dispatcher:
    """Execute commands subject to an allowlist and resource limits.

    Parameters
    ----------
    allowed_commands:
        List of fnmatch-style glob patterns.  A command is permitted when
        its full string matches at least one pattern.  Example patterns::

            ["df*", "free*", "uptime", "systemctl status *"]

    timeout_seconds:
        Hard timeout per command.  Commands that exceed this are killed and
        the result contains ``error="Command timed out."``.

    max_output_bytes:
        Combined stdout + stderr output is capped at this many bytes in the
        reply.  The raw bytes are truncated at the UTF-8 boundary and
        ``result.truncated`` is set to ``True`` when the cap is hit.
    """

    def __init__(
        self,
        allowed_commands: list[str],
        timeout_seconds: int = 30,
        max_output_bytes: int = 2000,
    ) -> None:
        self.allowed_commands = allowed_commands
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def is_allowed(self, command: str) -> bool:
        """Return True if *command* matches at least one allowlist pattern."""
        return any(fnmatch.fnmatch(command, p) for p in self.allowed_commands)

    def run(self, command: str) -> DispatchResult:
        """Execute *command* and return a :class:`DispatchResult`.

        The command is first checked against the allowlist.  If not permitted,
        ``result.allowed`` is ``False`` and no subprocess is launched.

        The command string is split with :func:`shlex.split` — shell operators
        (``|``, ``&&``, ``>`` etc.) are treated as literal arguments, not
        interpreted by a shell.
        """
        if not self.is_allowed(command):
            return DispatchResult(
                command=command,
                allowed=False,
                output="",
                returncode=None,
                truncated=False,
            )

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return DispatchResult(
                command=command,
                allowed=True,
                output="",
                returncode=1,
                truncated=False,
                error=f"Cannot parse command: {exc}",
            )

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return DispatchResult(
                command=command,
                allowed=True,
                output="",
                returncode=-1,
                truncated=False,
                error="Command timed out.",
            )
        except FileNotFoundError:
            return DispatchResult(
                command=command,
                allowed=True,
                output="",
                returncode=127,
                truncated=False,
                error=f"Command not found: {argv[0]}",
            )

        combined = (proc.stdout + proc.stderr).strip()
        encoded = combined.encode("utf-8", errors="replace")
        truncated = len(encoded) > self.max_output_bytes
        if truncated:
            combined = encoded[: self.max_output_bytes].decode("utf-8", errors="replace").strip()

        return DispatchResult(
            command=command,
            allowed=True,
            output=combined,
            returncode=proc.returncode,
            truncated=truncated,
        )
