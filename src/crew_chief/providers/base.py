"""crew_chief.providers.base — shared types and Provider protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderUnavailableError(RuntimeError):
    """Raised by a provider when it cannot serve any requests.

    Examples: Ollama service not running, CLI not installed / not logged in,
    API key absent or invalid.  :class:`FallbackProvider` catches this to
    advance to the next tier.  Other exceptions (timeouts, model errors)
    propagate normally.
    """


@dataclass
class ToolParam:
    """Describes a tool the model can call."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class ToolUse:
    """A single tool-call request returned by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResult:
    """Normalized response from a :class:`Provider` chat call."""

    content: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    # "end_turn" | "tool_use" | "max_tokens"
    stop_reason: str = "end_turn"
    # Identifier of the model that produced this response (e.g. "llama3.2", "claude-opus-4-6").
    # Empty string when the provider does not report a model name.
    model: str = ""


__all__ = [
    "ChatResult",
    "Provider",
    "ProviderUnavailableError",
    "ToolParam",
    "ToolUse",
]


@runtime_checkable
class Provider(Protocol):
    """Structural protocol satisfied by all LLM provider backends.

    *messages* uses a normalized internal format:

    * Plain turn: ``{"role": "user"|"assistant"|"system", "content": str}``
    * Assistant with tool calls:
      ``{"role": "assistant", "content": str, "tool_uses": [{"id": str, "name": str, "arguments": dict}]}``
    * Tool results:
      ``{"role": "tool_result", "results": [{"tool_use_id": str, "name": str, "content": str}]}``

    Each provider translates to/from its native wire format internally.
    """

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,
        system: str | None = None,
    ) -> ChatResult: ...

    def generate(self, prompt: str) -> str: ...
