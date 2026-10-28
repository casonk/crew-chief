"""crew_chief.cli — command-line interface for the crew-chief LLM service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from crew_chief.client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT, CrewChiefClient
from crew_chief.code_launcher import BACKENDS, DEFAULT_CODE_MODEL, DEFAULT_CONTEXT


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

    code_p = sub.add_parser(
        "code",
        aliases=["c"],
        help="Open Claude Code on a local model (beta).",
        description=(
            "Launch Claude Code against a local Anthropic-compatible server "
            "(Ollama or llama-server). Arguments after -- go to claude, "
            "e.g. crew-chief code -- --resume <session-id>."
        ),
    )
    code_p.add_argument(
        "-m",
        "--model",
        dest="code_model",
        default=DEFAULT_CODE_MODEL,
        help=f"Tool-capable model to use (env: CREW_CHIEF_CODE_MODEL, default: {DEFAULT_CODE_MODEL}).",
    )
    code_p.add_argument(
        "--backend",
        default=None,
        choices=BACKENDS,
        help="Override the serving policy's backend for this model (default: from the policy).",
    )
    code_p.add_argument(
        "--context",
        type=int,
        default=None,
        help=(
            "Override the context window, in tokens (default: from the serving policy, "
            f"else CREW_CHIEF_CODE_CONTEXT or {DEFAULT_CONTEXT})."
        ),
    )
    code_p.add_argument(
        "--list",
        action="store_true",
        help="List tool-capable models on the Ollama server and exit.",
    )
    code_p.add_argument(
        "--no-lease",
        action="store_true",
        help=(
            "Do not run the session under an ECU lease (also: CREW_CHIEF_NO_LEASE=1). "
            "By default a model with a measured gpu_mib on the Ollama backend gets one."
        ),
    )
    code_p.add_argument(
        "--skip-check",
        action="store_true",
        help="Launch without checking the server or model first.",
    )
    code_p.add_argument("claude_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)

    policy_p = sub.add_parser(
        "policy",
        help="Show or check the serving policy (config/serving-policy.toml).",
    )
    policy_sub = policy_p.add_subparsers(dest="policy_command", required=True)
    check_p = policy_sub.add_parser("check", help="Validate the policy and its evidence.")
    check_p.add_argument(
        "--live",
        action="store_true",
        help="Also compare against the models pulled in Ollama (drift).",
    )
    show_p = policy_sub.add_parser("show", help="Print the policy, or one model's entry.")
    show_p.add_argument("model", nargs="?")

    storage_p = sub.add_parser(
        "storage",
        help="Rotate retired models down storage tiers (hot -> warm -> cold -> deleted).",
        description=(
            "Tier paths come from ~/.config/crew-chief/storage.toml; rotation rules from "
            "[rotation] in the serving policy. See docs/serving-policy.md."
        ),
    )
    storage_sub = storage_p.add_subparsers(dest="storage_command", required=True)
    storage_sub.add_parser("status", help="Where each model is stored and when it is next benched.")
    storage_sub.add_parser("plan", help="Show the moves and deletions the rotation calls for.")
    apply_p = storage_sub.add_parser("apply", help="Carry out the planned moves.")
    apply_p.add_argument(
        "--delete",
        action="store_true",
        help="Also delete models that have reached the end of the bottom tier.",
    )
    restore_p = storage_sub.add_parser("restore", help="Bring a model back to hot storage.")
    restore_p.add_argument("model")
    bench_p = storage_sub.add_parser(
        "bench-due",
        help="Benchmark warm and cold models whose tier cadence has come round (llama.cpp).",
    )
    bench_p.add_argument("--dry-run", action="store_true", help="List them without running.")

    gguf_p = sub.add_parser(
        "gguf",
        help="llama.cpp-native GGUF copies of the Ollama models (config/gguf-sources.toml).",
    )
    gguf_sub = gguf_p.add_subparsers(dest="gguf_command", required=True)
    gguf_sub.add_parser("list", help="Each model's source and whether it is downloaded.")
    fetch_p = gguf_sub.add_parser("fetch", help="Download and verify missing files.")
    fetch_p.add_argument("models", nargs="*", help="Only these models (default: all).")

    task_p = sub.add_parser(
        "taskbench",
        help="Score models on a task-based decision benchmark (choice/score/noul).",
        description=(
            "Run a task file against one or more runners: rules, ollama:<model>, "
            "llamacpp:<model> (server at CREW_CHIEF_LLAMACPP_URL), systemone:<model> (Ollama's "
            "decision-model endpoint), jev (TYPESAFE_API_KEY). "
            "Results go to results/taskbench-<task>-<timestamp>.{md,json}."
        ),
    )
    task_p.add_argument("task", help="Task file, e.g. benchmarks/decisions/message-routing.json.")
    task_p.add_argument(
        "--runner",
        action="append",
        required=True,
        help="Runner spec; repeat for several (e.g. --runner rules --runner ollama:qwen3:14b).",
    )
    task_p.add_argument("--out", default="results", help="Output directory (default: results).")

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

    elif args.command in ("code", "c"):
        from crew_chief.code_launcher import (
            LaunchError,
            launch,
            ollama_tool_models,
            policy_gpu_mib,
            resolve_serving,
        )

        try:
            if args.list:
                for name in ollama_tool_models(args.url.rstrip("/")):
                    print(name)
                return
            passthrough = args.claude_args
            if passthrough[:1] == ["--"]:
                passthrough = passthrough[1:]
            backend, base_url, context, notes = resolve_serving(
                args.code_model,
                backend=args.backend,
                url=None if args.url == DEFAULT_BASE_URL else args.url,
                context=args.context,
            )
            for note in notes:
                print(f"crew-chief: {note}", file=sys.stderr)
            launch(
                backend=backend,
                base_url=base_url,
                model=args.code_model,
                context=context,
                passthrough=passthrough,
                skip_check=args.skip_check,
                gpu_mib=None if args.no_lease else policy_gpu_mib(args.code_model),
            )
        except LaunchError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)

    elif args.command == "taskbench":
        import time as _time
        from pathlib import Path

        from crew_chief import taskbench as tb

        try:
            task = tb.load_task(Path(args.task))
            runners = [tb.make_runner(spec, task) for spec in args.runner]
        except tb.TaskError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        results = []
        for runner in runners:
            print(f"running {runner.name} on {len(task.items)} items ...", file=sys.stderr)
            results.append(tb.run(task, runner))
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        base = out / f"taskbench-{tb.slug(task.name)}-{stamp}"
        markdown = tb.render_markdown(results, task, stamp)
        base.with_suffix(".md").write_text(markdown, encoding="utf-8")
        base.with_suffix(".json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(markdown)
        print(f"Saved: {base}.md and .json", file=sys.stderr)

    elif args.command == "policy":
        from crew_chief.serving_policy import (
            PolicyError,
            describe,
            load_policy,
            pulled_models,
            review,
        )

        try:
            policy = load_policy()
            if args.policy_command == "show":
                entries = [policy.get(args.model)] if args.model else list(policy.models.values())
                if entries == [None]:
                    print(f"{args.model}: not in the serving policy", file=sys.stderr)
                    sys.exit(1)
                for entry in entries:
                    print(describe(entry))
                return
            pulled = pulled_models(policy.url_for("ollama")) if args.live else None
            below_hot = _below_hot() if args.live else None
            errors, warnings = review(policy, pulled=pulled, below_hot=below_hot)
        except PolicyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        for line in warnings:
            print(f"warning: {line}")
        for line in errors:
            print(f"error: {line}")
        print(f"serving policy: {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1 if errors else 0)

    elif args.command == "storage":
        _storage(args)

    elif args.command == "gguf":
        _gguf(args)

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


def _gguf(args: argparse.Namespace) -> None:
    from crew_chief import gguf_sources as gs
    from crew_chief import model_storage as ms

    try:
        sources = gs.load_sources()
    except gs.SourceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        tiers = ms.load_tiers()
        where = ms.locate(tiers)
    except ms.StorageError:
        tiers, where = None, {}
    wanted = [ms.canonical(m) for m in getattr(args, "models", [])] or sorted(sources)
    unknown = [m for m in wanted if m not in sources]
    if unknown:
        print(f"Error: not in gguf-sources.toml: {', '.join(unknown)}", file=sys.stderr)
        sys.exit(2)
    failed = False
    for name in wanted:
        source = sources[name]
        path = gs.find(source, tiers)
        if args.gguf_command == "list":
            state = str(path) if path else "not downloaded"
            print(f"{name:28} {source.repo}/{source.file}  {state}")
            continue
        if path:
            continue
        tier = where.get(name, "hot")
        try:
            path = gs.fetch(source, gs.gguf_dir(tier, tiers))
            print(f"{name}: verified, {path}")
        except (gs.SourceError, OSError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed = True
    sys.exit(1 if failed else 0)


def _below_hot() -> dict[str, str] | None:
    """Models whose files live on warm or cold storage, or None when tiers are not set up."""
    from crew_chief import model_storage as ms

    try:
        where = ms.locate(ms.load_tiers())
    except ms.StorageError:
        return None
    return {name: tier for name, tier in where.items() if tier != "hot"}


def _storage(args: argparse.Namespace) -> None:
    import subprocess
    from datetime import date

    from crew_chief import model_storage as ms
    from crew_chief.serving_policy import REPO_ROOT, PolicyError, load_policy

    today = date.today()
    try:
        policy = load_policy()
        tiers = ms.load_tiers()
        state = ms.sync_state(ms.load_state(), ms.locate(tiers), today)
    except (PolicyError, ms.StorageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    ollama_url = policy.url_for("ollama")

    def unload(name: str) -> None:
        ms.unload(ollama_url, name)

    try:
        if args.storage_command == "status":
            for name, entry in sorted(state.items(), key=lambda kv: (kv[1]["tier"], kv[0])):
                model = policy.get(name)
                tier = entry["tier"]
                every = policy.rotation[tier].bench_every_days
                last = "weekly timer" if tier == "hot" else entry.get("last_benched", "never")
                served = "" if tier == "hot" or ms.is_linked(name, tiers, tier) else "  NOT LINKED"
                print(
                    f"{tier:<5} {name:<28} {model.status if model else 'unlisted':<10} "
                    f"since {entry.get('since', '?')}  bench every {every} d, last {last}{served}"
                )
        elif args.storage_command in ("plan", "apply"):
            if args.storage_command == "apply":
                for line in ms.repair(tiers):
                    print(f"repaired {line}")
            actions, notes = ms.plan(policy, state, today)
            for note in notes:
                print(f"note: {note}")
            if not actions:
                print("storage: nothing to rotate")
            for action in actions:
                where = f"{action.source} -> {action.target}" if action.target else action.source
                print(f"{action.kind} {action.model}: {where} ({action.reason})")
                if args.storage_command == "plan":
                    continue
                if action.kind == "delete" and not args.delete:
                    print("  skipped: pass --delete to delete")
                    continue
                freed = ms.execute(action, tiers, state, today, before_leaving_hot=unload)
                ms.save_state(state)
                print(f"  done; {freed / 2**30:.1f} GiB freed in {action.source}")
        elif args.storage_command == "restore":
            name = ms.canonical(args.model)
            entry = state.get(name)
            if entry is None:
                print(f"Error: {name} is not in any tier", file=sys.stderr)
                sys.exit(1)
            if entry["tier"] == "hot":
                print(f"{name} is already on hot storage")
                return
            action = ms.Action("move", name, entry["tier"], "hot", "restore")
            ms.execute(action, tiers, state, today)
            print(f"{name}: {action.source} -> hot")
            model = policy.get(name)
            if model and model.status == "retired":
                print("note: still retired in the serving policy; change it in a pull request")
        elif args.storage_command == "bench-due":
            pending = ms.due(policy, state, today)
            if not pending:
                print("storage: no warm or cold model is due a benchmark")
            for name, tier in pending:
                print(f"bench {name} ({tier}, every {policy.rotation[tier].bench_every_days} d)")
                if args.dry_run:
                    continue
                env = {**os.environ, "CREW_CHIEF_MODELS_DIR": str(tiers[tier])}
                script = REPO_ROOT / "scripts" / "llamacpp_bench.sh"
                quick = ["--", "-ngl", "99", "-p", "512", "-n", "128", "-fa", "1", "-r", "2"]
                result = subprocess.run(["bash", str(script), name, *quick], env=env, check=False)
                if result.returncode == 0:
                    state[name]["last_benched"] = today.isoformat()
                else:
                    print(f"  benchmark failed for {name}; will retry next run", file=sys.stderr)
        ms.save_state(state)
    except ms.StorageError as exc:
        ms.save_state(state)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
