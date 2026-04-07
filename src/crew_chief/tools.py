"""crew_chief.tools — built-in agent tools.

Each tool wraps a specific capability (shell execution, file I/O) behind a
uniform interface so the :class:`~crew_chief.agent.Agent` loop can execute
whichever tools the model requests.

Built-in tools
--------------
* :class:`ShellTool` — run an allowlisted shell command via
  :class:`~crew_chief.dispatcher.Dispatcher`.
* :class:`ReadFileTool` — read the text content of a file.
* :class:`WriteFileTool` — write text content to a file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from crew_chief.providers.base import ToolParam

log = logging.getLogger(__name__)


class Tool:
    """Base class for all agent tools.

    Subclasses must define :attr:`name`, :attr:`description`, and
    :attr:`parameters` (a JSON Schema *object*), and override :meth:`execute`.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    def execute(self, arguments: dict[str, Any]) -> str:  # noqa: ARG002
        raise NotImplementedError

    def to_param(self) -> ToolParam:
        """Return the :class:`~crew_chief.providers.base.ToolParam` descriptor."""
        return ToolParam(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


class ShellTool(Tool):
    """Execute an allowlisted shell command and return its output.

    Safety is enforced by the :class:`~crew_chief.dispatcher.Dispatcher`
    allowlist.  Commands not matching an allowed pattern are rejected before
    any subprocess is launched.
    """

    name = "shell"
    description = (
        "Execute a shell command from the configured allowlist and return the output. "
        "Only commands matching the allowed patterns will be run."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The exact shell command to execute (e.g. 'df -h' or 'uptime').",
            }
        },
        "required": ["command"],
    }

    def __init__(self, dispatcher: Any) -> None:
        """
        Parameters
        ----------
        dispatcher:
            A :class:`~crew_chief.dispatcher.Dispatcher` instance.
        """
        self.dispatcher = dispatcher

    def execute(self, arguments: dict[str, Any]) -> str:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "Error: no command provided."
        result = self.dispatcher.run(command)
        return result.reply_text()


class ReadFileTool(Tool):
    """Read the text content of a file at a given absolute path."""

    name = "read_file"
    description = (
        "Read and return the text content of a file. "
        "Provide an absolute path.  Only paths inside the configured allowed "
        "directories are accessible."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to read.",
            }
        },
        "required": ["path"],
    }

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        """
        Parameters
        ----------
        allowed_paths:
            Optional list of path prefixes the model is allowed to read.
            When *None* (or empty), all paths are permitted.
        """
        self.allowed_paths = allowed_paths or []

    def _check_path(self, path: str) -> str | None:
        """Return an error string if *path* is not permitted, else None."""
        if self.allowed_paths and not any(path.startswith(p) for p in self.allowed_paths):
            return f"Access denied: {path!r} is outside the allowed paths."
        return None

    def execute(self, arguments: dict[str, Any]) -> str:
        path = str(arguments.get("path", "")).strip()
        if not path:
            return "Error: no path provided."
        if err := self._check_path(path):
            return err
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return f"File not found: {path}"
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as exc:
            return f"Error reading {path}: {exc}"


class WriteFileTool(Tool):
    """Write (or overwrite) a file at a given absolute path."""

    name = "write_file"
    description = (
        "Write text content to a file, creating it or overwriting it if it exists. "
        "Provide an absolute path.  Only paths inside the configured allowed "
        "directories are writable.  Parent directories are created automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, allowed_paths: list[str] | None = None) -> None:
        self.allowed_paths = allowed_paths or []

    def _check_path(self, path: str) -> str | None:
        if self.allowed_paths and not any(path.startswith(p) for p in self.allowed_paths):
            return f"Access denied: {path!r} is outside the allowed paths."
        return None

    def execute(self, arguments: dict[str, Any]) -> str:
        path = str(arguments.get("path", "")).strip()
        content = str(arguments.get("content", ""))
        if not path:
            return "Error: no path provided."
        if err := self._check_path(path):
            return err
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} character(s) to {path}."
        except PermissionError:
            return f"Permission denied: {path}"
        except OSError as exc:
            return f"Error writing {path}: {exc}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_TOOL_NAMES = {"shell", "read_file", "write_file"}


def build_tools(cfg: Any) -> list[Tool]:
    """Build the tool list from a :class:`~crew_chief.config_loader.AgentConfig`.

    *cfg* must expose:

    * ``cfg.agent.tools`` — list of tool name strings
    * ``cfg.agent.allowed_paths`` — list of path prefixes for file tools
    * ``cfg.dispatch.*`` — dispatcher settings used by :class:`ShellTool`
    """
    from crew_chief.dispatcher import Dispatcher

    tools: list[Tool] = []
    enabled: list[str] = list(cfg.agent.tools)
    allowed_paths: list[str] = list(cfg.agent.allowed_paths)

    for name in enabled:
        if name == "shell":
            dispatcher = Dispatcher(
                allowed_commands=list(cfg.dispatch.allowed_commands),
                timeout_seconds=cfg.dispatch.timeout_seconds,
                max_output_bytes=cfg.dispatch.output_max_bytes,
            )
            tools.append(ShellTool(dispatcher))
        elif name == "read_file":
            tools.append(ReadFileTool(allowed_paths=allowed_paths or None))
        elif name == "write_file":
            tools.append(WriteFileTool(allowed_paths=allowed_paths or None))
        else:
            log.warning("Unknown tool name %r — skipped.", name)

    return tools
