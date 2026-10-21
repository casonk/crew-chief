# Local Inference Roadmap

Plan for moving day-to-day coding-agent work onto self-hosted inference.
Each phase ships as a **beta**: usable, documented, and benchmarked, but
allowed to change. A backend or frontend stays in the beta set even when its
gains over the incumbent are marginal; part of the goal is hands-on learning
of caching, parallelism, and multi-GPU tuning.

## Principles

- **Reuse mature agent frontends.** Claude Code, OpenCode and Codex already
  provide tool use, permissions and session history. crew-chief launches them
  against local servers instead of reimplementing an agent UI.
- **Speak the common wire formats.** Ollama and llama.cpp's `llama-server`
  both serve the Anthropic Messages API and the OpenAI API, so a frontend can
  switch backend by changing a base URL.
- **Every session is visible in session-control**, labelled with the backend
  and model it ran on, and resumable on that same backend.
- **Measure, don't assume.** New backends go through the crew-chief benchmark
  on the models actually used before they become a default.
- **Metered cloud APIs stay opt-in.** Keys are referenced as secrets, never
  stored in config files (see [continue-cli.md](continue-cli.md)).

## Phase 1 — `crew-chief code` (beta, shipped)

Claude Code on a local model:

```bash
crew-chief code --list                 # tool-capable models on Ollama
crew-chief code                        # default model (qwen3:14b)
crew-chief code -m qwen3:32b           # pick a model
crew-chief code -- --resume <id>       # reopen a local session
crew-chief code --backend llamacpp --url http://localhost:8080 -m <name>
```

The launcher checks the model is pulled and tool-capable, points every
Claude Code model slot (main, background, subagent) at it, sets the context
window, pins the session ID, and appends the session to
`~/.local/state/crew-chief/code-sessions.jsonl` (mode 600) for
session-control. Inside the session, `/model` aliases resolve to the
launched model; to switch models, exit and relaunch with `-m`.

Known limits: claude.ai connectors are disabled while the local endpoint is
in use; the context window must match what the server actually allocates
(Ollama sizes it from VRAM, 32K on the 3090 today; override with
`--context`).

Follow-up: session-control reads the registry, labels local sessions, and
resumes them through `crew-chief code`.

## Phase 2 — More frontends and providers (beta)

- **OpenCode** as a second frontend (`crew-chief code --frontend opencode`),
  configured against Ollama's OpenAI-compatible endpoint, plus a
  session-control scanner for its session store.
- **Codex `--oss`** with `gpt-oss:20b`, which Codex is tuned for. An initial
  test with `qwen3:14b` produced no edits.
- **OpenRouter** as an opt-in metered provider for open-weight models too
  large to run locally, with the key held as a secret. Useful for comparing
  a local model against its larger sibling before buying hardware.

## Phase 3 — Inference backends (beta)

Run alongside Ollama on separate ports, as Podman containers:

- **llama.cpp `llama-server`** (with `llama-swap` for on-demand model
  switching). Learning targets: prompt-cache reuse across agent turns,
  parallel slots, KV-cache quantization, flash attention, speculative
  decoding with a small draft model.
- **ExLlamaV3 via TabbyAPI**: the likeliest single-user latency win on
  NVIDIA consumer GPUs.
- **vLLM**: continuous batching and tensor parallelism; matters most once
  there are two GPUs or several concurrent agents.

Add each as a benchmark backend and record tokens/s, time to first token,
prefill speed on real agent prompts, and VRAM, per model.

## Phase 4 — 2 × RTX 3090 with NVLink

Target hardware for the current server. 48 GB across two cards opens up
70B-class models at 4-bit and long contexts for 30B-class models.
Compare tensor parallelism (vLLM, ExLlama) against llama.cpp layer/row
splitting, measure the NVLink benefit directly, and set per-card power
limits. A single 4090 remains the alternative if per-token latency matters
more than capacity.

## Phase 5 — Server upgrade and legacy node

Upgrade the current server, then stand up the legacy server as a second
inference node. crew-chief gains a node registry and routes requests by
model and load; session-control federation already aggregates sessions
across machines.

## Phase 6 — Mac home lab (MLX)

Apple Silicon node for the next home lab. Ollama 0.19+ uses MLX on Apple
Silicon, so the same crew-chief stack runs there; `mlx-lm` serves as a
direct comparison. Large unified memory trades per-token speed for
capacity; benchmark prefill on long agent prompts, MLX's weak point.

## Hosted capacity

Before each hardware purchase, rent comparable GPUs by the hour and run the
benchmark on the intended models. This tests whether the larger tier
actually beats the current one on portfolio work.
