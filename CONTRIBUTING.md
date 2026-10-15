# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running tests

```bash
pytest -q
```

Tests are fully offline — no running Ollama service is required.

## Lint and format

```bash
ruff check --fix .
ruff format .
```

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`.

## Adding a new API endpoint

1. Add the wrapper method to `CrewChiefClient` in `src/crew_chief/client.py`.
2. Add a matching CLI subcommand in `src/crew_chief/cli.py` if the endpoint should be user-facing.
3. Add offline unit tests in `tests/test_client.py`.
4. Update `docs/contributor-architecture-blueprint.md` if the public surface changes materially.

## Portfolio standards

For portfolio-wide conventions see `./util-repos/traction-control/AGENTS.md`.

## AI Contribution Disclosure

Parts of this repository's code, documentation and commit history were drafted
with AI coding assistants, including Claude Code, OpenAI Codex, GitHub Copilot
and Continue. The maintainer directs that work, reviews and tests each change
before it merges, and is responsible for the result.

This section is the repository-wide disclosure. Individual commits, pull
requests and files do not carry per-tool attribution lines.
