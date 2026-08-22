# Changelog

All notable changes to `crew-chief` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `bootstrap.sh` — creates a virtualenv, installs the package in editable mode,
  and verifies the `crew-chief` command runs. Supports `--no-dev`, `--listener`
  and `--venv PATH`.

### Fixed

- The README documented a bare `pip install -e .`, which PEP 668 causes current
  Debian, Ubuntu, Arch and openSUSE to refuse outright. Both the test setup and
  the client-install instructions now go through a virtualenv.

## [0.1.0] — 2026-04-04

### Added

- `Containerfile` — Podman image wrapping `ollama/ollama:latest`, exposing port 11434.
- `src/crew_chief/client.py` — zero-dependency `CrewChiefClient` wrapping `/api/generate`,
  `/api/chat`, `/api/tags`, and health-check endpoints.
- `src/crew_chief/cli.py` — `crew-chief` CLI with `generate`, `health`, and `models` subcommands.
- `scripts/start.sh`, `stop.sh`, `status.sh`, `pull_model.sh` — Podman lifecycle helpers.
- `config/ollama/config.env.example` — Ollama environment variable template.
- `config/downstream-repos.toml` — tracked downstream consumer inventory.
- `tests/test_client.py` — offline unit tests for the Python client (all mocked, no Ollama required).
- Baseline governance files: `AGENTS.md`, `LESSONSLEARNED.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.editorconfig`, `.pre-commit-config.yaml`,
  `.github/workflows/ci.yml`, and GitHub issue/PR templates.
- `docs/contributor-architecture-blueprint.md` and diagram starters.
