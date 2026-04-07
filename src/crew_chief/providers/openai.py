"""crew_chief.providers.openai — OpenAI Chat Completions API provider.

Uses only the standard library (urllib) so the zero-dependency constraint is
maintained.  Set OPENAI_API_KEY (or the env var named in ``openai_api_key_env``)
before use.

The wire format is very close to Ollama's: tool calls live in
``choices[0].message.tool_calls`` with a ``finish_reason`` of ``"tool_calls"``,
and tool results are submitted as ``{"role": "tool", "tool_call_id": ..., "content": ...}``
messages.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from crew_chief.providers.base import ChatResult, ProviderUnavailableError, ToolParam, ToolUse

_API_BASE = "https://api.openai.com"
_DEFAULT_MODEL = "gpt-4o"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TIMEOUT = 120


def _to_openai_messages(
    messages: list[dict[str, Any]],
    system: str | None,
) -> list[dict[str, Any]]:
    """Convert normalized messages to OpenAI's chat completions wire format."""
    native: list[dict[str, Any]] = []

    if system:
        native.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]

        if role == "system":
            # Already handled above; skip inline system messages.
            continue

        if role == "assistant" and msg.get("tool_uses"):
            tool_calls = [
                {
                    "id": tu["id"],
                    "type": "function",
                    "function": {
                        "name": tu["name"],
                        # OpenAI expects arguments as a JSON *string*
                        "arguments": json.dumps(tu["arguments"]),
                    },
                }
                for tu in msg["tool_uses"]
            ]
            native.append(
                {
                    "role": "assistant",
                    # content must be null (not empty string) when tool_calls present
                    "content": msg.get("content") or None,
                    "tool_calls": tool_calls,
                }
            )

        elif role == "tool_result":
            # One "tool" message per result (OpenAI matches by tool_call_id)
            for r in msg.get("results", []):
                native.append(
                    {
                        "role": "tool",
                        "tool_call_id": r["tool_use_id"],
                        "content": r["content"],
                    }
                )

        else:
            native.append({"role": role, "content": msg.get("content", "")})

    return native


def _to_openai_tools(tools: list[ToolParam]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _parse_response(body: dict[str, Any]) -> ChatResult:
    """Parse an OpenAI chat completions response into a :class:`ChatResult`."""
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message", {})
    content = message.get("content") or ""
    finish_reason = choice.get("finish_reason", "stop")

    raw_calls = message.get("tool_calls") or []
    tool_uses: list[ToolUse] = []
    for tc in raw_calls:
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_uses.append(
            ToolUse(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args if isinstance(args, dict) else {},
            )
        )

    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
    return ChatResult(content=content, tool_uses=tool_uses, stop_reason=stop_reason)


class OpenAIProvider:
    """Stdlib-only client for the OpenAI Chat Completions API.

    Parameters
    ----------
    api_key:
        OpenAI API key.  Falls back to the ``OPENAI_API_KEY`` environment
        variable when empty.
    model:
        Model ID (``"gpt-4o"``, ``"o3"``, …).  Defaults to ``"gpt-4o"``.
    timeout:
        HTTP request timeout in seconds.
    max_tokens:
        Upper bound on generated tokens per response.
    base_url:
        Override the API base URL (useful for testing, proxies, or
        OpenAI-compatible endpoints such as local llama.cpp servers).
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = _DEFAULT_MODEL,
        timeout: int = _DEFAULT_TIMEOUT,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        base_url: str = _API_BASE,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Single-turn generation — returns plain text."""
        return self.chat([{"role": "user", "content": prompt}]).content

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        """Multi-turn chat with optional tool calling."""
        if not self.api_key:
            raise ProviderUnavailableError(
                "OpenAI API key is not set.  Export OPENAI_API_KEY or pass api_key=."
            )

        native_messages = _to_openai_messages(messages, system)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": native_messages,
        }

        # max_tokens is called max_completion_tokens for o-series reasoning models;
        # the older name is still accepted by gpt-4* models.
        payload["max_tokens"] = self.max_tokens

        if tools:
            payload["tools"] = _to_openai_tools(tools)

        body = self._post("/v1/chat/completions", payload)
        return _parse_response(body)

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
                "Authorization": f"Bearer {self.api_key}",
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
            if exc.code in (401, 403):
                raise ProviderUnavailableError(
                    f"OpenAI API auth error {exc.code}: {msg}"
                ) from exc
            raise RuntimeError(f"OpenAI API error {exc.code}: {msg}") from exc
