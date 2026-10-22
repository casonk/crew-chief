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

`llamacpp` entries must also give `context` and `gpu_mib`, because the server
is started with exactly that configuration.

## Changing an entry

1. Measure on an idle GPU (stop other GPU services first):
   ```bash
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

## Who reads it

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
- `scripts/run_benchmark.sh` (the weekly timer) runs `storage bench-due` after
  the hot-tier benchmark once storage tiers are configured.
- A model taken back out of retirement (`beta` or `default` again) is reported
  by `storage plan` until it is restored to hot storage.
- Models Ollama cannot hand to llama.cpp (some multimodal or very new
  architectures) fail `bench-due` and are retried on the next run.
