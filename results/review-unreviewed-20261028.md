# Review of the unreviewed models 2026-10-28

RTX 3090 (24576 MiB) idle: no other process held GPU memory (15 MiB baseline),
the ECU lease was exclusive, listener and upscaler paused. Ollama, 32768-token
context, one run per prompt. Raw numbers: `bench-idle-20261028.json`
(`scripts/benchmark.py`, prompts latency, reasoning, codegen, summarise).
The `VRAM ΔMB` column in that file reads 0 because the model was already loaded
by its warm-up; GPU memory below is measured separately.

| Model | Tok/s (latency / reasoning / codegen / summarise) | Codegen total | GPU memory (MiB) |
|---|---|---:|---:|
| qwen3:14b-q8_0 | 49.1 / 48.1 / 43.8 / 45.6 | 106 s (4622 tokens, thinking) | 19968 |
| qwen3.5:27b | 34.8 / 34.0 / 32.2 / 32.2 | 168 s (5389 tokens, thinking) | 18752 |
| gemma3:27b-it-qat | 52.5 / 39.8 / 36.7 / 38.0 | 2.5 s (84 tokens) | 21062 |
| qwen2.5-coder:7b | 173.6 / 120.8 / 127.0 / 121.5 | 0.45 s | 6610 |

GPU memory is the increase over the idle baseline after a short request with
`num_ctx` 32768 (`ollama ps` reports 19658, 17408, 17372 and 6302 MiB resident
for the weights and cache it tracks; the nvidia-smi figure is the one a lease
must free).

Decisions:

- `qwen3:14b-q8_0` is 20-25% slower than `qwen3:14b` (63-64 tok/s) at 1.4x the
  memory and nothing in the portfolio names it: retired.
- `qwen3.5:27b` ties across backends (34.9 tok/s on llama.cpp, 2026-10-22) and
  spends thousands of thinking tokens on small tasks: beta on Ollama.
- `gemma3:27b-it-qat` is fastest of the 27B models with no thinking; llama.cpp
  is 13% faster but needs a separate GGUF without the vision weights: beta on
  Ollama.
- `qwen2.5-coder:7b` is used by Clockwork's grocery matching and runs at
  120-174 tok/s: default on Ollama.
- `llama3.2:latest`, `llama3.2:3b-instruct-q8_0` and `aya-expanse:8b` are named
  nowhere in the portfolio: retired.
