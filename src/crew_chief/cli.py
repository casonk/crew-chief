"""crew_chief.cli — command-line interface for the crew-chief LLM service."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from crew_chief.client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT, CrewChiefClient


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crew-chief",
        description="CLI client for the local crew-chief Ollama LLM service.",
    )
    p.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help="Base URL of the Ollama service (env: CREW_CHIEF_URL).",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model name to use (env: CREW_CHIEF_MODEL).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds (env: CREW_CHIEF_TIMEOUT).",
    )

    sub = p.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", aliases=["g"], help="Generate a response for a prompt.")
    gen.add_argument("prompt", help="The prompt text.")

    sub.add_parser("health", aliases=["h"], help="Check if the service is reachable.")
    sub.add_parser("models", aliases=["m"], help="List available models on the server.")

    listen_p = sub.add_parser(
        "listen",
        aliases=["l"],
        help="Start the shock-relay listener: poll Signal/Gmail, dispatch commands, reply.",
    )
    listen_p.add_argument(
        "--config",
        required=True,
        metavar="PATH",
        help="Path to the listener config TOML file (e.g. config/listener/config.toml).",
    )
    listen_p.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll cycle and exit (useful for testing).",
    )
    listen_p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )

    agent_p = sub.add_parser(
        "agent",
        aliases=["a"],
        help="Run a single agentic task and print the result.",
    )
    agent_p.add_argument("prompt", help="The task description or question for the agent.")
    agent_p.add_argument(
        "--provider",
        default="fallback",
        choices=["ollama", "claude-cli", "codex-cli", "anthropic", "openai", "fallback"],
        help="LLM provider backend (default: fallback — tries ollama, claude-cli, anthropic).",
    )
    agent_p.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        metavar="N",
        help="Maximum tool-use cycles (default: 10).",
    )
    agent_p.add_argument(
        "--tools",
        nargs="*",
        default=[],
        metavar="TOOL",
        help="Built-in tools to enable: shell, read_file, write_file.",
    )
    agent_p.add_argument(
        "--allowed-commands",
        nargs="*",
        default=["df*", "free*", "uptime", "hostname", "date", "ls *", "uname*", "whoami"],
        metavar="PATTERN",
        help="fnmatch patterns allowed for the shell tool.",
    )
    agent_p.add_argument(
        "--allowed-paths",
        nargs="*",
        default=[],
        metavar="PATH",
        help="Path prefixes allowed for file tools (empty = unrestricted).",
    )
    agent_p.add_argument(
        "--system",
        default="",
        metavar="PROMPT",
        help="Override the agent system prompt.",
    )
    agent_p.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: WARNING).",
    )

    return p


def main(argv: list[str] | None = None) -> None:
    p = build_parser()
    args = p.parse_args(argv)
    client = CrewChiefClient(base_url=args.url, model=args.model, timeout=args.timeout)

    if args.command in ("generate", "g"):
        print(client.generate(args.prompt))

    elif args.command in ("health", "h"):
        ok = client.health()
        print("ok" if ok else "unreachable")
        sys.exit(0 if ok else 1)

    elif args.command in ("models", "m"):
        for name in client.list_models():
            print(name)

    elif args.command in ("listen", "l"):
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        from crew_chief.config_loader import ConfigError, load
        from crew_chief.listener import run

        try:
            cfg = load(args.config)
        except ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)

        run(cfg, once=args.once)

    elif args.command in ("agent", "a"):
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

        from crew_chief.agent import Agent
        from crew_chief.dispatcher import Dispatcher
        from crew_chief.providers import FallbackProvider
        from crew_chief.providers.anthropic import AnthropicProvider
        from crew_chief.providers.cli import ClaudeCliProvider, CodexCliProvider
        from crew_chief.providers.ollama import OllamaProvider
        from crew_chief.providers.openai import OpenAIProvider
        from crew_chief.tools import ReadFileTool, ShellTool, Tool, WriteFileTool

        # Build provider
        if args.provider == "fallback":
            provider = FallbackProvider(
                [
                    OllamaProvider(base_url=args.url, model=args.model, timeout=args.timeout),
                    ClaudeCliProvider(model=args.model, timeout=args.timeout),
                    CodexCliProvider(model=args.model, timeout=args.timeout),
                    AnthropicProvider(
                        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                        model=args.model,
                        timeout=args.timeout,
                    ),
                    OpenAIProvider(
                        api_key=os.environ.get("OPENAI_API_KEY", ""),
                        timeout=args.timeout,
                    ),
                ]
            )
        elif args.provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                print(
                    "Error: ANTHROPIC_API_KEY environment variable is not set.",
                    file=sys.stderr,
                )
                sys.exit(2)
            provider = AnthropicProvider(api_key=api_key, model=args.model, timeout=args.timeout)
        elif args.provider == "claude-cli":
            provider = ClaudeCliProvider(model=args.model, timeout=args.timeout)
        elif args.provider == "codex-cli":
            provider = CodexCliProvider(model=args.model, timeout=args.timeout)
        elif args.provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                print(
                    "Error: OPENAI_API_KEY environment variable is not set.",
                    file=sys.stderr,
                )
                sys.exit(2)
            provider = OpenAIProvider(api_key=api_key, timeout=args.timeout)
        else:
            provider = OllamaProvider(base_url=args.url, model=args.model, timeout=args.timeout)

        # Build tools
        tools: list[Tool] = []
        for tool_name in args.tools:
            if tool_name == "shell":
                dispatcher = Dispatcher(
                    allowed_commands=args.allowed_commands,
                    timeout_seconds=30,
                    max_output_bytes=4000,
                )
                tools.append(ShellTool(dispatcher))
            elif tool_name == "read_file":
                tools.append(ReadFileTool(allowed_paths=args.allowed_paths or None))
            elif tool_name == "write_file":
                tools.append(WriteFileTool(allowed_paths=args.allowed_paths or None))
            else:
                print(f"Warning: unknown tool {tool_name!r} — ignored.", file=sys.stderr)

        agent = Agent(
            provider=provider,
            tools=tools,
            system_prompt=args.system,
            max_iterations=args.max_iterations,
        )
        print(agent.run(args.prompt))


if __name__ == "__main__":
    main()
