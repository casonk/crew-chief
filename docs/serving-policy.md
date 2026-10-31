# Serving Policy

`config/serving-policy.toml` records, for every model pulled into Ollama,
which backend serves it and how: context window, KV-cache type, flash
attention, the GPU memory that configuration needs, a status, and the
benchmark evidence behind the decision.

Which engine is faster depends on the model and on whether it fits on the
GPU. On 2026-10-21, `qwen3:14b` ran equally on Ollama and llama.cpp, while
`qwen3:32b` ran four times faster on llama.cpp, because Ollama's defaults left
part of it on the CPU. The policy turns those measurements into a reviewed
per-model decision instead of a per-session guess.

## Statuses

| Status | Meaning | Needs evidence |
|---|---|---|
| `default` | Reviewed, preferred configuration | yes |
| `beta` | Reviewed, being trialled; may change | yes |
| `unreviewed` | Pulled; served on Ollama defaults | no |
| `retired` | Kept for occasional use; rotates down slower storage | no |

`llamacpp` entries may set `speculative = "ngram-mod"`, which `crew-chief serve`
passes as `--spec-type ngram-mod`: draft-free speculative decoding that was 5x
faster on repetitive structured output and neutral on prose
(`results/serving-features-20261029-080146.md`). Enable it only on an entry
whose evidence covers that model.

`llamacpp` entries may instead set `draft = "<name in gguf-sources.toml>"` (with
`draft_tokens`, default 8) for draft-model speculative decoding. `crew-chief gguf
fetch <draft>` downloads and verifies the file; `serve` mounts it and passes
`-md`, `--spec-type draft-simple` and the draft length. `draft` and `speculative`
are mutually exclusive. A draft was 2.4x faster on structured output for
`qwen3:32b` at 8 draft tokens and costs about 1.5 GiB, so `qwen3:32b` at its
current 32K context (23.7 GiB) has no room for one: a draft entry needs a
shorter context, measured on an idle GPU before it is enabled.

`llamacpp` entries must also give `context` and `gpu_mib`, because the server
is started with exactly that configuration.

## Roles

An entry may carry `role = "coding" | "workhorse" | "system1"`. It does not change how the model is served;
it groups models in the bench interface's New run form (All, Coding, Workhorse, System 1) so a benchmark
can pick a whole category at once. Without a `role` the name decides: a System One model is `system1`, a name
with `code` in it (`qwen2.5-coder`, `codellama`, `deepseek-coder`) is `coding`, anything else is `workhorse`.
Set a `role` where the guess is wrong (for example a general model that is mostly used for code).

## Changing an entry

1. Measure on an idle GPU (stop other GPU services first). `llamacpp_bench.sh`
   takes the exclusive ECU lease itself when `ecu` is on PATH
   (`CREW_CHIEF_NO_LEASE=1` skips that); the other scripts still need the explicit
   `ecu run` shown:
   ```bash
   ecu run --gpu exclusive --own-gpu-process llama-server --cpu-cores 2 \
     --priority batch --max-wait 2h -- python3 scripts/engine_matrix.py <model>
   bash scripts/llamacpp_bench.sh <model>
   bash scripts/llamacpp_serving_measure.sh <model> <context> <kv-type>
   python3 scripts/benchmark.py <model> --json results/bench-idle-<date>.json
   ```
2. Commit the results under `results/` and update the entry: backend,
   settings, `gpu_mib` from the measurement, `evidence` paths, `reviewed`
   date, and a one-line `note` with the deciding numbers.
3. Run `crew-chief policy check --live` and open a pull request.

Pulling a new model requires adding at least an `unreviewed` entry; the check
fails otherwise.

## Engine matrix

Quick checks with different tools disagree: llama-bench measures an empty
context, Ollama replies vary in length, and thinking models produce thousands
of extra tokens. `scripts/engine_matrix.py` removes those differences. Each
model runs three ways with identical settings:

| Engine | File |
|---|---|
| Ollama | the blob Ollama pulled |
| llama.cpp (`llama-server`) | the same blob |
| llama.cpp (`llama-server`) | the llama.cpp-native file of the same weights and quantization |

All three get the same raw-text prompt (no chat template, so thinking does not
change the work), reply length, context, batch sizes (Ollama's 512/512) and
flash-attention setting, one warm-up and three timed runs. Comparing rows 1
and 2 isolates the engine; rows 2 and 3 isolate the file. Ollama 0.40 itself
runs `llama-server` underneath, so a large gap points at settings or at the
file, not the engine.

The native files are listed in `config/gguf-sources.toml` with their SHA-256;
`crew-chief gguf fetch` downloads and verifies them (`crew-chief gguf list`
shows what is present). A model on warm or cold storage gets its native file
in that tier's `gguf/` directory.

## Serving a model

`crew-chief serve <model>` starts the backend the entry names. For `llamacpp`
entries it runs `llama-server` in Podman with the entry's context window, KV-cache
type and flash attention, and stops it when interrupted. The container runs under
an `ecu run` lease sized from `gpu_mib` plus 1024 MiB of headroom (loading
allocates compute buffers beyond the loaded-model figure), or the whole GPU when
that does not fit. A model that needs more than is free still fails to load when a
registered live activity holds GPU memory; the server's out-of-memory message and
the lease's note naming the holder say so. Ollama entries need nothing started.
`--dry-run` prints the command and `--no-lease` skips the lease.

## Per-task routing

`[tasks."<name>"]` entries say which model answers a named task, from
`crew-chief taskbench` evidence: `model`, `runner` (`chat`, or `systemone` for a
decision model behind `/v1/systemone`), optional `fallback` models, `status`
(`default`, `beta`, `unreviewed`), `evidence` and `reviewed`. `policy check`
requires evidence and a date for `default` and `beta` tasks and errors on a model
that is missing from the policy or retired. `crew-chief policy show --task [name]`
prints them.

A `chat` task gives the listener its Ollama model chain (the model, then the
fallbacks). The listener's own `[llm.task_chains]` entry for the same task wins,
then the policy, then `default` and `ollama_model_chain`. A `systemone` task names a
decision model: the listener asks `message-routing` when `[llm] decision_gate = true`
(see `listener_gate.py`), trying the model and then its fallbacks, and drops only
messages the model is confident are notifications or small talk.

## Who reads it

- `crew-chief serve --swap <model> [<model> ...]` runs llama-swap
  (`ghcr.io/mostlygeek/llama-swap:cuda`, override with `LLAMA_SWAP_IMAGE`) in
  front of several models on `127.0.0.1:8085` (`--port`). It writes a config that
  gives each model its policy flags, loads the model a request names, stops the
  previous one, and unloads an idle model after `--ttl` seconds (default 300).
  Any OpenAI-compatible client selects a model with the usual `model` field. The
  lease is sized for the largest model, since one runs at a time. Measured
  2026-10-29 on one RTX 3090 with `qwen3:14b`, `qwen2.5-coder:7b` and `qwen3:32b`:
  a request to the loaded model answers in 0.2 s, and a swap takes 6-13 s (the
  32B takes longest); GPU memory matched each entry's `gpu_mib`.
- `crew-chief code -m <model>` takes the backend, server URL, and context from
  the entry. `--backend`, `--url`, and `--context` override it with a note; a
  `retired` model is served with a note that its first load is slower.
- `crew-chief policy show [model]` prints entries; `crew-chief policy check
  [--live]` validates them and, with `--live`, reports drift against the models
  Ollama has pulled.
- traction-control's portfolio audit runs the live check, so drift shows up in
  the daily audit rather than in a slow session.
- A GPU scheduler can size its reservations from `gpu_mib`.

Evidence reviewed more than 120 days ago is reported as stale.

## Storage rotation

Retiring a model does not delete it straight away. It moves down cheaper
storage, is benchmarked less often at each step, and is deleted only at the
bottom. Until then it stays usable from Ollama, `cn` and `crew-chief code`;
only its first load is slower. A large catalogue then costs little: the strongest models stay on fast
storage and are measured weekly, the weakest drift down and are measured rarely.

| Tier | Storage | Benchmarked | Stays |
|---|---|---|---|
| hot | Ollama volume (M.2) | every 7 days (weekly timer) | while not retired |
| warm | SATA SSD | every 30 days | 90 days, then to cold |
| cold | Hard disk | every 90 days | 180 days, then deleted |

The rules are `[rotation]` in the policy; change them in a pull request like
any other entry. Tier paths are host-specific, so they live in
`~/.config/crew-chief/storage.toml` (template: `config/storage.toml.example`).

```bash
crew-chief storage status        # tier, time in tier, bench cadence per model
crew-chief storage plan          # moves and deletions now due
crew-chief storage apply         # do the moves (deletion also needs --delete)
crew-chief storage restore <m>   # bring a model back to hot storage
crew-chief storage bench-due     # llama.cpp benchmark of warm/cold models due one
```

- A model below hot keeps a stub in the Ollama volume: a copy of its manifest
  and links to its blobs in the tier. `scripts/run_ollama.sh` mounts the tiers
  read-only at the same paths, so Ollama lists and loads it from there. Ollama
  0.40 rejects a linked manifest, which is why the manifest is a copy. Blobs a
  model still on hot storage shares stay real files.
- Load times (generation is unaffected once loaded): roughly 4 GB in 8 s from
  the SATA SSD and 20 s from the hard disk; 20 GB in 40 s and 2 minutes.
- `storage apply` first repairs: it gives every model below hot a stub and
  finishes any interrupted move. `storage status` marks a model without a
  stub as NOT LINKED.
- `policy check --live` treats stubs of retired models as expected, and warns
  when a model that is no longer retired still lives below hot.
- Every tier uses Ollama's own directory layout, so warm and cold models are
  benchmarked in place by `scripts/llamacpp_bench.sh` (`CREW_CHIEF_MODELS_DIR`)
  without being copied back.
- Moves copy first and remove the source last, so an interrupted move leaves
  the model whole in at least one tier. Blobs shared with a model that stays
  are copied, not moved.
- Which tier holds a model is read from disk; when it arrived and when it was
  last benchmarked are kept in `~/.local/state/crew-chief/model-storage.json`.
- `scripts/run_benchmark.sh` (the weekly timer) re-runs itself under an exclusive
  ECU lease when `ecu` is installed (`CREW_CHIEF_NO_LEASE=1` skips it), so the
  numbers are taken on an idle GPU; it then runs `storage bench-due` after the
  hot-tier benchmark once storage tiers are configured.
- A model taken back out of retirement (`beta` or `default` again) is reported
  by `storage plan` until it is restored to hot storage.
- Models Ollama cannot hand to llama.cpp (some multimodal or very new
  architectures) fail `bench-due` and are retried on the next run.
