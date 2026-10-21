"""crew_chief.code_launcher — run Claude Code against a local inference backend.

Ollama (>= 0.14) and llama.cpp's ``llama-server`` both serve the Anthropic
Messages API, so Claude Code can drive a local model when pointed at them.
This module builds that environment, checks the model is usable as an agent,
and records each launched session so session-control can label and resume it.

Stdlib only, like the rest of the client package.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CODE_MODEL: str = os.environ.get("CREW_CHIEF_CODE_MODEL", "qwen3:14b")
DEFAULT_CONTEXT: int = int(os.environ.get("CREW_CHIEF_CODE_CONTEXT", "32768"))
BACKENDS = ("ollama", "llamacpp")

# Flags that make Claude Code reopen an existing session rather than start one.
_RESUME_FLAGS = ("--resume", "-r", "--continue", "-c")


class LaunchError(RuntimeError):
    """Raised when the backend or model is not usable for a coding session."""


def registry_path() -> Path:
    """JSONL file mapping launched session IDs to their backend and model."""
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "crew-chief" / "code-sessions.jsonl"


def _get_json(url: str, timeout: int, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ollama_tool_models(base_url: str, timeout: int = 10) -> list[str]:
    """Return pulled Ollama models whose capabilities include tool calling."""
    try:
        tags = _get_json(f"{base_url}/api/tags", timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise LaunchError(
            f"Ollama is not reachable at {base_url} ({exc}). Start it with scripts/start.sh."
        ) from exc
    names = [m["name"] for m in tags.get("models", [])]
    usable = []
    for name in names:
        try:
            info = _get_json(f"{base_url}/api/show", timeout, {"model": name})
        except (urllib.error.URLError, OSError):
            continue
        if "tools" in info.get("capabilities", []):
            usable.append(name)
    return sorted(usable)


def check_model(backend: str, base_url: str, model: str, timeout: int = 10) -> None:
    """Fail early when the model cannot act as an agent on this backend.

    Only Ollama exposes per-model capabilities; llama-server serves whatever
    it was started with, so it is checked for reachability only.
    """
    if backend == "ollama":
        usable = ollama_tool_models(base_url, timeout)
        if model not in usable:
            listing = "\n  ".join(usable) or "(none)"
            raise LaunchError(
                f"Model {model!r} is not pulled or does not support tool calling.\n"
                f"Tool-capable models on {base_url}:\n  {listing}"
            )
        return
    try:
        _get_json(f"{base_url}/health", timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise LaunchError(
            f"llama-server is not reachable at {base_url} ({exc}). Start it with the "
            "configuration in `crew-chief policy show <model>` (see "
            "docs/local-inference-roadmap.md), or pass --backend ollama."
        ) from exc


def resolve_serving(
    model: str,
    backend: str | None = None,
    url: str | None = None,
    context: int | None = None,
    policy_loader=None,
) -> tuple[str, str, int, list[str]]:
    """Backend, base URL, and context for ``model``, from the serving policy.

    Explicit arguments override the policy. A model the policy retires is
    refused; one it does not list is served on Ollama defaults with a note.
    An unreadable policy never blocks a launch.
    """
    from crew_chief.serving_policy import PolicyError, load_policy

    notes: list[str] = []
    entry = None
    policy = None
    try:
        policy = (policy_loader or load_policy)()
        entry = policy.get(model)
    except PolicyError as exc:
        notes.append(f"serving policy unavailable ({exc}); using defaults")
    if entry is None and policy is not None:
        notes.append(f"{model} is not in the serving policy; serving on Ollama defaults")
    if entry is not None and entry.status == "retired":
        raise LaunchError(f"{model} is retired in the serving policy")
    if entry is not None and entry.status == "unreviewed":
        notes.append(f"{model} is unreviewed in the serving policy (no benchmark evidence)")

    chosen = backend or (entry.backend if entry else "ollama")
    if entry is not None and backend and backend != entry.backend:
        notes.append(f"overriding the policy's backend ({entry.backend}) with {backend}")
    if url is None:
        defaults = {"ollama": "http://localhost:11434", "llamacpp": "http://localhost:8081"}
        url = policy.url_for(chosen) if policy is not None else defaults[chosen]
    ctx = context or (entry.context if entry and entry.context else None) or DEFAULT_CONTEXT
    return chosen, url, ctx, notes


def build_env(base_url: str, model: str, context: int, base: dict[str, str]) -> dict[str, str]:
    """Environment that points Claude Code at a local Anthropic-compatible server."""
    env = dict(base)
    env.update(
        {
            "ANTHROPIC_BASE_URL": base_url,
            # Local servers ignore the token, but Claude Code needs one to skip login.
            "ANTHROPIC_AUTH_TOKEN": "local",
            "ANTHROPIC_API_KEY": "",
            # Background, subagent and alias requests would otherwise ask the
            # server for Claude model IDs it does not have.
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
            "ANTHROPIC_SMALL_FAST_MODEL": model,
            "CLAUDE_CODE_SUBAGENT_MODEL": model,
            # Unknown model IDs default to a 200k window; match the server's.
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(context),
        }
    )
    return env


def build_argv(model: str, passthrough: list[str], session_id: str | None) -> list[str]:
    argv = ["claude", "--model", model]
    if session_id:
        argv += ["--session-id", session_id]
    return argv + passthrough


def is_resume(passthrough: list[str]) -> bool:
    return any(arg in _RESUME_FLAGS or arg.startswith("--resume=") for arg in passthrough)


def record_session(
    path: Path, session_id: str, backend: str, base_url: str, model: str, cwd: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "session_id": session_id,
        "frontend": "claude",
        "backend": backend,
        "base_url": base_url,
        "model": model,
        "cwd": cwd,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def launch(
    backend: str,
    base_url: str,
    model: str,
    context: int,
    passthrough: list[str],
    skip_check: bool = False,
) -> None:
    """Validate, record the session, and replace this process with Claude Code."""
    if shutil.which("claude") is None:
        raise LaunchError("Claude Code ('claude') is not on PATH.")
    base_url = base_url.rstrip("/")
    if not skip_check:
        check_model(backend, base_url, model)

    session_id = None
    if not is_resume(passthrough):
        session_id = str(uuid.uuid4())
        record_session(registry_path(), session_id, backend, base_url, model, os.getcwd())

    env = build_env(base_url, model, context, dict(os.environ))
    argv = build_argv(model, passthrough, session_id)
    sys.stdout.flush()
    os.execvpe("claude", argv, env)
