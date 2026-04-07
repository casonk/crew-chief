"""crew_chief.providers — pluggable LLM provider backends."""

from __future__ import annotations

import logging
from typing import Any

from crew_chief.providers.anthropic import AnthropicProvider
from crew_chief.providers.base import ChatResult, Provider, ProviderUnavailableError, ToolParam, ToolUse
from crew_chief.providers.cli import ClaudeCliProvider, CodexCliProvider
from crew_chief.providers.ollama import OllamaProvider
from crew_chief.providers.openai import _DEFAULT_MODEL as _DEFAULT_OPENAI_MODEL
from crew_chief.providers.openai import OpenAIProvider

log = logging.getLogger(__name__)

__all__ = [
    "AnthropicProvider",
    "ChatResult",
    "ClaudeCliProvider",
    "CodexCliProvider",
    "FallbackProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "Provider",
    "ProviderUnavailableError",
    "ToolParam",
    "ToolUse",
    "get_provider",
]


# ---------------------------------------------------------------------------
# FallbackProvider
# ---------------------------------------------------------------------------


class FallbackProvider:
    """Try each provider in order; advance to the next on any exception.

    Providers are tried in the order given to the constructor.  On
    :class:`~crew_chief.providers.base.ProviderUnavailableError` the next
    provider is tried silently (DEBUG log).  On any other exception a WARNING
    is logged before advancing — these are genuine errors from an available
    provider, so the warning is important for debugging.

    If every provider fails, the last exception is re-raised.
    """

    def __init__(self, providers: list[Any]) -> None:
        if not providers:
            raise ValueError("FallbackProvider requires at least one provider.")
        self.providers = providers

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolParam] | None = None,
        system: str | None = None,
    ) -> ChatResult:
        last_exc: Exception | None = None
        for provider in self.providers:
            name = type(provider).__name__
            try:
                result = provider.chat(messages, tools=tools, system=system)
                log.debug("FallbackProvider: %s succeeded.", name)
                return result
            except ProviderUnavailableError as exc:
                log.debug("FallbackProvider: %s unavailable (%s); trying next.", name, exc)
                last_exc = exc
            except Exception as exc:
                log.warning("FallbackProvider: %s failed (%s); trying next.", name, exc)
                last_exc = exc
        raise last_exc or RuntimeError("All providers in the fallback chain failed.")

    def generate(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for provider in self.providers:
            name = type(provider).__name__
            try:
                result = provider.generate(prompt)
                log.debug("FallbackProvider: %s succeeded.", name)
                return result
            except ProviderUnavailableError as exc:
                log.debug("FallbackProvider: %s unavailable (%s); trying next.", name, exc)
                last_exc = exc
            except Exception as exc:
                log.warning("FallbackProvider: %s failed (%s); trying next.", name, exc)
                last_exc = exc
        raise last_exc or RuntimeError("All providers in the fallback chain failed.")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _build_single_provider(name: str, cfg: Any) -> Any:
    """Build one provider from its name and a LlmConfig-like *cfg* object."""
    import os

    if name == "ollama":
        return OllamaProvider(
            base_url=cfg.base_url,
            model=cfg.model,
            timeout=cfg.timeout_seconds,
        )

    if name == "claude-cli":
        return ClaudeCliProvider(
            model=getattr(cfg, "claude_cli_model", ""),
            allowed_tools=getattr(cfg, "claude_cli_allowed_tools", ""),
            timeout=cfg.timeout_seconds,
        )

    if name == "codex-cli":
        return CodexCliProvider(
            model=getattr(cfg, "codex_cli_model", ""),
            sandbox=getattr(cfg, "codex_cli_sandbox", "workspace-write"),
            timeout=cfg.timeout_seconds,
        )

    if name == "anthropic":
        api_key_env = getattr(cfg, "api_key_env", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        max_tokens = getattr(cfg, "max_tokens", 4096)
        return AnthropicProvider(
            api_key=api_key,
            model=cfg.model,
            timeout=cfg.timeout_seconds,
            max_tokens=max_tokens,
        )

    if name == "openai":
        api_key_env = getattr(cfg, "openai_api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        model = getattr(cfg, "openai_model", _DEFAULT_OPENAI_MODEL) or _DEFAULT_OPENAI_MODEL
        max_tokens = getattr(cfg, "max_tokens", 4096)
        return OpenAIProvider(
            api_key=api_key,
            model=model,
            timeout=cfg.timeout_seconds,
            max_tokens=max_tokens,
        )

    raise ValueError(
        f"Unknown provider name {name!r}.  "
        "Supported: 'ollama', 'claude-cli', 'codex-cli', 'anthropic', 'openai', 'fallback'."
    )


def get_provider(cfg: Any) -> Any:
    """Instantiate the correct provider (or fallback chain) from *cfg*.

    *cfg* is expected to have the attributes of
    :class:`~crew_chief.config_loader.LlmConfig`.  Duck-typed to avoid
    circular imports.

    Supported ``cfg.provider`` values
    -----------------------------------
    ``"ollama"``
        Local Ollama service.
    ``"claude-cli"``
        ``claude`` CLI authenticated via browser account.
    ``"codex-cli"``
        ``codex`` CLI authenticated via browser account.
    ``"anthropic"``
        Anthropic Messages API (reads ``cfg.api_key_env`` env var).
    ``"fallback"``
        Tries each provider in ``cfg.fallback_chain`` in order.
        Default chain: ``["ollama", "claude-cli", "anthropic"]``.
    """
    provider_name = getattr(cfg, "provider", "ollama")

    if provider_name == "fallback":
        chain = getattr(cfg, "fallback_chain", ["ollama", "claude-cli", "anthropic"])
        providers = [_build_single_provider(n, cfg) for n in chain]
        log.info(
            "FallbackProvider chain: %s",
            [type(p).__name__ for p in providers],
        )
        return FallbackProvider(providers)

    return _build_single_provider(provider_name, cfg)
