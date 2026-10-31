# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

- [ ] [manual:2026-10-31] **Re-model the backlog-triage suite on how groups really work.** In Clockwork's To Code
  list a group is a function of the repository, so replace the `group` question with a repository question over
  a realistic number of repositories (25-30, uneven descriptions, case variants of one name), keep `unknown`
  items, and add a separate variant that passes a share of the active sorting as examples (0, 25, 50, 100
  percent), scored on the items not passed. Never mix the examples into the plain suites. See
  `docs/decision-model-selection.md`.

- [ ] [manual:2026-10-31] **Make the backlog-triage suite harder.** The keyword baseline beats every model on it
  (0.97 group, 0.82 repo) because the entries share vocabulary. Add entries with typos, two repositories in one
  sentence, vague wording and entries that name no repository, then re-run the four decision models and report
  whether a model beats the keyword rules. See `docs/decision-model-selection.md`.

- [ ] [manual:2026-10-30] **Grow the Clockwork sorting suites and repeat the runs.**
  The held-out split has 88 items across seven suites, so differences of a few
  points are single items, and a repeated run moved some scores by up to 5
  points. Add held-out items until each suite has at least 30, run each
  configuration three times, and report the spread. See
  `docs/decision-model-selection.md`.

- [ ] [manual:2026-10-30] **Try selection with a chat-model tier.** The 2026-10-30
  router run found nothing to choose between four similar System One models. Add
  `ollama:qwen3:14b` and `ollama:qwen3:32b` as `routebench` candidates and test
  whether a cascade (`tev1` first, escalate on low confidence) buys accuracy that
  is worth the added latency; also try `tev1` as the router.

- [ ] [manual:2026-10-30] **Record the Clockwork categorize task in the serving
  policy.** Add a `[tasks."clockwork-categorize"]` entry (`systemone`,
  `clef-flash`) citing `results/taskbench-clockwork-sorting-20261030.md` once the
  held-out set above is large enough to support a `beta` status. Clockwork's
  `_ai_categorize` calls Ollama's chat endpoint today; switching it is a change in
  the Clockwork repository.

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

- [ ] [manual:2026-10-21] **Roadmap phase 3: remaining backends.** `llama-server`
  is served per policy (`crew-chief serve`) and its prompt cache, parallel
  slots, KV quantization and speculative decoding are measured
  (`scripts/serving_features.py`). Left: a systemd unit for `serve --swap`, a `qwen3:32b` entry at a shorter context that fits the 0.6B draft (2.4x on structured output; measure first), an `ngram-mod`
  measurement on the model that serves structured tasks (the policy key
  exists), and the ExLlamaV3 / TabbyAPI container
  with the same benchmark. Ship as beta even if gains are small.

- [ ] [manual:2026-10-21] **Jev reference run** (lower priority now that local
  decision models exist). With TypeSafe early access, run
  `taskbench --runner jev` on the synthetic suites only and record it as the
  decision-model reference; key held as a secret, metered.

- [ ] [manual:2026-10-21] **Fine-tune a local decision model.** LoRA-tune a small
  instruct model (or train an encoder classifier) to answer with the option
  token under log-loss, export GGUF, serve with llama.cpp, and compare with
  base models, rules, and Jev on held-out data.

- [ ] [manual:2026-10-22] **Enable the listener decision gate.** The gate is
  built (`listener_gate.py`, `[llm] decision_gate`, off by default): the
  `message-routing` decision model drops messages it is at least 80% sure are
  notifications or small talk, and everything else takes the existing path.
  Clef Flash beat the chat models on message-routing at 120 ms per call, but the
  2026-10-29 held-out run (10 items) did not separate `clef-flash` from
  `nimble`. Grow the held-out set, check how often the gate would have dropped a
  real command in the listener's own logs, then turn it on in the live config.

- [ ] [manual:2026-10-21] **Roadmap phase 4: 2 x RTX 3090 NVLink plan.** Before
  purchase, benchmark 70B-class 4-bit models on rented dual-GPU capacity;
  after install, compare vLLM/ExLlama tensor parallelism with llama.cpp
  splitting and measure the NVLink benefit.

- [ ] **vLLM inference backend** `[manual:2026-06-17]` — evaluate replacing Ollama with vLLM for higher throughput via paged attention and continuous batching. RTX 3090 24GB is capable. Worth testing on qwen3:14b and qwen3:32b. Primary benefit is concurrent request handling; for serialized personal-assistant use Ollama is sufficient. Benchmark: tokens/sec and TTFT vs Ollama at Q4_K_M. Reference: vllm-project/vllm, `vllm serve <model> --quantization awq`.

## In Progress

## Done
