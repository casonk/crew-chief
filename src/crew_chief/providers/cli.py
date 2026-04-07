"""crew_chief.providers.cli — CLI-backed provider implementations.

Both providers shell out to locally-installed CLI tools that authenticate via
browser login (no API key required):

* :class:`ClaudeCliProvider` — ``claude -p --output-format json``
* :class:`CodexCliProvider`  — ``codex exec --json -o <tmpfile>``

Each CLI is itself an agentic loop: it accepts a plain-text prompt, runs
whatever tools it needs internally, and returns a final text response.  The
providers therefore always return a :class:`~crew_chief.providers.base.ChatResult`
with no ``tool_uses`` — the inner agent loop is opaque to ``crew_chief``.

Availability detection
----------------------
:class:`~crew_chief.providers.base.ProviderUnavailableError` is raised when:

* The CLI binary is not found on ``PATH`` (``FileNotFoundError``).
* The CLI reports an authentication / login error.
* The CLI reports a quota-exhaustion error (treated as temporarily unavailable
  so the fallback chain advances to the next tier).

All other subprocess errors are re-raised as plain ``RuntimeError``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from crew_chief.providers.base import ChatResult, ProviderUnavailableError, ToolParam

log = logging.getLogger(__name__)

# Substrings that indicate auth / quota failure rather than an application error.
_CLAUDE_UNAVAILABLE_PHRASES = (
    "not logged in",
    "please run /login",
    "authentication",
    "unauthorized",
)
_CODEX_UNAVAILABLE_PHRASES = (
    "usage limit",
    "not logged in",
    "log in",
    "unauthorized",
    "authentication",
    "rate limit",
)

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _messages_to_prompt(
    messages: list[dict[str, Any]],
    system: str | None = None,
) -> str:
    """Flatten a normalized messages list into a single prompt string.

    For single-turn use (the common case in the listener) the user content is
    returned verbatim.  For multi-turn history the messages are formatted with
    role prefixes so the CLI agent has full context.
    """
    # Filter to only meaningful turns
    effective = [m for m in messages if m["role"] not in ("system",)]

    parts: list[str] = []

    if system:
        parts.append(f"[System]\n{system}")

    for msg in effective:
        role = msg["role"]

        if role == "tool_result":
            for r in msg.get("results", []):
                parts.append(f"[Tool result — {r['name']}]\n{r['content']}")

        elif role == "assistant" and msg.get("tool_uses"):
            text = msg.get("content", "").strip()
            if text:
                parts.append(f"Assistant: {text}")
            for tu in msg["tool_uses"]:
                parts.append(f"[Called tool {tu['name']!r} with {json.dumps(tu['arguments'])}]")

        else:
            content = msg.get("content", "")
            # Single bare user message with no system — send raw
            if len(effective) == 1 and role == "user" and not system:
                return content
            label = {"user": "User", "assistant": "Assistant"}.get(role, role.capitalize())
            parts.append(f"{label}: {content}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# ClaudeCliProvider
# ---------------------------------------------------------------------------


class ClaudeCliProvider:
    """Provider that delegates to the ``claude`` CLI (Claude Code).

    The CLI authenticates via the user's existing browser session — no API key
    is required.  It uses Claude's own internal agentic loop; the
    ``tools`` / ``system`` parameters accepted by :meth:`chat` are forwarded
    via ``--append-system-prompt`` and ``--allowedTools`` respectively.

    Parameters
    ----------
    model:
        Model alias or full ID (``"sonnet"``, ``"opus"``, ``"claude-opus-4-6"``
        …).  Empty string uses the CLI's configured default.
    allowed_tools:
        Space- or comma-separated Claude tool names to permit (e.g.
        ``"Bash,Read,Edit"``).  Empty string disables all tools (pure text
        generation — fastest and safest for simple Q&A).
    timeout:
        ``subprocess.run`` timeout in seconds.  The CLI itself streams
        internally; this is a hard wall-clock limit.
    cli_path:
        Override the ``claude`` binary path.  Defaults to PATH lookup.
    """

    def __init__(
        self,
        model: str = "",
        allowed_tools: str = "",
        timeout: int = 120,
        cli_path: str = "claude",
    ) -> None:
        self.model = model
        self.allowed_tools = allowed_tools
        self.timeout = timeout
        self.cli_path = cli_path

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Single-turn generation."""
        return self.chat([{"role": "user", "content": prompt}]).content

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,  # noqa: ARG002 — CLI manages its own tools
        system: str | None = None,
    ) -> ChatResult:
        """Run the Claude CLI with *messages* and return the final response.

        *tools* is ignored — the CLI's internal tool set is controlled by
        ``allowed_tools`` (set at construction time or via
        ``cfg.llm.claude_cli_allowed_tools``).
        """
        prompt = _messages_to_prompt(messages, system=None)

        cmd = [self.cli_path, "-p", "--output-format", "json"]

        if self.model:
            cmd += ["--model", self.model]

        # System prompt: append so we don't clobber Claude Code's own system
        if system:
            cmd += ["--append-system-prompt", system]

        # Tool access — empty string means no tools (--tools "")
        if self.allowed_tools:
            cmd += ["--allowedTools", self.allowed_tools]
        else:
            cmd += ["--tools", ""]

        log.debug("ClaudeCliProvider cmd: %s", cmd)

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise ProviderUnavailableError(
                f"claude CLI not found at {self.cli_path!r}.  "
                "Install Claude Code: https://claude.ai/code"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s") from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        log.debug(
            "ClaudeCliProvider rc=%d stdout=%r stderr=%r",
            result.returncode,
            stdout[:200],
            stderr[:200],
        )

        # Parse the JSON result object
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Non-JSON output on failure (e.g. auth prompt printed to stdout)
            raw = (stdout or stderr).lower()
            if any(phrase in raw for phrase in _CLAUDE_UNAVAILABLE_PHRASES):
                raise ProviderUnavailableError(
                    f"claude CLI not authenticated: {stdout or stderr}"
                ) from None
            raise RuntimeError(f"claude CLI returned non-JSON output: {stdout or stderr}") from None

        if data.get("is_error"):
            result_text = data.get("result", "")
            if any(phrase in result_text.lower() for phrase in _CLAUDE_UNAVAILABLE_PHRASES):
                raise ProviderUnavailableError(f"claude CLI unavailable: {result_text}")
            raise RuntimeError(f"claude CLI error: {result_text}")

        return ChatResult(
            content=data.get("result", ""),
            tool_uses=[],
            stop_reason=data.get("stop_reason", "end_turn"),
        )

    # ------------------------------------------------------------------
    # Availability probe
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the CLI is installed and the user is logged in."""
        try:
            r = subprocess.run(
                [self.cli_path, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(r.stdout.strip())
            return bool(data.get("loggedIn"))
        except Exception:
            return False


# ---------------------------------------------------------------------------
# CodexCliProvider
# ---------------------------------------------------------------------------

# Expected JSONL event types that indicate the run completed successfully.
_CODEX_SUCCESS_EVENTS = {"turn.completed", "thread.completed"}
# Event types that carry the final answer text.
_CODEX_RESULT_EVENTS = {"message", "message.completed", "agent.message"}


class CodexCliProvider:
    """Provider that delegates to the ``codex`` CLI (OpenAI Codex).

    The CLI authenticates via the user's existing ChatGPT / OpenAI session —
    no API key is required.  It uses Codex's own internal agentic loop.

    Parameters
    ----------
    model:
        Model name (``"o3"``, ``"o4-mini"`` …).  Empty string uses the
        configured default.
    sandbox:
        Codex sandbox policy: ``"read-only"``, ``"workspace-write"``, or
        ``"danger-full-access"``.  ``"workspace-write"`` allows the agent to
        read/write the workspace but not reach outside it.
    timeout:
        Hard wall-clock limit in seconds.
    cli_path:
        Override the ``codex`` binary path.
    """

    def __init__(
        self,
        model: str = "",
        sandbox: str = "workspace-write",
        timeout: int = 300,
        cli_path: str = "codex",
    ) -> None:
        self.model = model
        self.sandbox = sandbox
        self.timeout = timeout
        self.cli_path = cli_path

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        return self.chat([{"role": "user", "content": prompt}]).content

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,  # noqa: ARG002
        system: str | None = None,
    ) -> ChatResult:
        """Run the Codex CLI and return the final response text."""
        prompt = _messages_to_prompt(messages, system=system)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="cc_codex_"
        ) as tmp:
            out_path = tmp.name

        try:
            content = self._run(prompt, out_path)
        finally:
            Path(out_path).unlink(missing_ok=True)

        return ChatResult(content=content, tool_uses=[], stop_reason="end_turn")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, prompt: str, out_path: str) -> str:
        cmd = [
            self.cli_path,
            "exec",
            "--json",
            "--ephemeral",
            "-o",
            out_path,
            "--sandbox",
            self.sandbox,
        ]

        if self.model:
            cmd += ["--model", self.model]

        log.debug("CodexCliProvider cmd: %s", cmd)

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise ProviderUnavailableError(
                f"codex CLI not found at {self.cli_path!r}.  "
                "Install Codex: https://github.com/openai/codex"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"codex CLI timed out after {self.timeout}s") from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        log.debug(
            "CodexCliProvider rc=%d stdout=%r stderr=%r",
            result.returncode,
            stdout[:300],
            stderr[:200],
        )

        # Parse JSONL to detect errors before reading the output file
        self._check_jsonl_errors(stdout)

        # Read the -o output file (last assistant message)
        last_msg = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
        if last_msg:
            return last_msg

        # Fallback: extract text from JSONL events if file was empty
        return self._extract_text_from_jsonl(stdout)

    def _check_jsonl_errors(self, jsonl: str) -> None:
        """Scan JSONL output for error events; raise appropriate exceptions."""
        for line in jsonl.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") in ("error", "turn.failed"):
                msg = (
                    event.get("message") or (event.get("error") or {}).get("message") or str(event)
                )
                if any(phrase in msg.lower() for phrase in _CODEX_UNAVAILABLE_PHRASES):
                    raise ProviderUnavailableError(f"codex CLI unavailable: {msg}")
                raise RuntimeError(f"codex CLI error: {msg}")

    def _extract_text_from_jsonl(self, jsonl: str) -> str:
        """Best-effort extraction of text content from JSONL when -o file is empty."""
        parts: list[str] = []
        for line in jsonl.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Collect content from any message-like events
            etype = event.get("type", "")
            if etype in _CODEX_RESULT_EVENTS:
                text = event.get("content") or event.get("text") or ""
                if text:
                    parts.append(str(text))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Availability probe
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if the CLI is installed and the user is logged in."""
        try:
            r = subprocess.run(
                [self.cli_path, "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0 and "logged in" in r.stdout.lower()
        except Exception:
            return False
