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

- [ ] [manual:2026-10-21] **Roadmap phase 2: OpenCode frontend.** Add
  `crew-chief code --frontend opencode` against Ollama's OpenAI-compatible
  endpoint and a session-control scanner for OpenCode's session store. See
  `docs/local-inference-roadmap.md`.

- [ ] [manual:2026-10-21] **Roadmap phase 2: Codex `--oss` and OpenRouter.**
  Pull `gpt-oss:20b` and re-test `codex --oss` (a `qwen3:14b` trial made no
  edits). Add OpenRouter as an opt-in metered provider with the key held as a
  secret, for comparing local models with larger open-weight siblings.

- [ ] [manual:2026-10-21] **Roadmap phase 3: llama.cpp and ExLlamaV3 backends.**
  Run `llama-server` (+ `llama-swap`) and TabbyAPI as Podman containers beside
  Ollama, add them to the benchmark, and record tokens/s, TTFT, prefill and
  VRAM per model. Explore prompt-cache reuse, parallel slots, KV-cache
  quantization and speculative decoding. Ship as beta even if gains are small.

- [ ] [manual:2026-10-21] **Grow the task suites, with held-out splits.** Add
  synthetic suites for mail triage, receipt categorization, and schema
  extraction; split each into dev and held-out items, and write baseline rules
  against dev only (the message-routing rules were fitted to all 30 items).

- [ ] [manual:2026-10-21] **Per-task routing in the serving policy.** Add
  `[tasks."<name>"]` entries (model, backend, runner mode, evidence from
  `taskbench`) and have the listener's task chains read them.

- [ ] [manual:2026-10-21] **Jev reference run** (lower priority now that local
  decision models exist). With TypeSafe early access, run
  `taskbench --runner jev` on the synthetic suites only and record it as the
  decision-model reference; key held as a secret, metered.

- [ ] [manual:2026-10-21] **Fine-tune a local decision model.** LoRA-tune a small
  instruct model (or train an encoder classifier) to answer with the option
  token under log-loss, export GGUF, serve with llama.cpp, and compare with
  base models, rules, and Jev on held-out data.

- [ ] [manual:2026-10-22] **Route listener decisions to a decision model.** Clef
  Flash beat the chat models on message-routing at 120 ms per call with
  calibrated probabilities. After a held-out run confirms it, have the listener
  classify incoming messages via `/v1/systemone` and gate low-confidence
  answers to the chat-model path.

- [ ] [manual:2026-10-21] **Roadmap phase 4: 2 x RTX 3090 NVLink plan.** Before
  purchase, benchmark 70B-class 4-bit models on rented dual-GPU capacity;
  after install, compare vLLM/ExLlama tensor parallelism with llama.cpp
  splitting and measure the NVLink benefit.

- [ ] **vLLM inference backend** `[manual:2026-06-17]` — evaluate replacing Ollama with vLLM for higher throughput via paged attention and continuous batching. RTX 3090 24GB is capable. Worth testing on qwen3:14b and qwen3:32b. Primary benefit is concurrent request handling; for serialized personal-assistant use Ollama is sufficient. Benchmark: tokens/sec and TTFT vs Ollama at Q4_K_M. Reference: vllm-project/vllm, `vllm serve <model> --quantization awq`.

## In Progress

## Done
