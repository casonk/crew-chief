#!/usr/bin/env python3
"""Resolve the pilot's credentials from the vault into files for `kubectl create secret`.

A pod cannot reach the local vault, so the values are read here, once, with the same resolvers the
host listener uses, and written to a 0700 directory that apply.sh deletes after loading. Nothing is
printed. Output files: listener.env (API keys and Gmail credentials) and gmail.config.local.yaml
(the Gmail service config rewritten to read those values from the environment).
"""

from __future__ import annotations

import argparse
import sys
try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore[no-redef]
from pathlib import Path

import yaml

ENV_NAMES = {"username": "GMAIL_IMAP_USERNAME", "password": "GMAIL_IMAP_APP_PASSWORD"}


def gmail_config(live: dict) -> dict:
    """The live Gmail config with vault entries replaced by environment variable names."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in live.items()}
    out.pop("keepass_profile", None)
    imap = out.setdefault("imap", {})
    for key in ("username_keepass_entry", "password_keepass_entry", "username", "password"):
        imap.pop(key, None)
    imap["username_env"], imap["password_env"] = ENV_NAMES["username"], ENV_NAMES["password"]
    smtp = out.get("smtp")
    if isinstance(smtp, dict):
        for key in ("username_keepass_entry", "password_keepass_entry", "username", "password"):
            smtp.pop(key, None)
        smtp["username_env"], smtp["password_env"] = ENV_NAMES["username"], ENV_NAMES["password"]
    out.setdefault("paths", {})["data_dir"] = "/tmp/gmail-imap"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listener-config", type=Path, required=True)
    parser.add_argument("--gmail-config", type=Path, required=True)
    parser.add_argument("--crew-chief-src", type=Path, required=True)
    parser.add_argument("--gmail-dir", type=Path, required=True, help="shock-relay services/gmail-imap")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    sys.path[:0] = [str(args.crew_chief_src), str(args.gmail_dir)]
    from common import load_config  # shock-relay's own resolver  # noqa: PLC0415
    from crew_chief.providers import _resolve_api_key  # noqa: PLC0415

    listener = tomllib.loads(args.listener_config.read_text(encoding="utf-8"))
    llm = listener.get("llm", {})
    env_file = llm.get("auto_pass_env_file", "")
    lines = []
    for var, entry_key in (
        ("ANTHROPIC_API_KEY", "anthropic_api_key_auto_pass_entry"),
        ("OPENAI_API_KEY", "openai_api_key_auto_pass_entry"),
    ):
        value = _resolve_api_key(var, llm.get(entry_key, ""), env_file)
        if value:
            lines.append(f"{var}={value}")
    if not any(line.startswith("ANTHROPIC_API_KEY=") or line.startswith("OPENAI_API_KEY=") for line in lines):
        print("warning: no cloud API key resolved; the pod would have no LLM", file=sys.stderr)

    gmail = load_config(str(args.gmail_config))
    lines.append(f"{ENV_NAMES['username']}={gmail.imap.username}")
    lines.append(f"{ENV_NAMES['password']}={gmail.imap.password}")

    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.out.chmod(0o700)
    env_path = args.out / "listener.env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)
    yaml_path = args.out / "gmail.config.local.yaml"
    live = yaml.safe_load(args.gmail_config.read_text(encoding="utf-8")) or {}
    yaml_path.write_text(yaml.safe_dump(gmail_config(live), sort_keys=False), encoding="utf-8")
    yaml_path.chmod(0o600)
    print(f"wrote {len(lines)} credential(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
