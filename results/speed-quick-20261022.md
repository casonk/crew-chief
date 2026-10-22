# Quick speed check: 27B candidates and qwen3:14b-q8_0 (2026-10-22)

RTX 3090 (24576 MiB), Ollama 0.40.8, `ghcr.io/ggml-org/llama.cpp:full-cuda`
build 339f3242c. Run under an exclusive GPU lease (listener, Ollama and the
upscaler yielded). Quick settings: llama-bench `-ngl 99 -p 512 -n 128 -fa 1 -r 2`;
`scripts/benchmark.py --prompts latency codegen --runs 2` on Ollama defaults.

| Model | Ollama gen (tok/s) | On GPU | Codegen reply | llama.cpp gen (tok/s) | llama.cpp pp512 (tok/s) |
|---|---:|---|---|---:|---:|
| qwen3.5:27b | 31.7 | 100% (18 GB) | 5942 tokens, 200 s (thinking) | load failed | — |
| gemma3:27b-it-qat | 36.2 | 100% (18 GB) | 85 tokens, 2.5 s | load failed | — |
| qwen3:14b-q8_0 | 44.1 (latency prompt) | 100% | timed out at 600 s (thinking) | 49.1 | 2670 |

Ollama generation rates are from the codegen prompt except where noted; the
one-word latency prompt is too short to rate.

## Findings

- Both 27B models fit entirely on the GPU under Ollama, unlike `qwen3:32b`
  (17% on the CPU, 7.1 tok/s). At 32–36 tok/s they are slightly faster than
  `qwen3:32b` on llama.cpp (29.7 tok/s), with no separate server.
- llama.cpp cannot load Ollama's files for either 27B model:
  - `gemma3:27b-it-qat`: "wrong number of tensors; expected 1247, got 808".
    Ollama keeps the vision weights inside the one file; llama.cpp expects
    them in a separate projector file.
  - `qwen3.5:27b`: "qwen35.rope.dimension_sections has wrong array length;
    expected 4, got 3". Ollama's metadata for this new architecture differs
    from llama.cpp's.
  A llama.cpp comparison needs llama.cpp-native GGUF downloads of these models.
- `qwen3.5:27b` thinks at length: about 6,000 tokens for a short function.
  Its speed is fine; for interactive use it needs thinking limited or off.
- `qwen3:14b-q8_0` runs at 44–49 tok/s against 63–64 for the default
  `qwen3:14b` (Q4_K_M), about a quarter slower, and its codegen run did not
  finish within 600 s. The 6 GB of extra precision has not shown a benefit yet.

## Warm-tier benchmarks (retired models, read in place from the SATA SSD)

`crew-chief storage bench-due`, same quick llama-bench settings:

| Model | gen (tok/s) | pp512 (tok/s) |
|---|---:|---:|
| codellama:latest | 66.8* | 3293 |
| deepseek-coder:6.7b | 158.5 | 4452 |
| mistral:latest | 130.6 | 4275 |

\* Contended: the lease started while Ollama was still unloading qwen3:14b
(13282 of 24576 MiB free), so this number is low. It is re-measured on the
model's next warm-tier run. Benchmarking from the SATA SSD changes load time
only; generation runs from GPU memory.
