# Changelog

All notable changes to `crew-chief` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

- Fix a cancel that was lost: a click on Cancel in the moment between a job being marked running and its process starting set the flag but killed nothing, so the job ran to completion. The worker now checks the flag once the process is registered. This was also the cause of an intermittently failing job-cancel test.
- The Weekly report and the Test bench now share one page base and one in-page report nav (`theme.REPORT_CSS`, `theme.report_nav`), so their tops match: same font, tab size, spacing and heading. They had drifted (14px against 16px text, different tab sizes, different margins). The Test bench is also a whole HTML document now. `scripts/rerender_reports.py --force` rebuilds saved reports with the new chrome.
- Every rendering of a result links to the others: a result saved as `.html`, `.json`, `.md` and `.svg` shows format tabs (the current one marked) in the viewer bar and in the strip under the top bar of an HTML report, so you can switch between them in one click. A `latest.html` link offers the renderings of the report it points to, and a result with a single rendering shows no tabs.
- SVG results open in the themed viewer (`/view/results/<file>.svg`) like Markdown and JSON do: the drawing is shown inline, so its `var(--token)` colours follow the page's theme, with the top bar, a way back, a raw link and, for a chart whose data is in the result store, links to its renderings. The SVG is sanitised first (only shapes and text; scripts, styles, images, foreign content, event handlers and external links are removed). The Results tab and All files link to the viewer; the raw `/files/` URL is unchanged.
- Add a result store (`crew_chief/resultstore.py`): one SQLite file in the interface's state folder, built from the `results/` JSON (taskbench and routebench, rebuildable and imported only when a file changes) as long-format rows, and on-the-fly renderings of it (`crew_chief/render.py`): `GET /render/<run>/<chart>.<format>` gives an accuracy-against-latency scatter or accuracy bars as SVG (themed with `?theme=`, or following the viewer's light/dark setting), and per-performer or per-task tables as CSV, JSON, Markdown or a themed HTML page. The JSON viewer links to a stored result's renderings. See `docs/result-store.md`.
- Markdown and JSON result files open in a themed viewer (`/view/results/<file>`, `crew_chief/viewer.py`, stdlib only) instead of raw text: Markdown renders headings, tables, lists, quotes and code with everything escaped and unsafe link schemes dropped, and JSON is a collapsible tree. Both have the top bar, a way back and a raw link; the file list and the Results tab link to them, and the raw `/files/` and root URLs are unchanged.
- Served report pages and the interface now show one theme control, the one in the top bar (a report's own copy is dropped when it is served), and a strip under the bar links back to Bench home, Weekly report, Test bench and All files in place of the small floating button.
- Route bench accepts several routing models: the New run form lists them as checkboxes (plus free-text specs) and a job runs one `routebench` per router, one after the other. The job spec takes `routers`; the single `router` field still works.
- Add `scripts/rerender_reports.py`: rebuild saved `bench-*` and `test-bench-*` reports from their JSON so they carry the current portfolio theme (`--check` lists the ones that do not). A report embeds the theme from the day it was generated, so older ones ignored theme changes; the tracked `bench-*` reports are re-rendered with it. Nothing is re-measured.
- The bench interface now serves older reports with the current theme: a report generated earlier embedded an old copy of the theme (no rotator, menu or newer themes) that clashed with the top bar, so `latest.html` and `test-bench-latest.html` did not follow the system theme. The embedded copy is swapped for the current one when the page is served, the top bar and home link go after the doctype (a report without `<head>`/`<body>` no longer drops into quirks mode), and "All files" is a themed list with the top bar and a way back instead of a bare list.
- Re-model the `backlog-triage` suite on how Clockwork groups work: one `repo` question over 26 synthetic repositories with uneven descriptions and 24 hard entries (typos, two repositories in one sentence, vague, implied), 185 entries in all, plus three active-sorting variants (`backlog-triage-active-25|50|75.json`) that pass a share of each repository's entries as examples and score the rest. `clef` scores 0.89 and `clef-flash` 0.83 against 0.76 for the keyword rules, and examples in the descriptions did not help. See `results/backlog-triage-v2-20261031.md`.
- Add an optional decision-model gate to the listener (`listener_gate.py`, `[llm] decision_gate`, off by default). The serving policy's `message-routing` task classifies each natural-language message, and one it is confident is a notification or small talk skips the chat-model step. Anything else, or any error, continues through the unchanged extraction, allowlist and dispatcher.
- Answer `/_portfolio/*` itself from a vendored portfolio site seam (`crew_chief/portfolio/`), which replaces the old `theme/` copy, so the theme and top bar work with no Caddy in front: the owner-only site store first, then a pinned fallback copy. Add `/.portfolio` (ignored) and `config/portfolio-site.example.toml`. See traction-control `docs/portfolio-sites.md`.

### Added

- `OllamaProvider(options=...)` sends Ollama runtime options such as `num_ctx` with every `generate` and `chat` request, so callers with long prompts are no longer truncated at the server default.
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
- The bench interface and the report pages it serves load the portfolio top bar
  (`/_portfolio/chrome.js`, served by the shared Caddy).
- The bench interface, `scripts/report.py`, `scripts/test_benchmark.py` and the routebench
  chart use the portfolio system themes (Midnight, Daylight, Ember, High contrast; a
  switcher on every page, following the system by default). Colours live in
  traction-control (`docs/system-theme.md`); `src/crew_chief/theme/` is the vendored copy.
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
