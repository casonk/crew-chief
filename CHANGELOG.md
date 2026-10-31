# Changelog

All notable changes to `crew-chief` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Seven synthetic Clockwork list-sorting suites for `crew-chief taskbench`
  (`benchmarks/decisions/clockwork-*.json`), each with dev and held-out items.
- `taskbench` states every allowed value before the input, reports a confusion
  matrix and macro-F1 per runner and question, and records latency per item.
- `crew-chief routebench` compares single models, a profile lookup, a router
  model, confidence cascades and an oracle on accuracy, macro-F1 and time to
  inference. See `docs/decision-model-selection.md`.
- Scoring profiles (`config/scoring-profiles.toml`, `crew_chief.scoring`): one
  accuracy-and-latency score per use case with hard gates, tie margins and a
  weight sensitivity table, added to `taskbench` and `routebench` reports.
  Speed credit blends an absolute latency curve with one normalised against every
  performer in the same report (`relative_weight`).
- The bench interface uses the portfolio (Clockwork) dark palette.
- Report pages served by `benchui` (latest.html, test-bench-latest.html, ...) carry a link back to the interface.
- `crew-chief benchui`: a web interface (loopback listener, reached through the shared
  Caddy at bench.crew-chief.internal; user unit via `scripts/install_benchui_systemd.sh`) with profile sliders and a
  live ranking, a form that starts `taskbench` and `routebench` jobs, a one-at-a-time
  job queue with status, logs and cancel, and results linked to the jobs that wrote
  them.

### Fixed

- The weekly benchmark (`scripts/run_benchmark.sh`) now runs under an exclusive
  ECU lease. Without one it shared the GPU with other jobs, recorded first-token
  times of 5-7 minutes and hit the unit's 2 hour limit on 2026-10-25.

### Added

- Serving-policy keys `draft` and `draft_tokens` for draft-model speculative
  decoding; `config/gguf-sources.toml` gains `draft = true` sources and lists
  Qwen3-0.6B. The engine matrix skips draft-only sources.
- `crew-chief serve --swap MODEL...` fronts several policy-served models with
  llama-swap, one endpoint that swaps models on demand.
- `scripts/serving_features.py --draft` accepts a GGUF path; a Qwen3-0.6B draft
  trial on `qwen3:32b` is recorded in the roadmap.
- Serving-policy key `speculative = "ngram-mod"` for `llamacpp` entries;
  `crew-chief serve` passes it as `--spec-type ngram-mod`.
- `scripts/serving_features.py` measures llama-server's prompt-cache reuse,
  parallel slots, KV-cache type and speculative decoding on an idle GPU;
  first results and findings in `docs/local-inference-roadmap.md`.
- `taskbench` runner `systemone:<model>` for local decision models on Ollama's
  `/v1/systemone` endpoint (Clef, Nimble, Tev1). Serving-policy entries and
  evidence for clef-flash, nimble, and tev1. Decision tasks move to
  `benchmarks/decisions/`, leaving `benchmarks/tasks/` to the test benchmark.
- `crew-chief taskbench` — task-based decision benchmarks in the Jev question
  format (choice, score, yes/no) with runners for keyword rules, Ollama
  (JSON-schema output), llama.cpp (single-token answers with probabilities),
  and TypeSafe's hosted Jev. Scores accuracy, invalid answers, latency, and
  Brier calibration. First suite: `benchmarks/decisions/message-routing.json`.
- Serving policy (`config/serving-policy.toml`, `docs/serving-policy.md`): a
  reviewed, evidence-backed backend and configuration per model.
  `crew-chief policy show|check [--live]` validates it and reports drift;
  `crew-chief code` now takes backend, URL, and context from it and refuses
  retired models. `scripts/llamacpp_serving_measure.sh` records a serving
  configuration's GPU memory and generation rate as evidence.
- `scripts/llamacpp_bench.sh` — runs llama.cpp's `llama-bench` (official CUDA
  image, rootless Podman) on the GGUF blobs already pulled into Ollama, and
  saves Markdown and JSONL results. Roadmap phase 3, step 1.
- `crew-chief code` (beta) — launches Claude Code against a local Ollama or
  llama-server endpoint, checks the model supports tool calling, and records
  each session in `~/.local/state/crew-chief/code-sessions.jsonl` for
  session-control. Roadmap in `docs/local-inference-roadmap.md`.
- `cwd` option for `ClaudeCliProvider` and `CodexCliProvider`, so callers can run
  the CLI agent in an empty directory instead of their own working tree.
- `bootstrap.sh` — creates a virtualenv, installs the package in editable mode,
  and verifies the `crew-chief` command runs. Supports `--no-dev`, `--listener`
  and `--venv PATH`.
- `docs/continue-cli.md` and `config/continue/config.yaml.example` — setup for
  running the Continue CLI (`cn`) against the local models, with cloud API keys
  kept out of the config via `${{ secrets.* }}`.

### Changed

- The Ollama image is rebuilt on Ollama 0.40.8 (from 0.20.2), which adds the
  decision-model endpoint and cut per-call overhead on small decisions from
  ~1.1 s to ~0.4 s.

### Fixed

- `crew-chief policy check --live` treated `nimble` and `nimble:latest` as
  different models; untagged names now mean `:latest`, as in Ollama.

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
