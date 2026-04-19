"""crew_chief.client — zero-dependency HTTP client for the local Ollama service."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from crew_chief.prompt_utils import (
    looks_like_embedded_transcript,
    wrap_literal_user_message,
)

DEFAULT_BASE_URL: str = os.environ.get("CREW_CHIEF_URL", "http://localhost:11434")
DEFAULT_MODEL: str = os.environ.get("CREW_CHIEF_MODEL", "llama3.2")
DEFAULT_TIMEOUT: int = int(os.environ.get("CREW_CHIEF_TIMEOUT", "60"))


class CrewChiefClient:
    """Minimal HTTP client for the crew-chief Ollama service.

    Supports generate (single prompt → text) and chat (messages list → text)
    endpoints.  Uses only the standard library so any repo can install it
    without pulling in additional HTTP dependencies.

    Environment variables (all optional):
        CREW_CHIEF_URL     Base URL of the Ollama service.  Default: http://localhost:11434
        CREW_CHIEF_MODEL   Model name to use.               Default: llama3.2
        CREW_CHIEF_TIMEOUT Request timeout in seconds.      Default: 60
    """

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
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        """Send a single prompt and return the generated response text."""
        if looks_like_embedded_transcript(prompt):
            prompt = wrap_literal_user_message(prompt)
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        body = self._post("/api/generate", payload)
        return body.get("response", "")

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat-style messages list and return the assistant reply text.

        Each message dict must have ``role`` (``"user"``, ``"assistant"``, or
        ``"system"``) and ``content`` keys.
        """
        native_messages: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user" and looks_like_embedded_transcript(content):
                content = wrap_literal_user_message(content)
            native_messages.append({"role": role, "content": content})

        payload = {"model": self.model, "messages": native_messages, "stream": False}
        body = self._post("/api/chat", payload)
        return body.get("message", {}).get("content", "")

    def health(self) -> bool:
        """Return True when the service responds to the root endpoint."""
        try:
            req = urllib.request.Request(f"{self.base_url}/", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return the names of all models available on the server."""
        req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read())
        return [m["name"] for m in body.get("models", [])]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())
