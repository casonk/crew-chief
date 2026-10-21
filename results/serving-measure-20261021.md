# llama-server serving measurements 2026-10-21

RTX 3090 (24576 MiB), driver 580.178.04, `ghcr.io/ggml-org/llama.cpp:full-cuda`
build 339f3242c. Other GPU workloads were stopped before each run.
Measured with `scripts/llamacpp_serving_measure.sh`: GPU memory is the server's
increase over the idle baseline after load; generation is llama-server's
reported rate for a 200-token reply. Flash attention on, all layers on GPU.

| Model | Context | KV cache | GPU memory (MiB) | Generation (tok/s) |
|---|---:|---|---:|---:|
| qwen3:32b | 32768 | q8_0 | 23740 | 29.7 |
| qwen3:32b | 16384 | q8_0 | 21538 | 29.2 |
| qwen3:32b | 32768 | q4_0 | 21692 | 29.3 |
| qwen3:14b | 32768 | f16 | 14024 | 64.4 |

Same day under Ollama defaults (`bench-idle-20261021.json`): qwen3:32b
7.1 tok/s with 17% of the model on the CPU; qwen3:14b 62.6–63.7 tok/s.
