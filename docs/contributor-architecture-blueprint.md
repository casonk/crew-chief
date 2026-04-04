# Contributor Architecture Blueprint — crew-chief

## Overview

`crew-chief` has two concerns:

1. **Service layer** — a Podman container running Ollama, exposing a REST API on `localhost:11434`.
2. **Client layer** — a stdlib-only Python package (`crew_chief`) that wraps the REST API so portfolio repos can call it with a single import.

## Component diagram

See `docs/diagrams/repo-architecture.puml` and `docs/diagrams/repo-architecture.drawio` for the rendered architecture.

## Execution flow

```
Calling repo
    │
    │  from crew_chief import CrewChiefClient
    │  client = CrewChiefClient()
    │  client.generate("prompt")
    │
    ▼
crew_chief.client (stdlib HTTP)
    │
    │  POST http://localhost:11434/api/generate
    │
    ▼
Podman container (crew-chief)
    │
    │  ollama serve
    │
    ▼
Ollama REST API → model weights (crew-chief-models volume)
```

## Key files

| File | Role |
|---|---|
| `Containerfile` | Podman image — `FROM ollama/ollama:latest`, `EXPOSE 11434`, `ENTRYPOINT ["ollama","serve"]` |
| `src/crew_chief/client.py` | `CrewChiefClient` — `generate`, `chat`, `health`, `list_models` |
| `src/crew_chief/cli.py` | `crew-chief` CLI — `generate`, `health`, `models` subcommands |
| `scripts/start.sh` | Build image (if absent) + create volume + start container |
| `scripts/stop.sh` | Stop container |
| `scripts/status.sh` | Container state + HTTP health probe |
| `scripts/pull_model.sh` | Pull a model into the running service |
| `config/ollama/config.env.example` | Template for Ollama environment overrides |
| `config/downstream-repos.toml` | Tracked inventory of repos consuming this service |

## Boundaries

- **Committed**: `Containerfile`, Python source, scripts, config templates, governance docs.
- **Local-only (gitignored)**: `config/ollama/config.env`, `.tachometer/`, `CHATHISTORY.md`.
- **Runtime-only**: model weights in the `crew-chief-models` Podman volume.

## Extension points

- Add a new API wrapper: implement the method in `client.py`, expose via `cli.py`, add tests.
- Change the model default: update `CREW_CHIEF_MODEL` env var or pass `model=` to the client.
- GPU acceleration: pass `CUDA_VISIBLE_DEVICES` via `config/ollama/config.env` or `podman run -e`.
