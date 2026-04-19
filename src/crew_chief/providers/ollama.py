"""crew_chief.providers.ollama — Ollama-backed provider (local LLM)."""

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

DEFAULT_BASE_URL: str = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434")
DEFAULT_MODEL: str = os.environ.get("CREW_CHIEF_MODEL", "llama3.2")
DEFAULT_TIMEOUT: int = int(os.environ.get("CREW_CHIEF_TIMEOUT", "60"))


def _to_ollama_messages(
    messages: list[dict[str, Any]],
    system: str | None,
) -> list[dict[str, Any]]:
    """Convert normalized messages to Ollama's wire format."""
    native: list[dict[str, Any]] = []

    if system:
        native.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]

        if role == "assistant" and msg.get("tool_uses"):
            # Assistant turn with tool calls
            native.append(
                {
                    "role": "assistant",
                    "content": msg.get("content", ""),
                    "tool_calls": [
                        {
                            "function": {
                                "name": tu["name"],
                                "arguments": tu["arguments"],
                            }
                        }
                        for tu in msg["tool_uses"]
                    ],
                }
            )
        elif role == "tool_result":
            # Expand one normalized tool_result into N individual tool messages
            for result in msg.get("results", []):
                native.append({"role": "tool", "content": result["content"]})
        else:
            content = msg.get("content", "")
            if role == "user" and looks_like_embedded_transcript(content):
                content = wrap_literal_user_message(content)
            native.append({"role": role, "content": content})

    return native


def _parse_chat_response(body: dict[str, Any]) -> ChatResult:
    """Parse an Ollama /api/chat response into a normalized :class:`ChatResult`."""
    msg = body.get("message", {})
    content = msg.get("content") or ""
    raw_calls = msg.get("tool_calls") or []

    tool_uses: list[ToolUse] = []
    for i, tc in enumerate(raw_calls):
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_uses.append(
            ToolUse(
                id=f"ollama_{i}",  # Ollama provides no stable ID; synthesize one
                name=fn.get("name", ""),
                arguments=args if isinstance(args, dict) else {},
            )
        )

    stop_reason = "tool_use" if tool_uses else "end_turn"
    return ChatResult(content=content, tool_uses=tool_uses, stop_reason=stop_reason)


class OllamaProvider:
    """Stdlib-only HTTP client for the Ollama REST API.

    Supports :meth:`generate` (single prompt) and :meth:`chat` (multi-turn,
    with optional tool calling) against the local Ollama service.
    """

    reports_tool_use = True

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Provider protocol
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Single-turn generation — returns plain text."""
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        body = self._post("/api/generate", payload)
        return body.get("response") or ""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        """Multi-turn chat with optional tool calling."""
        native_messages = _to_ollama_messages(messages, system)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": native_messages,
            "stream": False,
        }

        if tools:
            payload["tools"] = [
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

        body = self._post("/api/chat", payload)
        result = _parse_chat_response(body)
        result.model = self.model
        return result

    # ------------------------------------------------------------------
    # Convenience helpers (matches CrewChiefClient API surface)
    # ------------------------------------------------------------------

    def health(self) -> bool:
        """Return True if the service is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return names of all models available on the server."""
        req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read())
        return [m["name"] for m in body.get("models", [])]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            # Connection refused / no route → service is not running
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            if any(
                kw in reason.lower()
                for kw in ("connection refused", "no route", "name or service not known")
            ):
                raise ProviderUnavailableError(
                    f"Ollama service not reachable at {self.base_url}: {reason}"
                ) from exc
            raise
