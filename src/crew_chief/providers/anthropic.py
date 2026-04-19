"""crew_chief.providers.anthropic — Anthropic Messages API provider.

Uses only the standard library (urllib) so the zero-dependency constraint is
maintained.  Set ANTHROPIC_API_KEY (or the env var named in ``api_key_env``)
before use.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from crew_chief.providers.base import ChatResult, ProviderUnavailableError, ToolParam, ToolUse
from crew_chief.providers.prompt_utils import (
    looks_like_embedded_transcript,
    wrap_literal_user_message,
)

_API_BASE = "https://api.anthropic.com"
_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-opus-4-6"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TIMEOUT = 120


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert normalized messages to Anthropic's wire format.

    System-role messages are excluded here because Anthropic accepts ``system``
    as a top-level parameter, not inside the messages list.
    """
    native: list[dict[str, Any]] = []

    for msg in messages:
        role = msg["role"]

        if role == "system":
            # Passed separately as the top-level ``system`` parameter.
            continue

        if role == "assistant" and msg.get("tool_uses"):
            content: list[dict[str, Any]] = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tu in msg["tool_uses"]:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["arguments"],
                    }
                )
            native.append({"role": "assistant", "content": content})

        elif role == "tool_result":
            # Tool results are re-submitted as a user turn
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": r["tool_use_id"],
                    "content": r["content"],
                }
                for r in msg.get("results", [])
            ]
            native.append({"role": "user", "content": content})

        else:
            # Plain user or assistant text turn
            content = msg.get("content", "")
            if role == "user" and looks_like_embedded_transcript(content):
                content = wrap_literal_user_message(content)
            native.append({"role": role, "content": content})

    return native


def _to_anthropic_tools(tools: list[ToolParam]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _parse_response(body: dict[str, Any]) -> ChatResult:
    """Parse an Anthropic Messages API response into a :class:`ChatResult`."""
    stop_reason = body.get("stop_reason", "end_turn")
    content_blocks = body.get("content", [])

    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_uses.append(
                ToolUse(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}),
                )
            )

    return ChatResult(
        content=" ".join(text_parts).strip(),
        tool_uses=tool_uses,
        stop_reason=stop_reason,
    )


class AnthropicProvider:
    """Stdlib-only client for the Anthropic Messages API.

    Parameters
    ----------
    api_key:
        Anthropic API key.  Falls back to the ``ANTHROPIC_API_KEY`` environment
        variable when empty.
    model:
        Claude model ID.  Defaults to ``claude-opus-4-6``.
    timeout:
        HTTP request timeout in seconds.
    max_tokens:
        Upper bound on generated tokens per response.
    base_url:
        Override the API base URL (useful for testing or proxies).
    """

    reports_tool_use = True

    def __init__(
        self,
        api_key: str = "",
        model: str = _DEFAULT_MODEL,
        timeout: int = _DEFAULT_TIMEOUT,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        base_url: str = _API_BASE,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Single-turn generation — returns plain text."""
        result = self.chat([{"role": "user", "content": prompt}])
        return result.content

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        """Multi-turn chat with optional tool calling."""
        if not self.api_key:
            raise ProviderUnavailableError(
                "Anthropic API key is not set.  Export ANTHROPIC_API_KEY or pass api_key=."
            )

        native_messages = _to_anthropic_messages(messages)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": native_messages,
        }

        if system:
            payload["system"] = system

        if tools:
            payload["tools"] = _to_anthropic_tools(tools)

        body = self._post("/v1/messages", payload)
        result = _parse_response(body)
        result.model = self.model
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": _API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body_text).get("error", {})
                msg = err.get("message", body_text)
            except Exception:
                msg = body_text
            # 401 / 403 → key invalid or lacking permissions → treat as unavailable
            if exc.code in (401, 403):
                raise ProviderUnavailableError(
                    f"Anthropic API auth error {exc.code}: {msg}"
                ) from exc
            raise RuntimeError(f"Anthropic API error {exc.code}: {msg}") from exc
