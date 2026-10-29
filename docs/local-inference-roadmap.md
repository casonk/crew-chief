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
crew-chief --url http://localhost:8081 code --backend llamacpp -m <alias>
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

### Step 1: raw llama.cpp numbers (`llama-bench`)

`scripts/llamacpp_bench.sh` runs llama.cpp's own `llama-bench` in the
official CUDA image, reading the GGUF blobs Ollama already pulled, so no
model is downloaded twice. Default sweep: prompt processing at 512 and 4096
tokens, 128-token generation, flash attention off and on, 3 repetitions.

```bash
podman pull ghcr.io/ggml-org/llama.cpp:full-cuda
systemctl --user stop crew-chief-listener clockwork-upscale   # keep the GPU to itself
podman exec crew-chief ollama ps                   # then `ollama stop <model>` for each
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv   # expect none
bash scripts/llamacpp_bench.sh llama3.1:8b qwen3:14b qwen3:32b
bash scripts/llamacpp_bench.sh qwen3:14b -- -ngl 99 -p 4096 -n 128 -fa 1 -ctk q8_0 -ctv q8_0
systemctl --user start crew-chief-listener clockwork-upscale
```

The script warns when other processes hold the GPU and exits non-zero if
a model fails to load. Results land in
`results/llamacpp-bench-<timestamp>.{md,jsonl}`. Compare
generation (`tg`) with the Ollama benchmark for the same model; `pp`
(prompt processing) matters most for agents, whose first turn alone is
about 12K tokens of Claude Code system prompt.

First run (2026-10-21) findings:

- `qwen3:32b` does not fit Ollama's defaults on one 3090. With a 32K
  context and an f16 KV cache (8 GiB), Ollama placed 3.6 GiB of weights and
  1.1 GiB of KV cache on the CPU, which is why the weekly benchmark shows it
  at ~7 tok/s. A q8_0 KV cache (`-ctk q8_0 -ctv q8_0`, or
  `OLLAMA_KV_CACHE_TYPE=q8_0` with flash attention in Ollama) halves the
  cache and should keep the whole model on the GPU.
- Flash attention raised `llama3.1:8b` prompt processing at 4096 tokens from
  ~3.0K to ~4.1K tok/s.
- A long-running GPU job (clockwork's Real-ESRGAN upscaler) skewed the
  first `qwen3:14b` rows and left too little VRAM for `qwen3:32b`. Clean
  runs need an idle GPU: stop other GPU services, or hold an exclusive GPU
  lease, for the duration of the run.

Idle-GPU comparison, same day (generation tok/s; llama.cpp `tg128` with flash
attention, Ollama `scripts/benchmark.py` short prompts):

| Model | llama.cpp | Ollama | Note |
|---|---:|---:|---|
| llama3.1:8b | 125 | 142–188 | Ollama ahead on short outputs; not yet a like-for-like test |
| qwen3:14b | 64.5 | 62.6–63.7 | Equal |
| qwen3:32b | 27.5 | 7.1 | Ollama runs 17% of it on the CPU at a 32K f16 context |

The 32b gap is placement, not engine speed: fitting the model fully on the
GPU (q8_0 KV cache, or a shorter context) is the fix in either server.

### Step 2: serve a model and drive it with `crew-chief code`

```bash
BLOB=$(python3 -c "import json;print(next(l['digest'] for l in json.load(open('$(podman volume inspect crew-chief-models --format '{{.Mountpoint}}')/models/manifests/registry.ollama.ai/library/qwen3/14b'))['layers'] if l['mediaType'].endswith('.model')).replace(':','-'))")
# GPU flags: see scripts/llamacpp_bench.sh
podman run -d --name llamacpp --rm <gpu flags> \
  -e LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/cuda/lib64 \
  -v "$(podman volume inspect crew-chief-models --format '{{.Mountpoint}}')/models/blobs:/models:ro" \
  -p 127.0.0.1:8081:8080 --entrypoint /app/llama-server ghcr.io/ggml-org/llama.cpp:full-cuda \
  -m /models/$BLOB --alias qwen3:14b --jinja -ngl 99 -c 32768 -fa on --host 0.0.0.0 --port 8080
crew-chief --url http://localhost:8081 code --backend llamacpp -m qwen3:14b
```

`--jinja` is required for tool calling. Port 8080 is taken on the current
server, hence 8081. First trial (2026-10-21, qwen3:14b Q4_K_M, RTX 3090):
the agent loop worked and llama-server reused its prompt cache across
turns (12.1K-token first prefill at ~1.9K tok/s, later turns 1.5–3.2K
tokens), generating at ~55 tok/s. The model fixed the seeded bug but pasted
the `Read` tool's line-number prefixes into the file, a model-quality
failure to track in the coding benchmark.

### Step 3: serving features (`scripts/serving_features.py`)

Starts a fresh `llama-server` per configuration on an idle GPU and measures one
feature at a time (raw completions, temperature 0, flash attention on):

```bash
ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
  --priority batch --max-wait 2h -- python3 scripts/serving_features.py [kv cache slots spec]
```

First run (2026-10-29, `qwen3:14b` Q4_K_M, RTX 3090,
`results/serving-features-20261029-080146.md`):

- **Prompt-cache reuse is the big win for agents.** Four turns over a shared
  6K-token prefix: with `cache_prompt` a later turn evaluates 10 tokens and
  takes 0.55 s; without, it re-evaluates 4.9K tokens and takes 2.7 s. `crew-chief
  serve` and `code` already send `cache_prompt`; keep one slot per agent so the
  cache is not evicted.
- **Parallel slots** trade latency for throughput. Four concurrent requests:
  `-np 4` gives 124 tok/s aggregate (37 each) against 56 tok/s at `-np 1`,
  for 3.8 GiB more GPU memory (the context is split across slots). Use it
  only for concurrent agents or batch jobs; a single agent wants `-np 1`.
- **KV-cache quantization** costs 2% of generation speed for q8_0 and 3% for
  q4_0, and saves 0.6 GiB / 0.9 GiB at an 8K context (more at longer
  contexts). q8_0 is the default for models that need the room, as in the
  serving policy.
- **Speculative decoding** depends on the text. With `llama3.1:8b` (already
  117 tok/s), a `llama3.2` 3B draft model *slowed* generation (prose 60 tok/s,
  structured 113) because the draft's cost is not repaid by a fast target; it
  would pay off on the 32B-class models, not yet measured. The draft-free
  `--spec-type ngram-mod` is the useful one: no change on prose (23% of drafted
  tokens accepted), but 5× on repetitive structured output (586 vs 117 tok/s,
  95% accepted). That fits JSON extraction, schema-shaped replies and
  edit-heavy code, so it is worth enabling for those tasks.

Draft-model trial on a 32B-class target (2026-10-29, `qwen3:32b` Q4_K_M at
29 tok/s, draft `Qwen3-0.6B-Q8_0.gguf`, same tokenizer family; sha256
`9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031`,
`results/serving-features-20261029-083933.md`; pass it as
`--draft ~/.local/share/crew-chief/gguf/Qwen3-0.6B-Q8_0.gguf`):

| Setting | Prose tok/s | Structured tok/s |
|---|---:|---:|
| no draft | 29.4 | 29.4 |
| `ngram-mod` | 29.3 | 43.7 |
| draft, max 8 tokens | 29.9 (17% accepted) | **70.0** (57% accepted) |
| draft, max 16 tokens | 23.6 | 66.9 |

A draft pays off when the target is slow: the same technique slowed the 8B
target above. On 32B, an 8-token draft is neutral on prose and 2.4x on
structured output, so it is the setting to try for a 32B entry that serves
extraction or code edits. Longer drafts lose on prose (rejections cost more
than they save). The draft adds 1.5 GiB of GPU memory (21,398 to 22,938 MiB at an 8K context), which
matters for a 32B entry that already fills the card.

Flag names changed in the current llama.cpp image (`--draft-max` became
`--spec-draft-n-max`; `--spec-type draft-simple` is required for a draft
model).

## Decision models (beta, alongside phase 3)

Many workloads are bounded decisions, not generation. `crew-chief taskbench`
scores models on task suites in the Jev question format (choice, score,
yes/no), with runners for rules, Ollama, llama.cpp (constrained single-token
answers with probabilities), local decision models on Ollama's
`/v1/systemone` (Clef, Nimble, Tev1), and TypeSafe's hosted Jev as a
reference. First pick: Clef Flash (120 ms per decision set, best calibration).
Next:
held-out task data, a locally fine-tuned decision model, and per-task
routing in the serving policy. See [task-benchmarks.md](task-benchmarks.md).

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
