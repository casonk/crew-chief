# AGENTS.md

## Purpose

`crew-chief` is a local LLM service and agentic workflow engine backed by [Ollama](https://ollama.com) (local) and the Anthropic API (cloud), containerized with Podman, and exposed via a zero-dependency Python client.  Other portfolio repositories call it for inference tasks (classification, summarization, brief generation, multi-step tool-use workflows) without requiring extra HTTP libraries.

The repo ships three layers:

1. **Container definition** (`Containerfile`) — builds a Podman image wrapping the upstream `ollama/ollama` image and exposes the REST API on port 11434.
2. **Python client package** (`src/crew_chief/`) — stdlib-only provider backends, a multi-step `Agent` loop, and built-in tools (`shell`, `read_file`, `write_file`).
3. **Listener service** (`src/crew_chief/listener.py`) — polls Signal and Gmail, routes messages through the LLM (single-command or full agent mode), dispatches allowlisted shell commands, and replies.

## Repository Layout

```
crew-chief/
├── Containerfile                          # Podman image definition (FROM ollama/ollama)
├── pyproject.toml                         # Package metadata, ruff/black config, pytest config
├── src/crew_chief/
│   ├── __init__.py                        # Public re-exports, __version__
│   ├── __main__.py                        # python -m crew_chief entry point
│   ├── client.py                          # CrewChiefClient — legacy Ollama HTTP client
│   ├── cli.py                             # CLI: generate / health / models / listen / agent
│   ├── agent.py                           # Agent — multi-step plan→act→observe loop
│   ├── tools.py                           # Tool base class + ShellTool / ReadFileTool / WriteFileTool
│   ├── providers/
│   │   ├── __init__.py                    # get_provider() factory + re-exports
│   │   ├── base.py                        # Provider protocol, ToolParam, ToolUse, ChatResult
│   │   ├── ollama.py                      # OllamaProvider — local Ollama REST API
│   │   └── anthropic.py                   # AnthropicProvider — Anthropic Messages API
│   ├── dispatcher.py                      # Allowlisted shell command execution
│   ├── listener.py                        # Signal/Gmail poll loop + agent/dispatch routing
│   └── config_loader.py                   # TOML config: ListenerConfig + AgentConfig
├── tests/
│   ├── test_client.py                     # Offline unit tests for CrewChiefClient
│   ├── test_dispatcher.py                 # Offline unit tests for Dispatcher
│   ├── test_listener.py                   # Offline unit tests for listener
│   ├── test_providers.py                  # Offline unit tests for OllamaProvider / AnthropicProvider
│   ├── test_agent.py                      # Offline unit tests for Agent loop
│   └── test_tools.py                      # Unit tests for ShellTool / ReadFileTool / WriteFileTool
├── scripts/
│   ├── start.sh                           # Build image (if absent) + start container
│   ├── stop.sh                            # Stop running container
│   ├── status.sh                          # Container state + service health check
│   └── pull_model.sh                      # Pull a model into the running service
├── config/
│   ├── ollama/config.env.example          # Ollama env vars template (do not commit config.env)
│   ├── listener/config.toml               # Listener + agent + dispatch config
│   └── downstream-repos.toml             # Tracked inventory of downstream consumers
└── docs/
    ├── contributor-architecture-blueprint.md
    └── diagrams/
        ├── repo-architecture.puml
        └── repo-architecture.drawio
```

## Quick Start

```bash
# 1. Build the Podman image and start the service
bash scripts/start.sh

# 2. Pull a model
bash scripts/pull_model.sh llama3.2

# 3. Check the service is up
bash scripts/status.sh

# 4. Install the Python client (in another repo)
pip install -e ./util-repos/crew-chief

# 5. Use from Python
from crew_chief import CrewChiefClient
client = CrewChiefClient()
print(client.generate("What is 2+2?"))
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CREW_CHIEF_URL` | `http://localhost:11434` | Base URL of the Ollama service |
| `CREW_CHIEF_MODEL` | `llama3.2` | Default model name |
| `CREW_CHIEF_TIMEOUT` | `60` | Request timeout in seconds |
| `CREW_CHIEF_CONTAINER` | `crew-chief` | Podman container name |
| `CREW_CHIEF_IMAGE` | `crew-chief:latest` | Podman image name |
| `CREW_CHIEF_PORT` | `11434` | Host port to bind |
| `CREW_CHIEF_MODELS_VOLUME` | `crew-chief-models` | Podman volume for model weights |
| `ANTHROPIC_API_KEY` | *(unset)* | API key for the Anthropic provider (set `llm.api_key_env` to use a different name) |

## Architecture Notes

- The container is stateless; model weights are persisted in the named Podman volume `crew-chief-models`.
- The entire Python package is stdlib-only (`json`, `urllib`) — no third-party runtime dependencies.
- `stream` is always `False`; streaming is not exposed through the current client or provider APIs.

### Provider layer (`src/crew_chief/providers/`)

Three tiers, tried in order when `provider = "fallback"`:

| Tier | Class | Backend | Auth | Tool calling |
|---|---|---|---|---|
| 1 | `OllamaProvider` | Local Ollama service (port 11434) | None — local service | Yes — Ollama `/api/chat` with `tools:` |
| 2 | `ClaudeCliProvider` | `claude -p --output-format json` | Browser login (Claude account) | Claude's own internal tools (`--allowedTools Bash,…`) |
| 2 | `CodexCliProvider` | `codex exec --json -o <file>` | Browser login (OpenAI account) | Codex's own internal agentic loop |
| 3 | `AnthropicProvider` | Anthropic Messages API | `ANTHROPIC_API_KEY` env var | Yes — `tools:` + `tool_use` content blocks |

All four implement the `Provider` protocol (`chat()` + `generate()`).  `get_provider(cfg)` builds the right backend (or a `FallbackProvider` wrapping a chain) based on `cfg.provider`.

`ProviderUnavailableError` is raised when a provider cannot serve (service down, CLI not installed, not logged in, no API key, quota exhausted).  `FallbackProvider` catches it and advances to the next tier; other exceptions cause a WARNING log and also advance.

The providers share a normalized internal message format:
- Plain turn: `{"role": "user"|"assistant", "content": str}`
- Tool-use turn: `{"role": "assistant", "content": str, "tool_uses": [{"id", "name", "arguments"}]}`
- Tool results: `{"role": "tool_result", "results": [{"tool_use_id", "name", "content"}]}`

CLI providers (tiers 2) convert the full message history to a single prompt string and let the CLI's own agent loop handle any tool use; they always return `ChatResult` with no `tool_uses`.

### Agent loop (`src/crew_chief/agent.py`)

`Agent.run(prompt)` drives a plan → act → observe cycle:
1. Call `provider.chat(messages, tools, system)`.
2. If `stop_reason == "tool_use"`: execute each requested tool, append results, repeat.
3. If plain text response or `max_iterations` reached: return the content.

### Built-in tools (`src/crew_chief/tools.py`)

| Tool | Class | Safety |
|---|---|---|
| `shell` | `ShellTool` | Dispatcher allowlist — only matched fnmatch patterns are run |
| `read_file` | `ReadFileTool` | Optional `allowed_paths` prefix list |
| `write_file` | `WriteFileTool` | Optional `allowed_paths` prefix list |

`build_tools(cfg)` instantiates tools from `cfg.agent.tools` and wires the `Dispatcher` from `cfg.dispatch`.

### Listener routing (`src/crew_chief/listener.py`)

When `agent.enabled = false` (default): single-command flow — extract one shell command via LLM or `!` prefix, dispatch, reply.

When `agent.enabled = true`: full agent loop — `Agent.run(message_text)` is called; the model may invoke tools across multiple iterations before producing the final reply.

## Coexisting Email Pipelines and Channel Isolation

crew-chief's Gmail channel trusts a sender address, not a dedicated mailbox.  If other automated pipelines also send email to (or from) the same Gmail account, those messages will appear as trusted inbound traffic and trigger crew-chief's agent loop.

**Known coexisting pipeline:** The receipt-intake pipeline sends self-emails (FROM and TO the same Gmail account) with subjects like `[intake] Receipt processed: <merchant> $<amount>`.  This pipeline uses the inbox as a notification channel; its emails must never be processed by crew-chief.

**How to isolate:**

Use `gmail.subject_exclude_patterns` to drop emails from non-crew-chief pipelines before any LLM or dispatch processing:

```toml
[gmail]
subject_exclude_patterns = ["[intake]"]
```

Any message whose subject contains a pattern (case-insensitive substring match) is silently skipped.  Add one entry per pipeline that shares the inbox.

**General rule:** If a new automated pipeline begins sending self-emails to the same Gmail account, add its subject prefix to `subject_exclude_patterns` in `config/listener/config.toml` before enabling crew-chief's Gmail channel.  Failure to do so will cause crew-chief to process the pipeline's notifications as user commands and may trigger a reply loop.

## Security: What Must Never Be Committed

The following are **sensitive identifiers** that must exist only in gitignored local files:

| Sensitive value | Gitignored location | Safe placeholder in `.example` |
|---|---|---|
| KeePass entry paths (`anthropic_api_key_auto_pass_entry`, etc.) | `config/listener/config.toml` | `"your-keepass-entry-path"` |
| Phone numbers (`signal.trusted_senders`, `signal.reply_to`) | `config/listener/config.toml` | `"+15551234567"` |
| Email addresses (`gmail.trusted_senders`, `gmail.reply_to`) | `config/listener/config.toml` | `"you@example.com"` |
| Absolute filesystem paths (`shock_relay_dir`, `config_path`, `auto_pass_env_file`) | `config/listener/config.toml` | `"/path/to/..."` |
| API keys | `config/env` | `# export KEY="sk-..."` |

**Rule**: `.example` and template files are committed to git and therefore public.  They must contain only generic, non-identifying placeholders — never real entry paths, real phone numbers, real email addresses, or real filesystem paths.  Even if a value looks harmless (e.g. a KeePass entry name), it can reveal account structure, service names, or naming conventions that are personal and should not be public.

When in doubt, make the value gitignored.

## Change Guidance

- Keep the Python client dependency-free.  Introduce a dependency only if it is universally available (already in the portfolio's standard Python environment) and the benefit clearly outweighs the friction.
- When adding a new API endpoint wrapper, add matching unit tests in `tests/test_client.py`.
- When changing the container configuration materially (different base image, new env vars, port changes), update the `Containerfile`, `scripts/`, and this `AGENTS.md` in the same change.
- Keep `config/downstream-repos.toml` current: add entries when another repo begins consuming `crew_chief.client`.

## Testing Expectations

All tests are offline — they mock `urllib.request.urlopen` and do not require a running Ollama service.

```bash
# Install and run tests
pip install -e .
pytest -q
```

Pre-commit validation:

```bash
pre-commit run --all-files
```

## Sudo Boundary

Agents will never be able to run `sudo` commands in this environment. If a task requires elevated system changes, make the repo edits and run the validation that can be done without `sudo`, then give the user the exact command(s) to run.

Always require the user to run those commands instead of retrying `sudo`; do not claim a sudo-backed live change was applied until the user shares the result.

## Local CI Verification

Run before every push:

```bash
pre-commit run --all-files
pytest -q
```

Do not push changes that have not passed all checks locally.

## Portfolio Standards Reference

For portfolio-wide repository standards and baseline conventions, consult the control-plane repo at `./util-repos/traction-control` from the portfolio root.

Start with:
- `./util-repos/traction-control/AGENTS.md`
- `./util-repos/traction-control/README.md`
- `./util-repos/traction-control/LESSONSLEARNED.md`

Shared implementation repos available portfolio-wide:
- `./util-repos/archility` for architecture toolchain bootstrap/render orchestration, Graphviz-capable diagram support, deterministic starter scaffolding, agentic architecture authoring, and drift checks
- `./util-repos/auto-pass` for KeePassXC-backed password management and secret retrieval/update flows
- `./util-repos/nordility` for NordVPN-based VPN switching and connection orchestration
- `./util-repos/shock-relay` for external messaging across Signal, Telegram, Twilio SMS, WhatsApp, and Gmail IMAP
- `./util-repos/snowbridge` for SMB-based private file sharing and phone-accessible fileshare workflows
- `./util-repos/dyno-lab` for unified test bench utilities — fixtures, subprocess/HTTP/env mocks, schema validation, smoke scaffolding, and pytest markers/fixtures
- `./util-repos/short-circuit` for WireGuard VPN setup and configuration, establishing private tunnels with SMB, HTTPS, and SSH access
- `./util-repos/clockwork` for declarative cron and systemd scheduler manifest rendering and install helpers
- `./util-repos/tachometer` for manifest-driven local profiling snapshot, run, and summarize workflows
- `./util-repos/crew-chief` (this repo) for local LLM inference via a Podman-hosted Ollama service

## Agent Memory

Use `./LESSONSLEARNED.md` as the tracked durable lessons file for this repo.
Use `./CHATHISTORY.md` as the standard local handoff file for this repo.

- `LESSONSLEARNED.md` is tracked and should capture only reusable lessons.
- `CHATHISTORY.md` is local-only, gitignored, and should capture transient handoff context.
- Read `LESSONSLEARNED.md` and `CHATHISTORY.md` after `AGENTS.md` when resuming work.
- Add durable lessons to `LESSONSLEARNED.md` when they should influence future sessions.
