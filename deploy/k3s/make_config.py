#!/usr/bin/env python3
"""Derive the confined listener config for the K3s pilot from the live one.

The live config describes a host process: it runs host commands, reaches a host Ollama and the
local vault, and reads Signal. In the pod none of that exists, so this keeps the channels and trust
settings, then removes everything the pod cannot or must not do. The output holds private values
(trusted senders), so it is written to a gitignored file and loaded into a Secret, never committed.
"""

from __future__ import annotations

import argparse
import sys
try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

CONFINED_COMMANDS = ["date", "hostname", "uname*", "whoami", "df*"]
CONTAINER_GMAIL_DIR = "/opt/shock-relay/services/gmail-imap"
CONTAINER_GMAIL_CONFIG = "/opt/shock-relay/config/gmail-imap.config.local.yaml"
HOST_ONLY_LLM_KEYS = (
    "auto_pass_env_file",
    "anthropic_api_key_auto_pass_entry",
    "openai_api_key_auto_pass_entry",
    "claude_cli_allowed_tools",
    "ollama_model_chain",
)
CLOUD_CHAIN = ["anthropic", "openai"]


def confine(config: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in config.items()}
    out.setdefault("signal", {})["enabled"] = False
    gmail = out.setdefault("gmail", {})
    gmail["shock_relay_dir"] = CONTAINER_GMAIL_DIR
    gmail["config_path"] = CONTAINER_GMAIL_CONFIG
    llm = out.setdefault("llm", {})
    for key in HOST_ONLY_LLM_KEYS:
        llm.pop(key, None)
    llm["provider"] = "fallback"
    llm["fallback_chain"] = list(CLOUD_CHAIN)
    llm["base_url"] = "http://127.0.0.1:1"  # no local backend in the pod; refused, not reached
    llm.pop("task_chains", None)
    agent = out.setdefault("agent", {})
    agent["provider"] = "fallback"
    agent["fallback_chain"] = list(CLOUD_CHAIN)
    agent["allowed_paths"] = ["/tmp"]
    out.setdefault("dispatch", {})["allowed_commands"] = list(CONFINED_COMMANDS)
    return out


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_scalar(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def dumps(config: dict) -> str:
    lines: list[str] = []
    for key, value in config.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_scalar(value)}")
    for section, table in config.items():
        if not isinstance(table, dict):
            continue
        lines += ["", f"[{section}]"]
        for key, value in table.items():
            if isinstance(value, dict):
                raise TypeError("nested tables are not used by the listener config")
            lines.append(f"{key} = {_scalar(value)}")
    return "\n".join(lines).lstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="live config/listener/config.toml")
    parser.add_argument("--out", type=Path, required=True, help="where to write the confined config")
    args = parser.parse_args(argv)
    confined = confine(tomllib.loads(args.source.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps(confined), encoding="utf-8")
    args.out.chmod(0o600)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
