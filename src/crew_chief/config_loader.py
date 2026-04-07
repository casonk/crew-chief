"""crew_chief.config_loader — load and validate listener.toml configuration.

The listener feature depends on TOML parsing.  Python 3.11+ ships ``tomllib``;
Python 3.10 needs the third-party ``tomli`` back-port (installed via the
``listener`` optional-extras group: ``pip install "crew-chief[listener]"``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError as _err:
        raise ImportError(
            "The crew-chief listener requires tomllib (Python ≥ 3.11) or tomli "
            "(pip install 'crew-chief[listener]')."
        ) from _err


class ConfigError(ValueError):
    """Raised when the listener config is missing or invalid."""


@dataclass
class LlmConfig:
    model: str = "llama3.2"
    # When True, natural-language messages are routed through the LLM for
    # command extraction.  When False, only messages starting with "!" are
    # processed (the "!" prefix is stripped and the rest is used verbatim).
    natural_language: bool = True
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 60

    # ------------------------------------------------------------------ #
    # Provider selection                                                   #
    # ------------------------------------------------------------------ #
    # Supported values:
    #   "ollama"     — local Ollama service (default)
    #   "claude-cli" — claude CLI logged in via browser account
    #   "codex-cli"  — codex CLI logged in via browser account
    #   "anthropic"  — Anthropic Messages API (requires api_key_env)
    #   "fallback"   — try each provider in fallback_chain order
    provider: str = "ollama"

    # Ordered list of provider names used when provider = "fallback".
    fallback_chain: list[str] = field(
        default_factory=lambda: ["ollama", "claude-cli", "codex-cli", "anthropic", "openai"]
    )

    # ------------------------------------------------------------------ #
    # Anthropic API settings                                               #
    # ------------------------------------------------------------------ #
    # Name of the environment variable that holds the Anthropic API key.
    api_key_env: str = "ANTHROPIC_API_KEY"
    # Upper bound on generated tokens.
    max_tokens: int = 4096

    # ------------------------------------------------------------------ #
    # Claude CLI settings                                                  #
    # ------------------------------------------------------------------ #
    # Model alias/ID for the claude CLI.  Empty = CLI default.
    claude_cli_model: str = ""
    # Tool names to allow (e.g. "Bash,Read,Edit").  Empty = no tools
    # (pure text generation — fastest for simple Q&A).
    claude_cli_allowed_tools: str = ""

    # ------------------------------------------------------------------ #
    # Codex CLI settings                                                   #
    # ------------------------------------------------------------------ #
    # Model name for the codex CLI.  Empty = CLI default.
    codex_cli_model: str = ""
    # Sandbox policy: "read-only", "workspace-write", "danger-full-access".
    codex_cli_sandbox: str = "workspace-write"

    # ------------------------------------------------------------------ #
    # OpenAI API settings                                                  #
    # ------------------------------------------------------------------ #
    # Name of the environment variable that holds the OpenAI API key.
    openai_api_key_env: str = "OPENAI_API_KEY"
    # Model ID for the OpenAI provider.
    openai_model: str = "gpt-4o"


@dataclass
class AgentConfig:
    # When True, incoming messages are handled by the multi-step Agent loop
    # instead of the single-command dispatch flow.
    enabled: bool = False
    # Hard cap on tool-use cycles per request to prevent infinite loops.
    max_iterations: int = 10
    # System prompt sent to the model on every agent call.  Empty string uses
    # the default prompt defined in crew_chief.agent.
    system_prompt: str = ""
    # Built-in tool names to enable: "shell", "read_file", "write_file".
    tools: list[str] = field(default_factory=lambda: ["shell"])
    # Path prefixes the model is allowed to read/write via file tools.
    # An empty list permits all paths (no restriction).
    allowed_paths: list[str] = field(default_factory=list)


@dataclass
class SignalConfig:
    enabled: bool = False
    # Absolute path to the shock-relay services/signal-cli directory.
    shock_relay_dir: str = ""
    # Path to the signal-cli config.local.yaml used by shock-relay.
    config_path: str = ""
    # Only process incoming messages from these phone numbers.
    trusted_senders: list[str] = field(default_factory=list)
    # Phone number to send replies to (usually your own registered number).
    reply_to: str = ""


@dataclass
class GmailConfig:
    enabled: bool = False
    # Absolute path to the shock-relay services/gmail-imap directory.
    shock_relay_dir: str = ""
    # Path to the gmail-imap config.local.yaml used by shock-relay.
    config_path: str = ""
    # Only process incoming messages from these email addresses.
    trusted_senders: list[str] = field(default_factory=list)
    # Email address to send replies to.
    reply_to: str = ""
    # Days of history to scan for new mail on each poll.
    since_days: int = 1
    # Maximum unseen messages to retrieve per poll cycle.
    limit: int = 5


@dataclass
class DispatchConfig:
    # Hard timeout per command in seconds.
    timeout_seconds: int = 30
    # Maximum output bytes included in the reply message.
    output_max_bytes: int = 2000
    # fnmatch-style globs matched against the full command string.
    # The command must match at least one pattern before it is executed.
    allowed_commands: list[str] = field(
        default_factory=lambda: [
            "df*",
            "free*",
            "uptime",
            "hostname",
            "date",
            "ping -c *",
            "ls *",
            "uname*",
            "whoami",
        ]
    )


@dataclass
class ListenerConfig:
    # Seconds to sleep between full poll cycles (Signal + Gmail).
    poll_interval_seconds: int = 30
    llm: LlmConfig = field(default_factory=LlmConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    gmail: GmailConfig = field(default_factory=GmailConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)


def _str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string, got {type(value).__name__}.")
    return value


def _int(value: Any, key: str) -> int:
    if not isinstance(value, int):
        raise ConfigError(f"Config key '{key}' must be an integer, got {type(value).__name__}.")
    return value


def _bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"Config key '{key}' must be a boolean, got {type(value).__name__}.")
    return value


def _str_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"Config key '{key}' must be a list of strings.")
    return list(value)


def load(path: str | Path) -> ListenerConfig:
    """Load and return a :class:`ListenerConfig` from *path*.

    Raises :class:`ConfigError` if the file cannot be read or contains invalid
    values.
    """
    p = Path(path)
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Listener config not found: {p}") from exc
    except Exception as exc:
        raise ConfigError(f"Cannot parse listener config {p}: {exc}") from exc

    cfg = ListenerConfig()

    top = raw.get("listener", {})
    if "poll_interval_seconds" in top:
        cfg.poll_interval_seconds = _int(
            top["poll_interval_seconds"], "listener.poll_interval_seconds"
        )

    llm = raw.get("llm", {})
    if "model" in llm:
        cfg.llm.model = _str(llm["model"], "llm.model")
    if "natural_language" in llm:
        cfg.llm.natural_language = _bool(llm["natural_language"], "llm.natural_language")
    if "base_url" in llm:
        cfg.llm.base_url = _str(llm["base_url"], "llm.base_url")
    if "timeout_seconds" in llm:
        cfg.llm.timeout_seconds = _int(llm["timeout_seconds"], "llm.timeout_seconds")
    if "provider" in llm:
        cfg.llm.provider = _str(llm["provider"], "llm.provider")
    if "fallback_chain" in llm:
        cfg.llm.fallback_chain = _str_list(llm["fallback_chain"], "llm.fallback_chain")
    if "api_key_env" in llm:
        cfg.llm.api_key_env = _str(llm["api_key_env"], "llm.api_key_env")
    if "max_tokens" in llm:
        cfg.llm.max_tokens = _int(llm["max_tokens"], "llm.max_tokens")
    if "claude_cli_model" in llm:
        cfg.llm.claude_cli_model = _str(llm["claude_cli_model"], "llm.claude_cli_model")
    if "claude_cli_allowed_tools" in llm:
        cfg.llm.claude_cli_allowed_tools = _str(
            llm["claude_cli_allowed_tools"], "llm.claude_cli_allowed_tools"
        )
    if "codex_cli_model" in llm:
        cfg.llm.codex_cli_model = _str(llm["codex_cli_model"], "llm.codex_cli_model")
    if "codex_cli_sandbox" in llm:
        cfg.llm.codex_cli_sandbox = _str(llm["codex_cli_sandbox"], "llm.codex_cli_sandbox")
    if "openai_api_key_env" in llm:
        cfg.llm.openai_api_key_env = _str(llm["openai_api_key_env"], "llm.openai_api_key_env")
    if "openai_model" in llm:
        cfg.llm.openai_model = _str(llm["openai_model"], "llm.openai_model")

    agt = raw.get("agent", {})
    if "enabled" in agt:
        cfg.agent.enabled = _bool(agt["enabled"], "agent.enabled")
    if "max_iterations" in agt:
        cfg.agent.max_iterations = _int(agt["max_iterations"], "agent.max_iterations")
    if "system_prompt" in agt:
        cfg.agent.system_prompt = _str(agt["system_prompt"], "agent.system_prompt")
    if "tools" in agt:
        cfg.agent.tools = _str_list(agt["tools"], "agent.tools")
    if "allowed_paths" in agt:
        cfg.agent.allowed_paths = _str_list(agt["allowed_paths"], "agent.allowed_paths")

    sig = raw.get("signal", {})
    if "enabled" in sig:
        cfg.signal.enabled = _bool(sig["enabled"], "signal.enabled")
    if "shock_relay_dir" in sig:
        cfg.signal.shock_relay_dir = _str(sig["shock_relay_dir"], "signal.shock_relay_dir")
    if "config_path" in sig:
        cfg.signal.config_path = _str(sig["config_path"], "signal.config_path")
    if "trusted_senders" in sig:
        cfg.signal.trusted_senders = _str_list(sig["trusted_senders"], "signal.trusted_senders")
    if "reply_to" in sig:
        cfg.signal.reply_to = _str(sig["reply_to"], "signal.reply_to")

    gm = raw.get("gmail", {})
    if "enabled" in gm:
        cfg.gmail.enabled = _bool(gm["enabled"], "gmail.enabled")
    if "shock_relay_dir" in gm:
        cfg.gmail.shock_relay_dir = _str(gm["shock_relay_dir"], "gmail.shock_relay_dir")
    if "config_path" in gm:
        cfg.gmail.config_path = _str(gm["config_path"], "gmail.config_path")
    if "trusted_senders" in gm:
        cfg.gmail.trusted_senders = _str_list(gm["trusted_senders"], "gmail.trusted_senders")
    if "reply_to" in gm:
        cfg.gmail.reply_to = _str(gm["reply_to"], "gmail.reply_to")
    if "since_days" in gm:
        cfg.gmail.since_days = _int(gm["since_days"], "gmail.since_days")
    if "limit" in gm:
        cfg.gmail.limit = _int(gm["limit"], "gmail.limit")

    dis = raw.get("dispatch", {})
    if "timeout_seconds" in dis:
        cfg.dispatch.timeout_seconds = _int(dis["timeout_seconds"], "dispatch.timeout_seconds")
    if "output_max_bytes" in dis:
        cfg.dispatch.output_max_bytes = _int(dis["output_max_bytes"], "dispatch.output_max_bytes")
    if "allowed_commands" in dis:
        cfg.dispatch.allowed_commands = _str_list(
            dis["allowed_commands"], "dispatch.allowed_commands"
        )

    return cfg
