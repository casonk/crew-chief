# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

- [ ] [manual:2026-10-15] **Ask GitHub Support to purge pre-rewrite commits** — this
  repository's published history was rewritten (most recently on 2026-10-15,
  to remove per-commit AI attribution trailers). GitHub keeps serving the old
  commits to anyone with a hash, and through the read-only `refs/pull/*` refs
  of earlier pull requests, until Support garbage-collects them. The request
  is filed once for the whole portfolio from traction-control's backlog; mark
  this done when an old hash returns 404 here. Never push an old clone's
  history back.

- [ ] [manual:2026-10-21] **Rotate the OpenAI API key used by the Continue CLI.**
  The previous key sat in plain text in `~/.continue/config.yaml` and was
  exposed in an agent session transcript. The config now references
  `${{ secrets.OPENAI_API_KEY }}`, so rotation touches one file: create a new
  key in the OpenAI dashboard, replace the `OPENAI_API_KEY=` line in
  `~/.continue/.env` (mode 600), check it with a free `GET /v1/models`, then
  revoke the old key. See `docs/continue-cli.md`.

- [ ] **vLLM inference backend** `[manual:2026-06-17]` — evaluate replacing Ollama with vLLM for higher throughput via paged attention and continuous batching. RTX 3090 24GB is capable. Worth testing on qwen3:14b and qwen3:32b. Primary benefit is concurrent request handling; for serialized personal-assistant use Ollama is sufficient. Benchmark: tokens/sec and TTFT vs Ollama at Q4_K_M. Reference: vllm-project/vllm, `vllm serve <model> --quantization awq`.

## In Progress

## Done
