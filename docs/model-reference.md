# Model Reference

Reference for Ollama model selection, quantization formats, and VRAM planning
on the crew-chief RTX 3090 deployment (24 GB VRAM).

---

## Quantization Formats

| Format | Bits/weight | Perplexity loss vs F16 | Typical use |
|---|---|---|---|
| **Q4_K_M** | 4-bit grouped + mixed precision | ~0.8–1.5 % | Portfolio default. Best balance of quality, VRAM, and speed. Ships as the Ollama default. |
| **QAT** | 4-bit, quantization-aware trained | ~0.3–0.5 % | Model trained with its own quantization applied; better quality than post-training Q4_K_M for the same VRAM. Only available for select models (e.g. Gemma3). |
| **Q8_0** | 8-bit uniform | ~0.05 % | Near-fp16 quality; 2× VRAM of Q4_K_M. Use when a model fits and quality matters more than VRAM headroom. |
| **F16** | 16-bit half precision | 0 % (reference) | Full quality; 4× VRAM of Q4_K_M. Only feasible for ≤8B models on 24 GB. |
| Q4_0 | 4-bit, no channel scale | ~2–4 % | Older format, lower quality. Avoid for new pulls; exists only in legacy checkpoints. |
| Q5_K_M | 5-bit grouped + mixed precision | ~0.3–0.6 % | Not available in the official `qwen3` or `llama3.2` library tags as of 2026-06. Use Q8_0 for a quality bump instead. |

---

## VRAM Estimates by Model Size

KV-cache adds ~1–2 GB depending on context length; leave that headroom.

| Model params | Q4_K_M | Q8_0 | F16 | Fits in 24 GB (Q4_K_M) |
|---|---|---|---|---|
| 3B | ~2 GB | ~3.5 GB | ~7 GB | Yes |
| 7–8B | ~4.5 GB | ~8 GB | ~16 GB | Yes |
| 14B | ~9 GB | ~16 GB | ~30 GB | Yes (Q4_K_M, Q8_0) |
| 27–32B | ~17–20 GB | ~35 GB | — | Q4_K_M only |
| 35B | ~24 GB | — | — | Tight; KV cache may OOM |
| 70B+ | ~40 GB+ | — | — | No |

---

## Local Model Catalog

Current models on the `crew-chief-models` volume. Updated manually after each pull.

| Model | Tag | Disk | Quant | Tier | Notes |
|---|---|---|---|---|---|
| Llama 3.2 | `llama3.2:latest` | ~2 GB | Q4_K_M | Fast | Default fast-tier; used by crew-chief listener |
| Llama 3.2 | `llama3.2:3b-instruct-q8_0` | ~3.5 GB | Q8_0 | Fast+ | Better quality for quick tasks |
| Mistral 7B | `mistral:latest` | ~4 GB | Q4_K_M | Mid | General purpose |
| Qwen2.5 Coder | `qwen2.5-coder:7b` | ~4 GB | Q4_K_M | Specialist | Code generation |
| Llama 3.1 8B | `llama3.1:8b` | ~4.5 GB | Q4_K_M | Mid | Strong general baseline |
| DeepSeek Coder | `deepseek-coder:6.7b` | ~3 GB | Q4_K_M | Specialist | Code; use qwen2.5-coder as primary |
| CodeLlama | `codellama:latest` | ~3 GB | Q4_K_M | Specialist | Code legacy; prefer qwen2.5-coder |
| Aya Expanse | `aya-expanse:8b` | ~5 GB | Q4_K_M | Specialist | Multilingual / translation; used by intake |
| Qwen3 14B | `qwen3:14b` | ~9 GB | Q4_K_M | Mid+ | Strong reasoning and instruction-following |
| Qwen3 14B | `qwen3:14b-q8_0` | ~16 GB | Q8_0 | Mid++ | Near-fp16 quality mid-tier |
| Gemma3 27B | `gemma3:27b-it-qat` | ~18 GB | QAT | High | Google flagship; 128K context; strong summarise/document/translate; architectural diversity from Qwen |
| Qwen3 32B | `qwen3:32b` | ~20 GB | Q4_K_M | High | Best single-model quality in 24 GB |
| Qwen3.5 27B | `qwen3.5:27b` | ~17 GB | Q4_K_M | High+ | Multimodal (text + image), 256K context |

---

## Model Families

### Gemma3 (2025 — Google flagship)

- Sizes: 270m, 1b, 4b, 12b, 27b
- Context: 128K tokens (all sizes)
- Inputs: text + image
- QAT variants available for 1b/4b/12b/27b — prefer `*-it-qat` over `*-it-q4_K_M` at the same VRAM cost for better quality
- `gemma3:27b-it-qat` (18 GB) fits comfortably on 24 GB; Q8 (30 GB) does not
- Strong for summarisation, document analysis, and multilingual tasks; provides architectural diversity from the Qwen family

---

### Qwen3.5 (2026 — recommended flagship)

- Sizes: 0.8b, 2b, 4b, 9b, 27b, 35b, 122b
- Context: 256K tokens
- Inputs: text + image (all standard variants)
- `qwen3.5:27b` (17 GB) fits comfortably; `qwen3.5:35b` (24 GB) is borderline — KV cache may OOM at long contexts

### Qwen3 (2025)

- Sizes: 0.6b, 1.7b, 4b, 8b, 14b, 32b
- Context: 40K tokens
- Text only
- Official quantization tags for 14b: `q4_K_M` (9 GB), `q8_0` (16 GB), `fp16` (30 GB — too large)
- No `q5_K_M` tag in the official library

### Llama 3.2 / 3.1

- 3B (llama3.2) is the crew-chief default fast tier; `q8_0` variant gives near-fp16 quality at 3.5 GB
- 8B (llama3.1) is a strong general mid-tier at 4.5 GB

---

## Task Chains

Per-task Ollama model chains are configured under `[llm.task_chains]` in
`config/listener/config.toml` (gitignored). Three models per task before any
external API is reached. A fourth slot is reserved for future expansion.

`FallbackProvider` tries each model in order and advances on error — including
context-length overflow, so the document chain naturally escalates by context window.

```toml
[llm.task_chains]
# Code specialist → near-fp16 reasoning → highest quality
code      = ["qwen2.5-coder:7b",  "qwen3:14b-q8_0",  "qwen3:32b"]

# Fast near-fp16 → Google diversity → Qwen ceiling
reasoning = ["qwen3:14b-q8_0",    "gemma3:27b",       "qwen3:32b"]
summarise = ["qwen3:14b-q8_0",    "gemma3:27b",       "qwen3:32b"]

# Multilingual specialist → near-fp16 → Google multilingual
translate = ["aya-expanse:8b",    "qwen3:14b-q8_0",   "gemma3:27b"]

# Context-window escalation: 40K → 128K → 256K
document  = ["qwen3:32b",         "gemma3:27b",        "qwen3.5:27b"]

# Ultra-fast dispatch → balanced → quality ceiling
default   = ["llama3.2:latest",   "qwen3:14b",         "qwen3:32b"]
```

---

## Decision Guide

| Situation | Recommended model |
|---|---|
| Simple dispatch / health check | `llama3.2:latest` (fast, 2 GB) |
| General Q&A, moderate reasoning | `qwen3:14b` (9 GB) |
| High-quality reasoning, no image | `qwen3:14b-q8_0` (16 GB) or `qwen3:32b` (20 GB) |
| Document analysis, short–medium (≤40K tokens) | `qwen3:32b` (20 GB) |
| Document analysis, long (40K–128K tokens) | `gemma3:27b-it-qat` (18 GB, 128K ctx) |
| Document analysis, very long (128K–256K tokens) | `qwen3.5:27b` (17 GB, 256K ctx) |
| Document with images | `qwen3.5:27b` (multimodal) |
| Code generation | `qwen2.5-coder:7b` (4 GB) |
| Multilingual / translation | `aya-expanse:8b` (5 GB) |
| High-quality summarisation | `gemma3:27b-it-qat` (18 GB) |
| Maximum quality within 24 GB | `qwen3:32b` (20 GB) |

---

## Benchmark Results

Run `python3 scripts/benchmark.py` to generate a result table. Pass `--json` to persist
results across sessions.

See [`scripts/benchmark.py`](../scripts/benchmark.py) for full usage.
