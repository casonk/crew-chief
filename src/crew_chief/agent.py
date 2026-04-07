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
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful automation assistant running in a secure local system. "
    "You have access to tools that let you interact with the system. "
    "Use them step by step to accomplish the user's request. "
    "When you have completed the task, summarize what you did and any relevant results."
)


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
    """

    def __init__(
        self,
        provider: Any,
        tools: list[Any] | None = None,
        system_prompt: str = "",
        max_iterations: int = 10,
    ) -> None:
        self.provider = provider
        self.tools = tools or []
        self.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self.max_iterations = max_iterations

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
                return result.content

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
                results.append(
                    {"tool_use_id": tu.id, "name": tu.name, "content": output}
                )

            messages.append({"role": "tool_result", "results": results})

        log.warning(
            "Agent reached max_iterations=%d without a final response; returning last content.",
            self.max_iterations,
        )
        return last_content
