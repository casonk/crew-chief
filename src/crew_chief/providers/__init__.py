"""crew_chief.providers — pluggable LLM provider backends."""

from __future__ import annotations

import logging
from typing import Any

from crew_chief.providers.anthropic import AnthropicProvider
from crew_chief.providers.base import (
    ChatResult,
    Provider,
    ProviderUnavailableError,
    ToolParam,
    ToolUse,
)
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
    "build_provider",
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


def _resolve_api_key(env_var: str, auto_pass_entry: str) -> str:
    """Return an API key, trying *env_var* first then auto-pass.

    If *env_var* is set in the environment its value is returned immediately.
    Otherwise, if *auto_pass_entry* is non-empty, ``auto-pass get <entry>
    --field password`` is called as a subprocess and its stdout is used.
    Returns an empty string when both sources are absent or fail.
    """
    import os
    import subprocess

    key = os.environ.get(env_var, "")
    if key:
        return key
    if not auto_pass_entry:
        return ""
    try:
        result = subprocess.run(
            ["auto-pass", "get", auto_pass_entry, "--field", "password"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            key = result.stdout.strip()
            if key:
                log.debug(
                    "Loaded %s from auto-pass entry %r.", env_var, auto_pass_entry
                )
                return key
        log.warning(
            "auto-pass lookup for %r failed (rc=%d): %s",
            auto_pass_entry,
            result.returncode,
            result.stderr.strip()[:200],
        )
    except FileNotFoundError:
        log.debug("auto-pass not found on PATH — skipping key lookup for %r.", env_var)
    except Exception as exc:
        log.warning("auto-pass lookup for %r raised: %s", auto_pass_entry, exc)
    return ""


def _build_single_provider(name: str, cfg: Any) -> Any:
    """Build one provider from its name and a LlmConfig-like *cfg* object."""
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
        auto_pass_entry = getattr(cfg, "api_key_auto_pass_entry", "")
        api_key = _resolve_api_key(api_key_env, auto_pass_entry)
        max_tokens = getattr(cfg, "max_tokens", 4096)
        return AnthropicProvider(
            api_key=api_key,
            model=cfg.model,
            timeout=cfg.timeout_seconds,
            max_tokens=max_tokens,
        )

    if name == "openai":
        api_key_env = getattr(cfg, "openai_api_key_env", "OPENAI_API_KEY")
        auto_pass_entry = getattr(cfg, "openai_api_key_auto_pass_entry", "")
        api_key = _resolve_api_key(api_key_env, auto_pass_entry)
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


def build_provider(name: str, cfg: Any) -> Any:
    """Public alias for building a single named provider from *cfg*.

    Convenience wrapper around :func:`_build_single_provider` for callers that
    need to construct individual providers (e.g. to build per-provider agent
    instances for a confidence-based cascade).
    """
    return _build_single_provider(name, cfg)


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
