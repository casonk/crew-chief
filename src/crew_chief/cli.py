"""crew_chief.cli — command-line interface for the crew-chief LLM service."""

from __future__ import annotations

import argparse
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


if __name__ == "__main__":
    main()
