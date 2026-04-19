"""crew_chief.agent — multi-step agentic loop.

The :class:`Agent` drives a *plan → act → observe* cycle:

1. Send the user's prompt (and any prior conversation turns) to a
   :class:`~crew_chief.providers.base.Provider`.
2. If the model requests tool calls, execute each tool via the registered
   :class:`~crew_chief.tools.Tool` instances and feed the results back.
3. Repeat until the model produces a final text response (``stop_reason !=
   "tool_use"``) or :attr:`max_iterations` is reached.

The loop is provider-agnostic: both :class:`~crew_chief.providers.OllamaProvider`
and :class:`~crew_chief.providers.AnthropicProvider` satisfy the
:class:`~crew_chief.providers.base.Provider` protocol.

Confidence-based escalation
---------------------------
When :attr:`Agent.confidence_threshold` is set above ``0.0``, the agent asks
the model to self-assess its response after the loop completes. If the score
is below the threshold a :class:`LowConfidenceError` is raised, carrying the
low-confidence response so it is not lost. :class:`AgentCascade` catches this
and re-runs the request with the next provider in the chain.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from crew_chief.model_output_utils import extract_echoed_shell_command
from crew_chief.providers.base import ToolUse

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are Crew Chief, a helpful automation assistant running on a secure local system.

## Responding to messages

**Conversational messages** (greetings, thanks, general questions, small talk):
Respond naturally and helpfully in plain text. Do NOT invoke any tools.
Example greeting response: "Hello! I'm Crew Chief, your local system assistant. \
I can help with things like disk space, memory usage, uptime, running processes, \
service status, recent logs, and ping checks. Just ask naturally, e.g. 'how much \
disk space is free?' or 'is nginx running?'"
Do not turn greetings into a numbered menu, a task picker, or a "choose one of these \
options" response. Do not ask the user to type a number.

**Explicit system/command requests** (user clearly asks for system information or to run a command):
Use the shell tool to fulfill the request. Examples of explicit requests:
- "how much disk space do I have?"
- "check if nginx is running"
- "what's the uptime?"
- "show memory usage"

**Code change requests** (user asks you to modify, add, fix, or refactor code in the repo):
Use read_file to read relevant source files first, then write_file to apply changes, then
shell to run tests (e.g. `python3 -m pytest`) and git commands to commit. Work step by
step — read before writing, test after writing, commit when the user asks or confirms.
Always tell the user which files you changed and why.

**Ambiguous requests** (unclear whether a shell command or code change is appropriate):
Do NOT act. Instead, describe what you would do and ask for confirmation.
Example: "I could run `uptime` to show system uptime. Should I go ahead?"

## Key rules
1. Never use the shell tool in response to a greeting, thanks, or casual message.
2. Never guess at what command the user wants — ask when uncertain.
3. For code changes: read first, write second, test third.
4. Keep responses concise and friendly.\
"""

_DEFAULT_GREETING_RESPONSE = """\
Hello! I'm Crew Chief, your local system assistant. I can help with things like disk \
space, memory usage, system uptime, running processes, service status, recent logs, and \
ping checks. Ask naturally, for example: "how much disk space is free?" or "is nginx \
running?"\
"""

_PSEUDO_TOOL_RETRY_PROMPT = (
    "Your previous reply was plain-text tool/function-call JSON instead of a user-facing "
    "answer. Reply again for the user in plain text. Do not emit plain-text tool/"
    "function-call JSON. If you truly need a tool, use the provider's actual tool-use "
    "mechanism rather than JSON in the message content."
)

_SYSTEM_REQUEST_FALLBACK = (
    "I couldn't verify the current system state because no command was executed. "
    "Please ask again or send the exact command you want run."
)

_GENERIC_PSEUDO_TOOL_FALLBACK = (
    "I couldn't complete the request because no tool was actually executed. Please try again."
)

_CONFIDENCE_CHECK_PROMPT = (
    "Rate your confidence that your previous response fully and correctly addressed "
    "the user's request. Consider: did you use all necessary tools? Is the task "
    "actually complete, or did you only describe what you would do? "
    'Reply with only this JSON on a single line: {"confidence": 0.X} '
    "where 0.0 = not confident at all, 1.0 = fully confident the task is done."
)

_PSEUDO_TOOL_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>\{.*\})\s*```\s*$",
    re.DOTALL,
)
_TRAILING_PSEUDO_TOOL_JSON_FENCE_RE = re.compile(
    r"^(?P<prefix>.*?)\s*```(?:json)?\s*(?P<body>\{.*\})\s*```\s*$",
    re.DOTALL,
)
_SIMPLE_GREETING_RE = re.compile(
    r"^\s*(?:(?:hi|hello|hey)(?:\s+there)?|good\s+(?:morning|afternoon|evening))\s*[!.?]*\s*$",
    re.IGNORECASE,
)
_CONVERSATIONAL_RE = re.compile(
    r"^\s*(?:(?:hi|hello|hey)\b|good\s+(?:morning|afternoon|evening)\b)",
    re.IGNORECASE,
)
_LIVE_REQUEST_PATTERNS = (
    "uptime",
    "disk space",
    "memory usage",
    "show memory",
    "free memory",
    "running processes",
    "process list",
    "service status",
    "systemctl",
    "journalctl",
    "recent logs",
    "ping ",
    "hostname",
    "df -h",
    "free -h",
    "ps aux",
    "check if ",
    "show ",
    "run ",
    "execute ",
    "status of ",
    "what's the uptime",
    "what is the uptime",
    "how much disk space",
    "how full is the disk",
    "is nginx running",
)
_STRUCTURED_OUTPUT_TERMS = (
    "json",
    "schema",
    "payload",
    "shape",
    "format",
    "example",
    "sample",
    "template",
    "object",
    "parameters",
    "look like",
)
_TOOL_EXAMPLE_CONTEXT_TERMS = (
    "tool",
    "function",
    "shell",
    "command",
    "request",
    "call",
)


class LowConfidenceError(RuntimeError):
    """Raised when the agent's self-assessed confidence falls below the threshold.

    Attributes
    ----------
    content:
        The low-confidence response text, preserved so the cascade can use it
        as a last resort if all providers are low-confidence.
    confidence:
        The numeric score (0.0–1.0) returned by the model's self-assessment.
    """

    def __init__(self, message: str, *, content: str, confidence: float) -> None:
        super().__init__(message)
        self.content = content
        self.confidence = confidence


class Agent:
    """Multi-step agent that drives a provider through a tool-use loop.

    Parameters
    ----------
    provider:
        Any object satisfying :class:`~crew_chief.providers.base.Provider`.
    tools:
        List of :class:`~crew_chief.tools.Tool` instances available to the
        model. Pass an empty list (or omit) for text-only agents.
    system_prompt:
        System instruction sent on every call. Defaults to a generic
        automation assistant prompt.
    max_iterations:
        Hard cap on tool-use cycles to prevent infinite loops.
    confidence_threshold:
        When > 0.0, the agent asks the model to score its response after the
        loop. If the score is below this threshold a :class:`LowConfidenceError`
        is raised so :class:`AgentCascade` can escalate to the next provider.
        ``0.0`` disables confidence checking entirely (default).
    """

    def __init__(
        self,
        provider: Any,
        tools: list[Any] | None = None,
        system_prompt: str = "",
        max_iterations: int = 10,
        confidence_threshold: float = 0.0,
    ) -> None:
        self.provider = provider
        self.tools = tools or []
        self.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self.max_iterations = max_iterations
        self.confidence_threshold = confidence_threshold

        # Build a name->tool lookup once.
        self._tool_map: dict[str, Any] = {t.name: t for t in self.tools}

        # Set after each run() call; holds the model ID of the last provider response.
        self.last_used_model: str = ""

    def run(self, prompt: str) -> str:
        """Run the agent loop for *prompt* and return the final text response."""
        if _is_simple_greeting(prompt):
            log.debug("Short-circuiting simple greeting without calling provider.")
            self.last_used_model = ""
            return _DEFAULT_GREETING_RESPONSE

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_params = [t.to_param() for t in self.tools] if self.tools else None
        last_content = ""
        pseudo_tool_retry_used = False

        for iteration in range(self.max_iterations):
            log.debug("Agent iteration %d/%d.", iteration + 1, self.max_iterations)

            result = self.provider.chat(
                messages,
                tools=tool_params,
                system=self.system_prompt,
            )
            last_content = result.content
            self.last_used_model = result.model

            pseudo_tool = None
            if result.stop_reason != "tool_use" and not result.tool_uses:
                pseudo_tool = _find_pseudo_tool_call(prompt, result.content)
                repaired_tool_use = _repair_pseudo_tool_call(
                    pseudo_tool,
                    self._tool_map,
                    repair_id=f"repaired_shell_{iteration}",
                )
                if repaired_tool_use is not None:
                    result.content = ""
                    result.tool_uses = [repaired_tool_use]
                    result.stop_reason = "tool_use"
                    pseudo_tool = None

            if pseudo_tool is not None:
                log.info("Model emitted pseudo tool-call JSON for %r.", pseudo_tool["name"])
                if not pseudo_tool_retry_used:
                    messages.append({"role": "assistant", "content": result.content})
                    messages.append({"role": "user", "content": _PSEUDO_TOOL_RETRY_PROMPT})
                    pseudo_tool_retry_used = True
                    continue
                return _fallback_for_prompt(prompt)

            if result.tool_uses:
                result.tool_uses = _repair_tool_uses(result.tool_uses, self._tool_map)

            if result.stop_reason != "tool_use" or not result.tool_uses:
                log.debug("Agent finished after %d iteration(s).", iteration + 1)
                break

            log.info(
                "Model requested %d tool call(s): %s",
                len(result.tool_uses),
                [tu.name for tu in result.tool_uses],
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_uses": [
                        {"id": tu.id, "name": tu.name, "arguments": tu.arguments}
                        for tu in result.tool_uses
                    ],
                }
            )

            results: list[dict[str, Any]] = []
            for tu in result.tool_uses:
                tool = self._tool_map.get(tu.name)
                if tool is not None:
                    try:
                        output = tool.execute(tu.arguments)
                    except Exception as exc:
                        output = f"Tool execution error: {exc}"
                        log.exception("Tool %r raised an exception.", tu.name)
                else:
                    output = f"Unknown tool: {tu.name!r}"
                    log.warning("Model requested unknown tool %r.", tu.name)

                output_text = str(output)
                log.info("Tool %r -> %r", tu.name, output_text[:120])
                results.append({"tool_use_id": tu.id, "name": tu.name, "content": output_text})

            messages.append({"role": "tool_result", "results": results})
        else:
            log.warning(
                "Agent reached max_iterations=%d without a final response; returning last content.",
                self.max_iterations,
            )

        if self.confidence_threshold > 0.0 and last_content:
            confidence = self._check_confidence(messages, last_content)
            log.info(
                "Agent confidence check: %.2f (threshold %.2f, provider %s).",
                confidence,
                self.confidence_threshold,
                type(self.provider).__name__,
            )
            if confidence < self.confidence_threshold:
                raise LowConfidenceError(
                    f"confidence {confidence:.2f} < threshold {self.confidence_threshold:.2f} "
                    f"from {type(self.provider).__name__}",
                    content=last_content,
                    confidence=confidence,
                )

        return last_content

    def _check_confidence(self, history: list[dict[str, Any]], response: str) -> float:
        """Ask the provider to rate its own response; return a 0.0-1.0 score."""
        user_prompt = next((m["content"] for m in history if m.get("role") == "user"), "")
        check_messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": response},
            {"role": "user", "content": _CONFIDENCE_CHECK_PROMPT},
        ]
        try:
            result = self.provider.chat(check_messages, tools=None, system=None)
            raw = result.content.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                score = float(parsed.get("confidence", 1.0))
                return max(0.0, min(1.0, score))
            log.debug("Confidence check: unparseable response %r; assuming 1.0.", raw[:120])
        except Exception as exc:
            log.warning("Confidence check call failed (%s); assuming confident.", exc)
        return 1.0


class AgentCascade:
    """Run agents in priority order; escalate on low confidence or failure."""

    def __init__(self, agents: list[Agent]) -> None:
        if not agents:
            raise ValueError("AgentCascade requires at least one agent.")
        self.agents = agents
        self.last_used_model: str = ""

    def run(self, prompt: str) -> str:
        """Run the cascade for *prompt* and return the first confident response."""
        last_content = ""
        for agent in self.agents:
            provider_name = type(agent.provider).__name__
            try:
                content = agent.run(prompt)
                self.last_used_model = agent.last_used_model
                return content
            except LowConfidenceError as exc:
                log.info(
                    "Cascade: %s confidence %.2f below threshold %.2f; escalating.",
                    provider_name,
                    exc.confidence,
                    agent.confidence_threshold,
                )
                last_content = exc.content
                self.last_used_model = agent.last_used_model
            except Exception as exc:
                log.warning("Cascade: %s failed (%s); escalating.", provider_name, exc)
        log.warning(
            "Cascade: all %d provider(s) exhausted; returning last response.",
            len(self.agents),
        )
        return last_content


def _is_simple_greeting(prompt: str) -> bool:
    return bool(_SIMPLE_GREETING_RE.match(prompt))


def _looks_like_live_request(prompt: str) -> bool:
    normalized = _normalize_prompt(prompt)
    if normalized.startswith("!"):
        return True
    return any(pattern in normalized for pattern in _LIVE_REQUEST_PATTERNS)


def _is_conversational_prompt(prompt: str) -> bool:
    if _looks_like_live_request(prompt):
        return False
    return bool(_CONVERSATIONAL_RE.match(prompt))


def _fallback_for_prompt(prompt: str) -> str:
    if _looks_like_live_request(prompt):
        return _SYSTEM_REQUEST_FALLBACK
    if _is_conversational_prompt(prompt):
        return _DEFAULT_GREETING_RESPONSE
    return _GENERIC_PSEUDO_TOOL_FALLBACK


def _find_pseudo_tool_call(prompt: str, content: str) -> dict[str, Any] | None:
    if _prompt_requests_tool_example(prompt):
        return None

    parsed = _parse_pseudo_tool_call(content)
    if parsed is not None:
        return parsed

    prefix, candidate = _split_trailing_json_object(content)
    if candidate is None:
        return None
    if _looks_like_structured_example_prefix(prefix):
        return None
    return _parse_pseudo_tool_payload(candidate)


def _repair_pseudo_tool_call(
    pseudo_tool: dict[str, Any] | None,
    tool_map: dict[str, Any],
    repair_id: str,
) -> ToolUse | None:
    if pseudo_tool is None or "shell" not in tool_map:
        return None

    command = extract_echoed_shell_command(pseudo_tool["name"], pseudo_tool["arguments"])
    if command is None:
        return None

    log.info("Repairing schema-echo pseudo tool payload into shell command %r.", command)
    return ToolUse(id=repair_id, name="shell", arguments={"command": command})


def _repair_tool_uses(tool_uses: list[ToolUse], tool_map: dict[str, Any]) -> list[ToolUse]:
    repaired: list[ToolUse] = []
    for tool_use in tool_uses:
        if tool_use.name in tool_map or "shell" not in tool_map:
            repaired.append(tool_use)
            continue

        command = extract_echoed_shell_command(tool_use.name, tool_use.arguments)
        if command is None:
            repaired.append(tool_use)
            continue

        log.info(
            "Repairing malformed tool call %r into shell command %r.",
            tool_use.name,
            command,
        )
        repaired.append(ToolUse(id=tool_use.id, name="shell", arguments={"command": command}))
    return repaired


def _parse_pseudo_tool_call(content: str) -> dict[str, Any] | None:
    raw = content.strip()
    if not raw:
        return None

    candidate = raw
    fence_match = _PSEUDO_TOOL_JSON_FENCE_RE.fullmatch(raw)
    if fence_match is not None:
        candidate = fence_match.group("body").strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    return _parse_pseudo_tool_payload(parsed)


def _parse_pseudo_tool_payload(parsed: Any) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None

    name = parsed.get("name")
    arguments = parsed.get("parameters", parsed.get("arguments"))
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None
    return {"name": name, "arguments": arguments}


def _normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.strip().lower().split())


def _prompt_requests_tool_example(prompt: str) -> bool:
    normalized = _normalize_prompt(prompt)
    return any(term in normalized for term in _STRUCTURED_OUTPUT_TERMS) and any(
        term in normalized for term in _TOOL_EXAMPLE_CONTEXT_TERMS
    )


def _looks_like_structured_example_prefix(prefix: str) -> bool:
    normalized = _normalize_prompt(prefix)
    if not normalized:
        return False
    return any(term in normalized for term in _STRUCTURED_OUTPUT_TERMS)


def _split_trailing_json_object(content: str) -> tuple[str, Any | None]:
    raw = content.strip()
    if not raw:
        return "", None

    fence_match = _TRAILING_PSEUDO_TOOL_JSON_FENCE_RE.match(raw)
    if fence_match is not None:
        prefix = fence_match.group("prefix").strip()
        body = fence_match.group("body").strip()
        try:
            return prefix, json.loads(body)
        except json.JSONDecodeError:
            return "", None

    decoder = json.JSONDecoder()
    parsed_tail: tuple[str, Any] | None = None
    for match in re.finditer(r"\{", raw):
        start = match.start()
        try:
            parsed, end = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            continue
        if raw[start + end :].strip():
            continue
        parsed_tail = (raw[:start].strip(), parsed)

    if parsed_tail is None:
        return "", None
    return parsed_tail
