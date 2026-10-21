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
| `retired` | Do not serve; remove the pull | no |

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
  `retired` model is refused.
- `crew-chief policy show [model]` prints entries; `crew-chief policy check
  [--live]` validates them and, with `--live`, reports drift against the models
  Ollama has pulled.
- traction-control's portfolio audit runs the live check, so drift shows up in
  the daily audit rather than in a slow session.
- A GPU scheduler can size its reservations from `gpu_mib`.

Evidence reviewed more than 120 days ago is reported as stale.
