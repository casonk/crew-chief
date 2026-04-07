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
the model to self-assess its response after the loop completes.  If the score
is below the threshold a :class:`LowConfidenceError` is raised — carrying the
low-confidence response so it is not lost.  :class:`AgentCascade` catches this
and re-runs the request with the next provider in the chain.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are Crew Chief, a helpful automation assistant running on a secure local system.

## Responding to messages

**Conversational messages** (greetings, thanks, general questions, small talk):
Respond naturally and helpfully in plain text. Do NOT invoke any tools.
Example greeting response: "Hello! I'm Crew Chief, your local system assistant. \
Here are some things I can help you with:
- Check disk space (df -h)
- Show memory usage (free -h)
- Check system uptime (uptime)
- View running processes (ps aux)
- Check a service status (systemctl status <name>)
- View recent logs (journalctl -n <N>)
- Network ping test (ping -c <N> <host>)
Just ask naturally, e.g. 'how much disk space is free?' or 'is nginx running?'"

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

_CONFIDENCE_CHECK_PROMPT = (
    "Rate your confidence that your previous response fully and correctly addressed "
    "the user's request. Consider: did you use all necessary tools? Is the task "
    "actually complete, or did you only describe what you would do? "
    'Reply with only this JSON on a single line: {"confidence": 0.X} '
    "where 0.0 = not confident at all, 1.0 = fully confident the task is done."
)


class LowConfidenceError(RuntimeError):
    """Raised when the agent's self-assessed confidence falls below the threshold.

    Attributes
    ----------
    content:
        The low-confidence response text — preserved so the cascade can use it
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
        model.  Pass an empty list (or omit) for text-only agents.
    system_prompt:
        System instruction sent on every call.  Defaults to a generic
        automation assistant prompt.
    max_iterations:
        Hard cap on tool-use cycles to prevent infinite loops.
    confidence_threshold:
        When > 0.0, the agent asks the model to score its response after the
        loop.  If the score is below this threshold a :class:`LowConfidenceError`
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

        # Build a name→tool lookup once
        self._tool_map: dict[str, Any] = {t.name: t for t in self.tools}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, prompt: str) -> str:
        """Run the agent loop for *prompt* and return the final text response.

        The agent sends *prompt* as a user turn, then iterates:

        * If the model returns tool calls, execute each and re-submit results.
        * If the model returns plain text (or max iterations is hit), return it.

        When :attr:`confidence_threshold` is set, the model is asked to
        self-assess after completing.  Scores below the threshold raise
        :class:`LowConfidenceError`.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_params = [t.to_param() for t in self.tools] if self.tools else None

        last_content = ""

        for iteration in range(self.max_iterations):
            log.debug("Agent iteration %d/%d.", iteration + 1, self.max_iterations)

            result = self.provider.chat(
                messages,
                tools=tool_params,
                system=self.system_prompt,
            )
            last_content = result.content

            if result.stop_reason != "tool_use" or not result.tool_uses:
                log.debug("Agent finished after %d iteration(s).", iteration + 1)
                break

            log.info(
                "Model requested %d tool call(s): %s",
                len(result.tool_uses),
                [tu.name for tu in result.tool_uses],
            )

            # Append the assistant's tool-use turn to history
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

            # Execute each tool and collect results
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

                log.info("Tool %r → %r", tu.name, output[:120])
                results.append({"tool_use_id": tu.id, "name": tu.name, "content": output})

            messages.append({"role": "tool_result", "results": results})
        else:
            log.warning(
                "Agent reached max_iterations=%d without a final response; returning last content.",
                self.max_iterations,
            )

        # Confidence check — only when a threshold is configured.
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_confidence(self, history: list[dict[str, Any]], response: str) -> float:
        """Ask the provider to rate its own response; return a 0.0–1.0 score.

        Sends the conversation history plus *response* as a final assistant
        turn, then asks for a JSON confidence score.  Falls back to ``1.0``
        (assume confident) if the check call fails or the response is
        unparseable — better to pass through than to always escalate on errors.
        """
        # Build a minimal view: original user message + assistant response
        # + the confidence-check question.  Avoid sending full tool traces to
        # keep the check call fast and cheap.
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
            log.debug("Confidence check: unparseable response %r — assuming 1.0.", raw[:120])
        except Exception as exc:
            log.warning("Confidence check call failed (%s) — assuming confident.", exc)
        return 1.0


class AgentCascade:
    """Run agents in priority order; escalate on low confidence or failure.

    Each entry in *agents* is tried in sequence.  The cascade advances when:

    * :class:`LowConfidenceError` is raised — the model completed but rated
      itself below the configured threshold.
    * Any other exception — the provider failed entirely.

    If every agent is exhausted the last low-confidence content (or an empty
    string) is returned with a warning, rather than raising — so the caller
    always gets *some* reply.

    Parameters
    ----------
    agents:
        Ordered list of :class:`Agent` instances, highest-priority first.
    """

    def __init__(self, agents: list[Agent]) -> None:
        if not agents:
            raise ValueError("AgentCascade requires at least one agent.")
        self.agents = agents

    def run(self, prompt: str) -> str:
        """Run the cascade for *prompt* and return the first confident response."""
        last_content = ""
        for agent in self.agents:
            provider_name = type(agent.provider).__name__
            try:
                return agent.run(prompt)
            except LowConfidenceError as exc:
                log.info(
                    "Cascade: %s confidence %.2f below threshold %.2f — escalating.",
                    provider_name,
                    exc.confidence,
                    agent.confidence_threshold,
                )
                last_content = exc.content
            except Exception as exc:
                log.warning(
                    "Cascade: %s failed (%s) — escalating.",
                    provider_name,
                    exc,
                )
        log.warning(
            "Cascade: all %d provider(s) exhausted — returning last response.",
            len(self.agents),
        )
        return last_content
