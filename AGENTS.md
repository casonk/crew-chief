# AGENTS.md

## Purpose

`crew-chief` is a local LLM service backed by [Ollama](https://ollama.com), containerized with Podman, and exposed via a zero-dependency Python client.  Other portfolio repositories call it for trivial inference tasks (classification, summarization, brief generation) without requiring cloud API access.

The repo ships two things:

1. **Container definition** (`Containerfile`) — builds a Podman image wrapping the upstream `ollama/ollama` image and exposes the REST API on port 11434.
2. **Python client package** (`src/crew_chief/`) — a stdlib-only HTTP wrapper around Ollama's `/api/generate` and `/api/chat` endpoints so any repo can call the service without pulling in extra HTTP libraries.

## Repository Layout

```
crew-chief/
├── Containerfile                          # Podman image definition (FROM ollama/ollama)
├── pyproject.toml                         # Package metadata, ruff/black config, pytest config
├── src/crew_chief/
│   ├── __init__.py                        # Public re-exports, __version__
│   ├── __main__.py                        # python -m crew_chief entry point
│   ├── client.py                          # CrewChiefClient — HTTP client for Ollama
│   └── cli.py                             # crew-chief CLI (generate / health / models)
├── tests/
│   └── test_client.py                     # Offline unit tests (no real service required)
├── scripts/
│   ├── start.sh                           # Build image (if absent) + start container
│   ├── stop.sh                            # Stop running container
│   ├── status.sh                          # Container state + service health check
│   └── pull_model.sh                      # Pull a model into the running service
├── config/
│   ├── ollama/config.env.example          # Ollama env vars template (do not commit config.env)
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

## Architecture Notes

- The container is stateless; model weights are persisted in the named Podman volume `crew-chief-models`.
- The Python client is stdlib-only (`json`, `urllib`) — no third-party dependencies.
- `CrewChiefClient.generate(prompt)` wraps `/api/generate` (single-turn).
- `CrewChiefClient.chat(messages)` wraps `/api/chat` (multi-turn).
- `stream` is always `False`; streaming is not exposed through the current client API.

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
